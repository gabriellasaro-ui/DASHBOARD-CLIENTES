"""Sincronizacao centralizada das APIs de midia para o PostgreSQL."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

logger = logging.getLogger(__name__)

from core.data import _google_query, _google_values, _meta_values, _status, clear_cache
from core.integrations import IntegrationError, meta_ads
from core.storage import (
    mark_media_sync_window,
    media_coverage_bounds,
    replace_media_rows,
    set_media_sync_state,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _base_row(tenant_id: int, platform: str, account_id: str, day: str, level: str, entity_id: str):
    return {
        "tenant_id": tenant_id,
        "platform": platform,
        "metric_date": day,
        "level": level,
        "entity_id": str(entity_id),
        "account_id": account_id,
        "name": None,
        "status": "active",
        "campaign_id": None,
        "campaign_name": None,
        "parent_id": None,
        "parent_name": None,
        "investimento": 0.0,
        "receita": 0.0,
        "impressoes": 0,
        "cliques": 0,
        "leads": 0.0,
        "conversoes": 0.0,
        "alcance": 0,
        "creative_url": None,
        "creative_quality": None,
        "quality_score": None,
        "match_type": None,
        "impression_share": None,
        "top_impression_share": None,
        "updated_at": _now(),
    }


def _with_metrics(target: dict, values: dict) -> dict:
    for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance"):
        target[key] = values.get(key, 0)
    return target


META_CHECK_ATTEMPTS = 3


def _close(value: float, expected: float) -> bool:
    """Igual o bastante: o dia corrente ainda gasta entre uma consulta e outra."""
    return abs(value - expected) <= max(1.0, abs(expected) * 0.01)


def _checked_meta_insights(account_id: str, start: date, end: date) -> tuple[list[dict], list[dict]]:
    """
    Quebra diária da Meta, conferida contra o total do período antes de valer.

    A Meta às vezes devolve a quebra diária com gasto e impressões ZERADOS —
    sem erro, com status 200. Foi o que regravou zeros por cima de dados bons
    num ciclo do worker, enquanto a mesma consulta, segundos depois, vinha
    certa. Por isso a soma dos dias (conta e anúncios) tem de bater com uma
    consulta agregada do mesmo período; se não bater, tenta de novo, e se
    continuar errado FALHA — os dados anteriores ficam no banco.
    """
    window = {"start": start.isoformat(), "end": end.isoformat()}
    for attempt in range(1, META_CHECK_ATTEMPTS + 1):
        with ThreadPoolExecutor(max_workers=3) as pool:
            account_future = pool.submit(meta_ads.insights, account_id, level="account", time_increment=1, **window)
            ads_future = pool.submit(meta_ads.insights, account_id, level="ad", time_increment=1, **window)
            expected_future = pool.submit(meta_ads.window_totals, account_id, **window)
            account_rows = account_future.result()
            ad_rows = ads_future.result()
            expected = expected_future.result()

        def total(rows, key):
            return sum(float(row.get(key) or 0) for row in rows)

        checks = (
            _close(total(account_rows, "spend"), expected["spend"]),
            _close(total(ad_rows, "spend"), expected["spend"]),
            _close(total(account_rows, "impressions"), expected["impressions"]),
        )
        if all(checks):
            return account_rows, ad_rows
        logger.warning(
            "Meta %s %s a %s: quebra diária não fecha com o total (conta %.2f, anúncios %.2f, "
            "esperado %.2f). Tentativa %s de %s.",
            account_id, start, end, total(account_rows, "spend"), total(ad_rows, "spend"),
            expected["spend"], attempt, META_CHECK_ATTEMPTS,
        )
        time.sleep(5 * attempt)

    raise IntegrationError(
        "meta",
        "A Meta devolveu números diários que não fecham com o total do período. "
        "Os dados anteriores foram preservados; nova tentativa no próximo ciclo.",
    )


def fetch_meta_rows(tenant: dict, start: date, end: date) -> list[dict]:
    account_id = tenant.get("meta_ad_account_id")
    if not account_id:
        return []
    account_rows, ad_rows = _checked_meta_insights(account_id, start, end)

    ad_ids = {str(row.get("ad_id")) for row in ad_rows if row.get("ad_id")}
    try:
        creatives = meta_ads.ad_creatives(account_id, ad_ids)
    except IntegrationError as exc:
        # As métricas valem mais que as imagens, então a falha de criativo não
        # derruba a sincronização. Mas precisa aparecer no log: era um `except`
        # mudo, e o sintoma no produto virava "os anúncios não têm imagem",
        # sem nada que apontasse para a causa.
        logger.warning(
            "Criativos da conta %s não vieram (%s anúncios): %s",
            account_id, len(ad_ids), exc,
        )
        creatives = {}

    rows = []
    for source in account_rows:
        day = source.get("date_start")
        if not day:
            continue
        row = _base_row(tenant["id"], "meta", account_id, day, "account", account_id)
        row["name"] = tenant.get("name")
        rows.append(_with_metrics(row, _meta_values(source)))

    for source in ad_rows:
        day = source.get("date_start")
        ad_id = str(source.get("ad_id") or "")
        if not day or not ad_id:
            continue
        creative = creatives.get(ad_id, {})
        row = _base_row(tenant["id"], "meta", account_id, day, "ad", ad_id)
        row.update(
            {
                "name": source.get("ad_name") or f"Anuncio {ad_id}",
                "status": _status(creative.get("status") or "ACTIVE"),
                "campaign_id": str(source.get("campaign_id") or ""),
                "campaign_name": source.get("campaign_name"),
                "parent_id": str(source.get("adset_id") or ""),
                "parent_name": source.get("adset_name"),
                "creative_url": creative.get("url"),
                "creative_quality": creative.get("quality"),
            }
        )
        rows.append(_with_metrics(row, _meta_values(source)))
    return rows


def _google_entity_row(tenant: dict, account_id: str, source: dict, level: str) -> dict | None:
    day = source.get("segments", {}).get("date")
    if not day:
        return None
    campaign = source.get("campaign", {})
    group = source.get("adGroup", {})
    if level == "campaign":
        node = campaign
        entity_id = node.get("id")
        name = node.get("name")
        status = node.get("status")
    elif level == "group":
        node = group
        entity_id = node.get("id")
        name = node.get("name")
        status = node.get("status")
    elif level == "keyword":
        node = source.get("adGroupCriterion", {})
        entity_id = node.get("criterionId")
        name = node.get("keyword", {}).get("text")
        status = node.get("status")
    else:
        wrapper = source.get("adGroupAd", {})
        node = wrapper.get("ad", {})
        entity_id = node.get("id") or wrapper.get("resourceName")
        name = node.get("name") or f"Anuncio {node.get('id', '')}".strip()
        status = wrapper.get("status")
    if not entity_id:
        return None

    row = _base_row(tenant["id"], "google", account_id, day, level, str(entity_id))
    row.update(
        {
            "name": name or f"Item {entity_id}",
            "status": _status(status),
            "campaign_id": str(campaign.get("id") or ""),
            "campaign_name": campaign.get("name"),
            "parent_id": str(group.get("id") or ""),
            "parent_name": group.get("name"),
        }
    )
    metrics = source.get("metrics", {})
    row = _with_metrics(row, _google_values(metrics))
    if level == "keyword":
        criterion = source.get("adGroupCriterion", {})
        row["quality_score"] = criterion.get("qualityInfo", {}).get("qualityScore")
        row["match_type"] = criterion.get("keyword", {}).get("matchType")
    if level == "campaign":
        row["impression_share"] = metrics.get("searchImpressionShare")
        row["top_impression_share"] = metrics.get("searchTopImpressionShare")
    return row


def fetch_google_rows(tenant: dict, start: date, end: date) -> list[dict]:
    account_id = tenant.get("google_ads_customer_id")
    if not account_id:
        return []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            level: pool.submit(_google_query, account_id, start, end, level)
            for level in ("account", "campaign", "group", "keyword", "ad")
        }
        source_rows = {level: future.result() for level, future in futures.items()}

    rows = []
    for source in source_rows.pop("account"):
        day = source.get("segments", {}).get("date")
        if not day:
            continue
        row = _base_row(tenant["id"], "google", account_id, day, "account", account_id)
        row["name"] = tenant.get("name")
        rows.append(_with_metrics(row, _google_values(source.get("metrics", {}))))

    for level, items in source_rows.items():
        for source in items:
            row = _google_entity_row(tenant, account_id, source, level)
            # Sem nenhuma atividade no dia a linha só ocupa espaço: o Google
            # devolve também as campanhas paradas, com tudo zerado.
            if row and any(row[key] for key in ("investimento", "impressoes", "cliques", "conversoes")):
                rows.append(row)
    return rows


def sync_platform(tenant: dict, platform: str, start: date, end: date) -> int:
    account_id = tenant.get("meta_ad_account_id" if platform == "meta" else "google_ads_customer_id")
    if not account_id:
        return 0
    started_at = _now()
    set_media_sync_state(
        tenant["id"], platform, "running", started_at=started_at,
        window_start=start.isoformat(), window_end=end.isoformat(),
    )
    try:
        rows = fetch_meta_rows(tenant, start, end) if platform == "meta" else fetch_google_rows(tenant, start, end)
        total = replace_media_rows(tenant["id"], platform, start.isoformat(), end.isoformat(), rows)
        mark_media_sync_window(tenant["id"], platform, start.isoformat(), end.isoformat())
        set_media_sync_state(
            tenant["id"], platform, "success", started_at=started_at, finished_at=_now(),
            window_start=start.isoformat(), window_end=end.isoformat(), rows_synced=total,
        )
        # O painel guarda o dataset em memória; sem invalidar aqui, o dado
        # recém-gravado só aparecia no próximo "Atualizar" ou dez minutos depois.
        clear_cache()
        return total
    except IntegrationError as exc:
        set_media_sync_state(
            tenant["id"], platform, "error", started_at=started_at, finished_at=_now(),
            window_start=start.isoformat(), window_end=end.isoformat(), error_message=str(exc),
            request_id=exc.request_id,
        )
        raise
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        set_media_sync_state(
            tenant["id"], platform, "error", started_at=started_at, finished_at=_now(),
            window_start=start.isoformat(), window_end=end.isoformat(), error_message=detail,
        )
        raise


_kickoff_lock = threading.Lock()
_kickoff_running: set[int] = set()


def kickoff_first_sync(tenant: dict, days: int = 30) -> None:
    """
    Busca os dados do cliente AGORA, em segundo plano.

    Sem isso, um cliente recém-criado ficava com o painel vazio até o worker
    passar — e se o worker não estivesse rodando, ficava vazio para sempre.
    Quem acabou de vincular as contas espera ver número, não uma tela em
    branco sem explicação.

    Roda numa thread para o admin não travar nos ~30 s das duas APIs, e um
    cliente por vez para dois cliques em "salvar" não dispararem a mesma
    carga duas vezes.
    """
    tenant_id = tenant.get("id")
    if not tenant_id:
        return
    if not (tenant.get("meta_ad_account_id") or tenant.get("google_ads_customer_id")):
        return

    with _kickoff_lock:
        if tenant_id in _kickoff_running:
            return
        _kickoff_running.add(tenant_id)

    def run():
        today = datetime.now(UTC).date()
        start = today - timedelta(days=max(1, days) - 1)
        try:
            for platform in ("meta", "google"):
                try:
                    sync_platform(tenant, platform, start, today)
                except Exception as exc:
                    # Uma plataforma falhar não pode impedir a outra: o estado
                    # do erro já ficou gravado por `sync_platform`.
                    logger.warning("Sync inicial de %s falhou para %s: %s",
                                   platform, tenant.get("name"), exc)
        finally:
            with _kickoff_lock:
                _kickoff_running.discard(tenant_id)

    threading.Thread(target=run, name=f"sync-inicial-{tenant_id}", daemon=True).start()


def sync_window_for(tenant_id: int, platform: str, today: date, refresh_days: int, backfill_days: int) -> tuple[date, date]:
    bounds = media_coverage_bounds(tenant_id, platform)
    if not bounds:
        return today - timedelta(days=max(1, refresh_days) - 1), today
    return today - timedelta(days=max(1, refresh_days) - 1), today


def historical_window_for(tenant_id: int, platform: str, today: date, backfill_days: int, chunk_days: int = 30):
    bounds = media_coverage_bounds(tenant_id, platform)
    if not bounds:
        return None
    target = today - timedelta(days=max(1, backfill_days) - 1)
    earliest = date.fromisoformat(bounds["first_date"])
    if earliest <= target:
        return None
    end = earliest - timedelta(days=1)
    start = max(target, end - timedelta(days=max(1, chunk_days) - 1))
    return start, end


def refresh_recent(tenant: dict, days: int = 3) -> list[str]:
    """
    Busca agora os últimos dias do cliente, esperando o resultado.

    É o que o botão "Atualizar" faz: o cliente que acabou de mexer numa
    campanha quer ver o número de hoje, não o do último ciclo do worker.
    Devolve as plataformas que falharam, para a tela poder avisar.
    """
    today = datetime.now(UTC).date()
    start = today - timedelta(days=max(1, days) - 1)
    failed = []
    for platform in ("meta", "google"):
        try:
            sync_platform(tenant, platform, start, today)
        except Exception as exc:
            logger.warning("Atualização de %s falhou para %s: %s", platform, tenant.get("name"), exc)
            failed.append(platform)
    return failed


def rebuild_history(tenant: dict, platform: str, days: int, chunk_days: int = 30, log=print) -> None:
    """
    Regrava o histórico inteiro em blocos, do mais recente para o mais antigo.

    O backfill normal só avança para trás a partir da data mais antiga já
    gravada — período gravado com erro nunca era corrigido. Isto refaz tudo.
    """
    today = datetime.now(UTC).date()
    target = today - timedelta(days=max(1, days) - 1)
    end = today
    while end >= target:
        start = max(target, end - timedelta(days=max(1, chunk_days) - 1))
        total = sync_platform(tenant, platform, start, end)
        log(f"{tenant.get('slug')} {platform}: {total} linhas ({start} a {end})")
        end = start - timedelta(days=1)
