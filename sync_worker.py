"""Worker unico que sincroniza Meta/Google e persiste tudo no PostgreSQL.

Uso:
    python sync_worker.py --once
    python sync_worker.py --interval 600
    python sync_worker.py --rebuild 550     # regrava o historico inteiro

O `app.py` tambem sobe este mesmo ciclo numa thread (`start_background_worker`)
para que o painel nunca dependa de alguem lembrar de abrir um segundo terminal:
sem isso um cliente recem-cadastrado ficava zerado indefinidamente. Os dois
caminhos disputam o mesmo arquivo de trava, entao rodar o comando acima com o
painel aberto continua sendo seguro -- quem chegar depois desiste.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date
import os
from pathlib import Path
import sys
import threading
import time

from core.data import DEFAULT_PERIOD, clear_cache, get_dataset
from core.storage import init_db, list_tenants
from core.sync import historical_window_for, rebuild_history, sync_platform, sync_window_for


BASE_DIR = Path(__file__).resolve().parent
LOCK_PATH = BASE_DIR / "runtime" / "ads-sync.lock"


@contextmanager
def single_worker():
    """Impede dois workers locais de consumirem a mesma cota das APIs."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        handle.close()
        raise RuntimeError("Ja existe um sincronizador de midia em execucao.")
    try:
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_cycle(
    refresh_days: int,
    backfill_days: int,
    history_chunk_days: int,
    history_chunks_per_cycle: int = 1,
) -> None:
    today = date.today()
    tenants = [tenant for tenant in list_tenants() if tenant.get("status") == "active"]
    for tenant in tenants:
        for platform, field in (("meta", "meta_ad_account_id"), ("google", "google_ads_customer_id")):
            if not tenant.get(field):
                continue
            start, end = sync_window_for(tenant["id"], platform, today, refresh_days, backfill_days)
            try:
                total = sync_platform(tenant, platform, start, end)
                log(f"{tenant['slug']} {platform}: {total} linhas ({start} a {end})")
            except Exception as exc:
                log(f"{tenant['slug']} {platform}: ERRO - {type(exc).__name__}: {exc}")
                continue

            for _ in range(max(0, history_chunks_per_cycle)):
                history = historical_window_for(
                    tenant["id"], platform, today, backfill_days, chunk_days=history_chunk_days
                )
                if not history:
                    break
                history_start, history_end = history
                try:
                    total = sync_platform(tenant, platform, history_start, history_end)
                    log(
                        f"{tenant['slug']} {platform}: backfill {total} linhas "
                        f"({history_start} a {history_end})"
                    )
                except Exception as exc:
                    log(f"{tenant['slug']} {platform}: backfill adiado - {type(exc).__name__}: {exc}")
                    break
    clear_cache()

    # Deixa pronto o que o cliente vê ao abrir o painel: o dataset do período
    # padrão e o alcance dele, que só existe consultando a Meta por período.
    for tenant in tenants:
        try:
            get_dataset(DEFAULT_PERIOD, tenant_id=tenant["id"])
        except Exception as exc:
            log(f"{tenant['slug']}: pre-carga adiada - {type(exc).__name__}: {exc}")


_embedded_started = False
_embedded_lock = threading.Lock()


def start_background_worker() -> bool:
    """
    Sobe o ciclo de sincronizacao junto com o painel.

    Retorna se esta thread ficou responsavel pelo ciclo. Ela nao fica em tres
    situacoes, todas normais:

    * `ADS_SYNC_EMBEDDED=false` -- a hospedagem roda o worker por fora;
    * ja existe um `sync_worker.py` com a trava na mao;
    * a funcao foi chamada duas vezes no mesmo processo.

    A thread e daemon: fechar o painel encerra a sincronizacao junto, sem
    deixar processo orfao consumindo cota das APIs.
    """
    global _embedded_started

    if os.getenv("ADS_SYNC_EMBEDDED", "true").strip().lower() in ("false", "0", "no"):
        return False

    with _embedded_lock:
        if _embedded_started:
            return False
        _embedded_started = True

    interval = int(os.getenv("ADS_SYNC_INTERVAL_SECONDS", "600"))
    refresh_days = int(os.getenv("ADS_SYNC_REFRESH_DAYS", "14"))
    backfill_days = int(os.getenv("ADS_SYNC_BACKFILL_DAYS", "550"))
    chunk_days = int(os.getenv("ADS_SYNC_HISTORY_CHUNK_DAYS", "60"))

    def loop() -> None:
        try:
            with single_worker():
                log("sincronizacao automatica ligada")
                while True:
                    started = time.monotonic()
                    try:
                        run_cycle(refresh_days, backfill_days, chunk_days)
                    except Exception as exc:  # o painel nao pode cair junto
                        log(f"ciclo falhou - {type(exc).__name__}: {exc}")
                    time.sleep(max(30, interval - int(time.monotonic() - started)))
        except RuntimeError:
            # Outro worker ja esta cuidando disso.
            pass

    threading.Thread(target=loop, name="ads-sync", daemon=True).start()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza APIs de midia com o PostgreSQL")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("ADS_SYNC_INTERVAL_SECONDS", "600")),
        help="Intervalo entre ciclos em segundos",
    )
    parser.add_argument("--refresh-days", type=int, default=int(os.getenv("ADS_SYNC_REFRESH_DAYS", "14")))
    parser.add_argument("--backfill-days", type=int, default=int(os.getenv("ADS_SYNC_BACKFILL_DAYS", "550")))
    parser.add_argument(
        "--history-chunk-days",
        type=int,
        default=int(os.getenv("ADS_SYNC_HISTORY_CHUNK_DAYS", "60")),
    )
    parser.add_argument("--history-chunks-per-cycle", type=int, default=1)
    parser.add_argument(
        "--rebuild",
        type=int,
        metavar="DIAS",
        help="Regrava os ultimos DIAS de todos os clientes e encerra",
    )
    args = parser.parse_args()

    init_db()
    with single_worker():
        if args.rebuild:
            for tenant in list_tenants():
                if tenant.get("status") != "active":
                    continue
                for platform, field in (("meta", "meta_ad_account_id"), ("google", "google_ads_customer_id")):
                    if not tenant.get(field):
                        continue
                    try:
                        rebuild_history(tenant, platform, args.rebuild, args.history_chunk_days, log=log)
                    except Exception as exc:
                        log(f"{tenant['slug']} {platform}: ERRO - {type(exc).__name__}: {exc}")
            return 0
        while True:
            started = time.monotonic()
            run_cycle(
                args.refresh_days,
                args.backfill_days,
                args.history_chunk_days,
                args.history_chunks_per_cycle,
            )
            if args.once:
                return 0
            elapsed = time.monotonic() - started
            wait = max(30, args.interval - int(elapsed))
            log(f"proximo ciclo em {wait} segundos")
            time.sleep(wait)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
