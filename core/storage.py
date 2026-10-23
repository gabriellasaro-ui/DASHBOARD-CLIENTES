"""Persistência de autenticação, tenants, identidade e vínculos de mídia.

Produção usa PostgreSQL em schema próprio. SQLite permanece como backend
isolado para os testes locais, sem duplicar regras de negócio.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash

from core import tenant_theme


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DEFAULT_DB_PATH = Path(os.getenv("PULSE_DB_PATH", BASE_DIR / "data" / "pulse.db"))
DB_PATH = DEFAULT_DB_PATH
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_SCHEMA = os.getenv("PULSE_DB_SCHEMA", "dashboard_clientes").strip()
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

if not SCHEMA_NAME.fullmatch(DB_SCHEMA):
    raise RuntimeError("PULSE_DB_SCHEMA possui um nome inválido.")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DatabaseConnection:
    def __init__(self, raw, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def execute(self, statement: str, params=()):
        if self.postgres:
            statement = statement.replace("?", "%s")
        return self.raw.execute(statement, params)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self.raw.executescript(script)
            return
        for statement in (part.strip() for part in script.split(";")):
            if statement:
                self.raw.execute(statement)

    def executemany(self, statement: str, params):
        if self.postgres:
            statement = statement.replace("?", "%s")
            with self.raw.cursor() as cursor:
                return cursor.executemany(statement, params)
        return self.raw.executemany(statement, params)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def _use_postgres() -> bool:
    # Os testes trocam DB_PATH para um arquivo temporário e ficam no SQLite.
    return bool(DATABASE_URL) and DB_PATH == DEFAULT_DB_PATH


@contextmanager
def connection():
    if _use_postgres():
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
        raw.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(DB_SCHEMA)))
        db = DatabaseConnection(raw, True)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(DB_PATH)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        db = DatabaseConnection(raw, False)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    if _use_postgres():
        with psycopg.connect(DATABASE_URL, connect_timeout=15) as raw:
            try:
                raw.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(DB_SCHEMA)))
            except (psycopg.errors.DuplicateSchema, psycopg.errors.UniqueViolation):
                # Dois processos do servidor podem iniciar juntos. O schema já
                # existir nesse instante é sucesso, não falha de inicialização.
                raw.rollback()

    with connection() as db:
        if db.postgres:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    logo_data TEXT,
                    meta_ad_account_id TEXT,
                    google_ads_customer_id TEXT,
                    primary_color TEXT NOT NULL DEFAULT '#E5001A',
                    secondary_color TEXT NOT NULL DEFAULT '#0B0B0D',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'inactive')),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('superadmin', 'client_admin', 'client')),
                    active SMALLINT NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
                """
            )
        else:
            db.executescript(
                """
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                logo_data TEXT,
                meta_ad_account_id TEXT,
                google_ads_customer_id TEXT,
                primary_color TEXT NOT NULL DEFAULT '#E5001A',
                secondary_color TEXT NOT NULL DEFAULT '#0B0B0D',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('superadmin', 'client_admin', 'client')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
                """
            )

            # Migração aditiva para bancos SQLite anteriores às integrações.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tenants)")}
            if "meta_ad_account_id" not in columns:
                db.execute("ALTER TABLE tenants ADD COLUMN meta_ad_account_id TEXT")
            if "google_ads_customer_id" not in columns:
                db.execute("ALTER TABLE tenants ADD COLUMN google_ads_customer_id TEXT")
        # Tema completo (fonte, fundo, texto, cards, menu, cantos) como JSON:
        # coluna única para cada ajuste novo não exigir outra migração.
        if db.postgres:
            db.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS theme_data TEXT")
        elif "theme_data" not in {row["name"] for row in db.execute("PRAGMA table_info(tenants)")}:
            db.execute("ALTER TABLE tenants ADD COLUMN theme_data TEXT")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_meta_account "
            "ON tenants(meta_ad_account_id) WHERE meta_ad_account_id IS NOT NULL"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_google_account "
            "ON tenants(google_ads_customer_id) WHERE google_ads_customer_id IS NOT NULL"
        )
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS media_daily_metrics (
                tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                metric_date TEXT NOT NULL,
                level TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                name TEXT,
                status TEXT,
                campaign_id TEXT,
                campaign_name TEXT,
                parent_id TEXT,
                parent_name TEXT,
                investimento REAL NOT NULL DEFAULT 0,
                receita REAL NOT NULL DEFAULT 0,
                impressoes INTEGER NOT NULL DEFAULT 0,
                cliques INTEGER NOT NULL DEFAULT 0,
                leads REAL NOT NULL DEFAULT 0,
                conversoes REAL NOT NULL DEFAULT 0,
                alcance INTEGER NOT NULL DEFAULT 0,
                creative_url TEXT,
                creative_quality TEXT,
                quality_score REAL,
                match_type TEXT,
                impression_share REAL,
                top_impression_share REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, platform, metric_date, level, entity_id)
            );

            CREATE INDEX IF NOT EXISTS idx_media_daily_lookup
            ON media_daily_metrics(tenant_id, platform, metric_date, level);

            CREATE TABLE IF NOT EXISTS media_sync_state (
                tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                window_start TEXT,
                window_end TEXT,
                rows_synced INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                request_id TEXT,
                PRIMARY KEY (tenant_id, platform)
            );

            CREATE TABLE IF NOT EXISTS media_sync_windows (
                tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, platform, window_start, window_end)
            );

            CREATE TABLE IF NOT EXISTS media_period_reach (
                tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                account_id TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                reach BIGINT NOT NULL DEFAULT 0,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, platform, account_id, start_date, end_date)
            );

            CREATE TABLE IF NOT EXISTS user_invites (
                token TEXT PRIMARY KEY,
                tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                invited_by BIGINT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                accepted_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_invites_tenant ON user_invites(tenant_id);
            """
        )

        admin_email = os.getenv("PULSE_ADMIN_EMAIL", "admin").strip().lower()
        exists = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO users (tenant_id, name, email, password_hash, role, created_at) "
                "VALUES (NULL, ?, ?, ?, 'superadmin', ?)",
                (
                    os.getenv("PULSE_ADMIN_NAME", "Administrador V4"),
                    admin_email,
                    generate_password_hash(os.getenv("PULSE_ADMIN_PASSWORD", "admin")),
                    _now(),
                ),
            )

        _migrate_memberships(db)


def _migrate_memberships(db) -> None:
    """
    Uma pessoa, vários clientes.

    Antes cada usuário tinha UM `tenant_id` e o e-mail era único — quem
    atendia dois clientes precisava de dois e-mails. Agora o vínculo é a tabela
    `tenant_members` (pessoa × cliente, com papel e status por cliente), e o
    mesmo login entra em quantos clientes tiver acesso.

    A migração copia o vínculo antigo e zera `users.tenant_id` na mesma
    transação: assim roda uma vez só, e um acesso removido depois não volta
    na próxima inicialização.
    """
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenant_members (
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('client_admin', 'client')),
            active SMALLINT NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, tenant_id)
        );

        CREATE INDEX IF NOT EXISTS idx_members_tenant ON tenant_members(tenant_id);
        """
    )
    # Último cliente aberto: quem tem vários volta para onde parou.
    if db.postgres:
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_tenant_id BIGINT")
    elif "last_tenant_id" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
        db.execute("ALTER TABLE users ADD COLUMN last_tenant_id INTEGER")

    db.execute(
        "INSERT INTO tenant_members (user_id, tenant_id, role, active, created_at) "
        "SELECT id, tenant_id, role, active, created_at FROM users "
        "WHERE tenant_id IS NOT NULL AND role IN ('client_admin', 'client') "
        "ON CONFLICT (user_id, tenant_id) DO NOTHING"
    )
    db.execute(
        "UPDATE users SET last_tenant_id = COALESCE(last_tenant_id, tenant_id), tenant_id = NULL "
        "WHERE tenant_id IS NOT NULL AND role IN ('client_admin', 'client')"
    )


def _clean_color(value: str | None, fallback: str) -> str:
    value = (value or "").strip().upper()
    if not HEX_COLOR.fullmatch(value):
        raise ValueError("Informe uma cor hexadecimal válida, como #E5001A.")
    return value or fallback


def _clean_slug(value: str | None) -> str:
    value = (value or "").strip().lower()
    if not SLUG.fullmatch(value):
        raise ValueError("O identificador deve usar letras minúsculas, números e hífens.")
    return value


def _validate_account(name: str | None, email: str | None, password: str | None) -> tuple[str, str, str]:
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""
    if len(name) < 2:
        raise ValueError("Informe o nome do responsável.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Informe um e-mail válido.")
    if len(password) < 8:
        raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
    return name, email, password


def create_tenant(
    *,
    name: str | None,
    slug: str | None,
    owner_name: str | None,
    owner_email: str | None,
    password: str | None,
    primary_color: str | None = "#E5001A",
    secondary_color: str | None = "#0B0B0D",
    logo_data: str | None = None,
    meta_ad_account_id: str | None = None,
    google_ads_customer_id: str | None = None,
    theme: dict | None = None,
) -> dict:
    tenant_name = (name or "").strip()
    if len(tenant_name) < 2:
        raise ValueError("Informe o nome do cliente.")
    slug = _clean_slug(slug)
    # E-mail que já tem conta vira responsável do cliente novo com a senha que
    # já usa — a mesma pessoa pode responder por vários clientes. Senha só é
    # exigida para conta nova.
    existing = _user_by_email((owner_email or "").strip().lower())
    if existing and existing["role"] == "superadmin":
        raise ValueError("Este e-mail é da conta da agência.")
    if existing:
        owner_name, owner_email = (owner_name or "").strip() or existing["name"], existing["email"]
    else:
        owner_name, owner_email, password = _validate_account(owner_name, owner_email, password)
    primary_color = _clean_color(primary_color, "#E5001A")
    secondary_color = _clean_color(secondary_color, "#0B0B0D")
    meta_ad_account_id = _clean_meta_account_id(meta_ad_account_id)
    google_ads_customer_id = _clean_google_customer_id(google_ads_customer_id)
    theme_data = tenant_theme.dumps(tenant_theme.clean_theme(theme or {}))

    try:
        with connection() as db:
            cursor = db.execute(
                "INSERT INTO tenants "
                "(name, slug, logo_data, meta_ad_account_id, google_ads_customer_id, "
                "primary_color, secondary_color, theme_data, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)"
                + (" RETURNING id" if db.postgres else ""),
                (
                    tenant_name, slug, logo_data, meta_ad_account_id,
                    google_ads_customer_id, primary_color, secondary_color, theme_data, _now(),
                ),
            )
            tenant_id = cursor.fetchone()["id"] if db.postgres else cursor.lastrowid
            owner_id = existing["id"] if existing else _insert_user(db, owner_name, owner_email, password)
            _add_membership(db, owner_id, tenant_id, "client_admin")
    except (sqlite3.IntegrityError, psycopg.IntegrityError) as exc:
        message = str(exc).lower()
        if "slug" in message:
            raise ValueError("Este identificador de cliente já está em uso.") from exc
        if "email" in message:
            raise ValueError("Este e-mail já possui uma conta.") from exc
        if "meta_ad_account_id" in message:
            raise ValueError("Esta conta Meta Ads já está vinculada a outro cliente.") from exc
        if "google_ads_customer_id" in message:
            raise ValueError("Esta conta Google Ads já está vinculada a outro cliente.") from exc
        raise ValueError("Não foi possível criar o cliente com estes dados.") from exc

    return get_tenant(tenant_id)


# --------------------------------------------------------------------------
# Pessoas e vínculos com clientes
# --------------------------------------------------------------------------

# Campos do cliente que viajam junto com o usuário (marca, tema, status).
_TENANT_FIELDS = ("tenant_name", "tenant_slug", "logo_data", "primary_color", "secondary_color",
                  "theme_data", "tenant_status")


def _user_by_email(email: str) -> dict | None:
    if not email:
        return None
    with connection() as db:
        row = db.execute("SELECT id, name, email, role FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def _insert_user(db, name: str, email: str, password: str) -> int:
    """Conta nova, sem cliente: o vínculo é sempre um `_add_membership` à parte."""
    cursor = db.execute(
        "INSERT INTO users (tenant_id, name, email, password_hash, role, created_at) "
        "VALUES (NULL, ?, ?, ?, 'client', ?)" + (" RETURNING id" if db.postgres else ""),
        (name, email, generate_password_hash(password), _now()),
    )
    return cursor.fetchone()["id"] if db.postgres else cursor.lastrowid


def _add_membership(db, user_id: int, tenant_id: int, role: str) -> None:
    """Dá acesso ao cliente; se já existia (talvez desativado), reativa com o papel novo."""
    db.execute(
        "INSERT INTO tenant_members (user_id, tenant_id, role, active, created_at) VALUES (?, ?, ?, 1, ?) "
        "ON CONFLICT (user_id, tenant_id) DO UPDATE SET role = excluded.role, active = 1",
        (user_id, tenant_id, role, _now()),
    )


def list_user_tenants(user_id: int | None) -> list[dict]:
    """
    Clientes que a pessoa pode abrir agora: vínculo ativo e cliente ativo.

    Sem logo nem tema — é a lista do seletor, consultada a cada requisição;
    a marca completa só é carregada para o cliente aberto.
    """
    if not user_id:
        return []
    with connection() as db:
        rows = db.execute(
            """
            SELECT m.tenant_id, m.role, t.name AS tenant_name, t.slug AS tenant_slug
            FROM tenant_members m
            JOIN tenants t ON t.id = m.tenant_id
            WHERE m.user_id = ? AND m.active = 1 AND t.status = 'active'
            ORDER BY t.name
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def user_has_tenant(user_id: int | None, tenant_id: int | None) -> bool:
    return any(item["tenant_id"] == tenant_id for item in list_user_tenants(user_id))


def set_last_tenant(user_id: int, tenant_id: int | None) -> None:
    with connection() as db:
        db.execute("UPDATE users SET last_tenant_id = ? WHERE id = ?", (tenant_id, user_id))


def authenticate(email: str | None, password: str | None) -> dict | None:
    """
    Confere e-mail e senha e devolve o usuário no cliente em que ele entra.

    Sem nenhum cliente ativo (todos os acessos removidos ou suspensos), não
    entra: a senha certa não basta para ver um painel vazio.
    """
    email = (email or "").strip().lower()
    with connection() as db:
        row = db.execute(
            "SELECT id, password_hash, active FROM users WHERE email = ?", (email,)
        ).fetchone()
    if not row or not row["active"] or not check_password_hash(row["password_hash"], password or ""):
        return None
    user = get_user(row["id"])
    if not user or (user["role"] != "superadmin" and not user.get("tenant_id")):
        return None
    return user


def get_user(user_id: int | None, tenant_id: int | None = None) -> dict | None:
    """
    O usuário NO CONTEXTO de um cliente.

    `tenant_id`, `role` e os campos de marca são os do cliente aberto: o pedido
    (`tenant_id`), senão o último que a pessoa abriu, senão o primeiro por
    nome. Assim quem lê `user["role"]` recebe o papel NAQUELE cliente — a mesma
    pessoa pode ser responsável num cliente e visualizadora em outro.
    `memberships` traz todos os clientes que ela pode abrir (o seletor do topo).
    """
    if not user_id:
        return None
    with connection() as db:
        row = db.execute(
            "SELECT id, name, email, role, active, last_tenant_id, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None

    user = {**dict(row), "tenant_id": None, **{field: None for field in _TENANT_FIELDS}, "memberships": []}
    if user["role"] == "superadmin":
        return user

    memberships = list_user_tenants(user_id)
    by_id = {item["tenant_id"]: item for item in memberships}
    chosen = by_id.get(tenant_id) or by_id.get(user["last_tenant_id"]) or (memberships[0] if memberships else None)
    user["memberships"] = memberships
    # Sem cliente aberto o papel é o mais restrito; `authenticate` e a sessão
    # recusam esse usuário de qualquer forma.
    user["role"] = chosen["role"] if chosen else "client"
    if not chosen:
        return user

    tenant = get_tenant(chosen["tenant_id"]) or {}
    user.update(
        tenant_id=chosen["tenant_id"],
        tenant_name=tenant.get("name"),
        tenant_slug=tenant.get("slug"),
        logo_data=tenant.get("logo_data"),
        primary_color=tenant.get("primary_color"),
        secondary_color=tenant.get("secondary_color"),
        theme_data=tenant.get("theme_data"),
        tenant_status=tenant.get("status"),
    )
    return user


def get_tenant(tenant_id: int | None) -> dict | None:
    if not tenant_id:
        return None
    with connection() as db:
        row = db.execute(
            """
            SELECT t.*,
                   COUNT(m.user_id) AS user_count,
                   MAX(CASE WHEN m.role = 'client_admin' THEN u.email END) AS owner_email
            FROM tenants t
            LEFT JOIN tenant_members m ON m.tenant_id = t.id
            LEFT JOIN users u ON u.id = m.user_id
            WHERE t.id = ?
            GROUP BY t.id
            """,
            (tenant_id,),
        ).fetchone()
    return dict(row) if row else None


def get_tenant_by_slug(slug: str | None) -> dict | None:
    """Busca segura usada pelas URLs curtas dos clientes, como ``/somaxi``."""
    slug = (slug or "").strip().lower()
    if not SLUG.fullmatch(slug):
        return None
    with connection() as db:
        row = db.execute(
            """
            SELECT t.*,
                   COUNT(m.user_id) AS user_count,
                   MAX(CASE WHEN m.role = 'client_admin' THEN u.email END) AS owner_email
            FROM tenants t
            LEFT JOIN tenant_members m ON m.tenant_id = t.id
            LEFT JOIN users u ON u.id = m.user_id
            WHERE t.slug = ?
            GROUP BY t.id
            """,
            (slug,),
        ).fetchone()
    return dict(row) if row else None


def list_tenants() -> list[dict]:
    with connection() as db:
        rows = db.execute(
            """
            SELECT t.*,
                   COUNT(m.user_id) AS user_count,
                   MAX(CASE WHEN m.role = 'client_admin' THEN u.email END) AS owner_email
            FROM tenants t
            LEFT JOIN tenant_members m ON m.tenant_id = t.id
            LEFT JOIN users u ON u.id = m.user_id
            GROUP BY t.id
            ORDER BY t.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


MEDIA_COLUMNS = (
    "tenant_id", "platform", "metric_date", "level", "entity_id", "account_id",
    "name", "status", "campaign_id", "campaign_name", "parent_id", "parent_name",
    "investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance",
    "creative_url", "creative_quality", "quality_score", "match_type",
    "impression_share", "top_impression_share", "updated_at",
)


def replace_media_rows(
    tenant_id: int,
    platform: str,
    start: str,
    end: str,
    rows: list[dict],
) -> int:
    """Substitui atomicamente uma janela ja validada pelo sincronizador."""
    placeholders = ", ".join("?" for _ in MEDIA_COLUMNS)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in MEDIA_COLUMNS
        if column not in {"tenant_id", "platform", "metric_date", "level", "entity_id"}
    )
    statement = (
        f"INSERT INTO media_daily_metrics ({', '.join(MEDIA_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT (tenant_id, platform, metric_date, level, entity_id) DO UPDATE SET {updates}"
    )
    values = [tuple(row.get(column) for column in MEDIA_COLUMNS) for row in rows]
    with connection() as db:
        db.execute(
            "DELETE FROM media_daily_metrics "
            "WHERE tenant_id = ? AND platform = ? AND metric_date BETWEEN ? AND ?",
            (tenant_id, platform, start, end),
        )
        if values:
            db.executemany(statement, values)
    return len(rows)


def get_media_rows(tenant_id: int, platform: str, start: str, end: str) -> list[dict]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM media_daily_metrics "
            "WHERE tenant_id = ? AND platform = ? AND metric_date BETWEEN ? AND ? "
            "ORDER BY metric_date, level, entity_id",
            (tenant_id, platform, start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def media_data_bounds(tenant_id: int, platform: str) -> dict | None:
    with connection() as db:
        row = db.execute(
            "SELECT MIN(metric_date) AS first_date, MAX(metric_date) AS last_date, COUNT(*) AS total "
            "FROM media_daily_metrics WHERE tenant_id = ? AND platform = ?",
            (tenant_id, platform),
        ).fetchone()
    return dict(row) if row and row["total"] else None


def media_fingerprint(tenant_id: int) -> str:
    """
    Resumo barato do que está gravado para o cliente.

    Muda quando um número muda, e só então. O horário da sincronização não
    serve para isso: o worker roda a cada dez minutos mesmo sem nada novo.
    """
    with connection() as db:
        row = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(investimento), 0) AS spend, "
            "COALESCE(SUM(impressoes), 0) AS impressions, COALESCE(SUM(leads), 0) AS leads "
            "FROM media_daily_metrics WHERE tenant_id = ? AND level = 'account'",
            (tenant_id,),
        ).fetchone()
    return f"{row['total']}:{float(row['spend']):.2f}:{int(row['impressions'])}:{float(row['leads']):.2f}"


def set_media_sync_state(
    tenant_id: int,
    platform: str,
    status: str,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    rows_synced: int = 0,
    error_message: str | None = None,
    request_id: str | None = None,
) -> None:
    with connection() as db:
        db.execute(
            """
            INSERT INTO media_sync_state
                (tenant_id, platform, status, started_at, finished_at, window_start, window_end,
                 rows_synced, error_message, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, platform) DO UPDATE SET
                status = excluded.status,
                started_at = COALESCE(excluded.started_at, media_sync_state.started_at),
                finished_at = COALESCE(excluded.finished_at, media_sync_state.finished_at),
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                rows_synced = excluded.rows_synced,
                error_message = excluded.error_message,
                request_id = excluded.request_id
            """,
            (
                tenant_id, platform, status, started_at, finished_at, window_start, window_end,
                rows_synced, error_message, request_id,
            ),
        )


def get_media_sync_state(tenant_id: int, platform: str) -> dict | None:
    with connection() as db:
        row = db.execute(
            "SELECT * FROM media_sync_state WHERE tenant_id = ? AND platform = ?",
            (tenant_id, platform),
        ).fetchone()
    return dict(row) if row else None


def get_period_reach(tenant_id: int, platform: str, account_id: str, start: str, end: str) -> dict | None:
    """Alcance de um período já buscado (alcance não se soma entre dias)."""
    with connection() as db:
        row = db.execute(
            "SELECT reach, fetched_at FROM media_period_reach "
            "WHERE tenant_id = ? AND platform = ? AND account_id = ? AND start_date = ? AND end_date = ?",
            (tenant_id, platform, account_id, start, end),
        ).fetchone()
    return dict(row) if row else None


def set_period_reach(tenant_id: int, platform: str, account_id: str, start: str, end: str, reach: float) -> None:
    with connection() as db:
        db.execute(
            """
            INSERT INTO media_period_reach (tenant_id, platform, account_id, start_date, end_date, reach, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, platform, account_id, start_date, end_date) DO UPDATE SET
                reach = excluded.reach,
                fetched_at = excluded.fetched_at
            """,
            (tenant_id, platform, account_id, start, end, int(reach or 0), _now()),
        )


def mark_media_sync_window(tenant_id: int, platform: str, start: str, end: str) -> None:
    with connection() as db:
        db.execute(
            """
            INSERT INTO media_sync_windows (tenant_id, platform, window_start, window_end, synced_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, platform, window_start, window_end) DO UPDATE SET
                synced_at = excluded.synced_at
            """,
            (tenant_id, platform, start, end, _now()),
        )


def media_coverage_bounds(tenant_id: int, platform: str) -> dict | None:
    with connection() as db:
        row = db.execute(
            "SELECT MIN(window_start) AS first_date, MAX(window_end) AS last_date, COUNT(*) AS total "
            "FROM media_sync_windows WHERE tenant_id = ? AND platform = ?",
            (tenant_id, platform),
        ).fetchone()
    return dict(row) if row and row["total"] else None


def tenant_stats() -> dict:
    with connection() as db:
        tenant_row = db.execute(
            "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'active') AS active FROM tenants"
        ).fetchone()
        user_row = db.execute(
            "SELECT COUNT(DISTINCT u.id) AS total FROM users u "
            "JOIN tenant_members m ON m.user_id = u.id WHERE u.active = 1 AND m.active = 1"
        ).fetchone()
    return {
        "tenants": tenant_row["total"] or 0,
        "active": tenant_row["active"] or 0,
        "users": user_row["total"] or 0,
    }


def update_tenant_branding(
    tenant_id: int,
    *,
    name: str | None,
    primary_color: str | None,
    secondary_color: str | None,
    logo_data: str | None,
    status: str = "active",
) -> dict:
    tenant_name = (name or "").strip()
    if len(tenant_name) < 2:
        raise ValueError("Informe o nome do cliente.")
    primary_color = _clean_color(primary_color, "#E5001A")
    secondary_color = _clean_color(secondary_color, "#0B0B0D")
    if status not in {"active", "inactive"}:
        raise ValueError("Status inválido.")
    with connection() as db:
        exists = db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not exists:
            raise ValueError("Cliente não encontrado.")
        db.execute(
            """
            UPDATE tenants
            SET name = ?, primary_color = ?, secondary_color = ?, logo_data = ?, status = ?
            WHERE id = ?
            """,
            (tenant_name, primary_color, secondary_color, logo_data, status, tenant_id),
        )
    return get_tenant(tenant_id)


def _clean_meta_account_id(value: str | None) -> str | None:
    value = (value or "").strip().lower().replace("act_", "").replace("-", "").replace(" ", "")
    if not value:
        return None
    if not value.isdigit():
        raise ValueError("Selecione uma conta Meta Ads válida.")
    return f"act_{value}"


def _clean_google_customer_id(value: str | None) -> str | None:
    value = re.sub(r"\D", "", value or "")
    if not value:
        return None
    if len(value) != 10:
        raise ValueError("Selecione uma conta Google Ads válida.")
    return value


def update_tenant_integrations(
    tenant_id: int,
    *,
    meta_ad_account_id: str | None,
    google_ads_customer_id: str | None,
) -> dict:
    meta_ad_account_id = _clean_meta_account_id(meta_ad_account_id)
    google_ads_customer_id = _clean_google_customer_id(google_ads_customer_id)
    try:
        with connection() as db:
            exists = db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            if not exists:
                raise ValueError("Cliente não encontrado.")
            db.execute(
                "UPDATE tenants SET meta_ad_account_id = ?, google_ads_customer_id = ? WHERE id = ?",
                (meta_ad_account_id, google_ads_customer_id, tenant_id),
            )
    except (sqlite3.IntegrityError, psycopg.IntegrityError) as exc:
        message = str(exc).lower()
        if "meta_ad_account_id" in message:
            raise ValueError("Esta conta Meta Ads já está vinculada a outro cliente.") from exc
        if "google_ads_customer_id" in message:
            raise ValueError("Esta conta Google Ads já está vinculada a outro cliente.") from exc
        raise ValueError("Não foi possível salvar as integrações deste cliente.") from exc
    return get_tenant(tenant_id)


def update_tenant_settings(
    tenant_id: int,
    *,
    name: str | None,
    primary_color: str | None,
    secondary_color: str | None,
    logo_data: str | None,
    status: str,
    meta_ad_account_id: str | None,
    google_ads_customer_id: str | None,
    slug: str | None = None,
    theme: dict | None = None,
) -> dict:
    """
    Salva identidade, acesso e integrações na mesma transação.

    `theme` ausente mantém o tema atual; presente, é validado inteiro (inclusive
    o contraste do texto) antes de qualquer gravação.
    """
    tenant_name = (name or "").strip()
    if len(tenant_name) < 2:
        raise ValueError("Informe o nome do cliente.")
    primary_color = _clean_color(primary_color, "#E5001A")
    secondary_color = _clean_color(secondary_color, "#0B0B0D")
    if status not in {"active", "inactive"}:
        raise ValueError("Status inválido.")
    meta_ad_account_id = _clean_meta_account_id(meta_ad_account_id)
    google_ads_customer_id = _clean_google_customer_id(google_ads_customer_id)
    # Slug em branco = "não mexer": o identificador é a URL do cliente e
    # trocá-lo por engano quebraria um link que já foi compartilhado.
    slug = _clean_slug(slug) if (slug or "").strip() else None
    theme_data = tenant_theme.dumps(tenant_theme.clean_theme(theme)) if theme is not None else None

    try:
        with connection() as db:
            exists = db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            if not exists:
                raise ValueError("Cliente não encontrado.")
            db.execute(
                """
                UPDATE tenants
                SET name = ?, primary_color = ?, secondary_color = ?, logo_data = ?, status = ?,
                    meta_ad_account_id = ?, google_ads_customer_id = ?,
                    slug = COALESCE(?, slug), theme_data = COALESCE(?, theme_data)
                WHERE id = ?
                """,
                (
                    tenant_name, primary_color, secondary_color, logo_data, status,
                    meta_ad_account_id, google_ads_customer_id, slug, theme_data, tenant_id,
                ),
            )
    except (sqlite3.IntegrityError, psycopg.IntegrityError) as exc:
        message = str(exc).lower()
        if "meta_ad_account_id" in message:
            raise ValueError("Esta conta Meta Ads já está vinculada a outro cliente.") from exc
        if "google_ads_customer_id" in message:
            raise ValueError("Esta conta Google Ads já está vinculada a outro cliente.") from exc
        if "slug" in message:
            raise ValueError("Este identificador já está em uso por outro cliente.") from exc
        raise ValueError("Não foi possível salvar este cliente.") from exc
    return get_tenant(tenant_id)


def update_tenant_appearance(
    tenant_id: int,
    *,
    primary_color: str | None,
    secondary_color: str | None,
    logo_data: str | None,
    theme: dict | None,
) -> dict:
    """
    Só a aparência: logo, cores da marca e tema.

    É o que o responsável do cliente pode mudar sozinho. Nome, endereço,
    contas de mídia e status continuam exclusivos do administrador — por isso
    esta função não recebe esses campos, em vez de confiar em quem chama.
    """
    primary_color = _clean_color(primary_color, "#E5001A")
    secondary_color = _clean_color(secondary_color, "#0B0B0D")
    theme_data = tenant_theme.dumps(tenant_theme.clean_theme(theme or {}))
    with connection() as db:
        exists = db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not exists:
            raise ValueError("Cliente não encontrado.")
        db.execute(
            "UPDATE tenants SET primary_color = ?, secondary_color = ?, logo_data = ?, theme_data = ? WHERE id = ?",
            (primary_color, secondary_color, logo_data, theme_data, tenant_id),
        )
    return get_tenant(tenant_id)


# --------------------------------------------------------------------------
# Acessos do cliente
# --------------------------------------------------------------------------

ROLE_LABELS = {
    "client_admin": "Responsável",
    "client": "Visualizador",
}


def list_tenant_users(tenant_id: int | None) -> list[dict]:
    """
    Quem acessa um cliente — o responsável primeiro, depois por nome.

    `role` e `active` são os DESTE cliente. `other_tenants` diz em quantos
    outros clientes a mesma pessoa entra (o admin precisa saber que remover o
    acesso aqui não tira a pessoa dos outros).
    """
    if not tenant_id:
        return []
    with connection() as db:
        rows = db.execute(
            """
            SELECT u.id, m.tenant_id, u.name, u.email, m.role,
                   CASE WHEN m.active = 1 AND u.active = 1 THEN 1 ELSE 0 END AS active,
                   m.created_at,
                   (SELECT COUNT(*) FROM tenant_members o
                    WHERE o.user_id = u.id AND o.tenant_id != m.tenant_id) AS other_tenants
            FROM tenant_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.tenant_id = ?
            ORDER BY CASE WHEN m.role = 'client_admin' THEN 0 ELSE 1 END, u.name
            """,
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _membership(db, user_id: int, tenant_id: int | None) -> dict:
    """
    O vínculo a alterar. Sem `tenant_id`, só vale se a pessoa tiver um cliente
    só — com vários, mexer "no acesso" sem dizer de qual cliente é ambíguo.
    """
    user = db.execute("SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise ValueError("Acesso não encontrado.")
    if user["role"] == "superadmin":
        raise ValueError("A conta da agência não é alterada por aqui.")
    if tenant_id is None:
        rows = db.execute("SELECT tenant_id FROM tenant_members WHERE user_id = ?", (user_id,)).fetchall()
        if len(rows) != 1:
            raise ValueError("Informe de qual cliente é o acesso.")
        tenant_id = rows[0]["tenant_id"]
    member = db.execute(
        "SELECT user_id, tenant_id, role, active FROM tenant_members WHERE user_id = ? AND tenant_id = ?",
        (user_id, tenant_id),
    ).fetchone()
    if not member:
        raise ValueError("Esta pessoa não tem acesso a este cliente.")
    return {**dict(member), "name": user["name"], "email": user["email"]}


def _other_owners(db, tenant_id: int, user_id: int, *, active_only: bool = False) -> int:
    """Responsáveis do cliente além desta pessoa — o cliente nunca pode ficar sem nenhum."""
    query = ("SELECT COUNT(*) AS total FROM tenant_members "
             "WHERE tenant_id = ? AND role = 'client_admin' AND user_id != ?")
    if active_only:
        query += " AND active = 1"
    return db.execute(query, (tenant_id, user_id)).fetchone()["total"]


def _clean_role(role: str | None) -> str:
    role = (role or "client").strip()
    if role not in ROLE_LABELS:
        raise ValueError("Perfil de acesso inválido.")
    return role


def _clean_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Informe um e-mail válido.")
    return email


def update_user(
    user_id: int,
    *,
    name: str | None,
    email: str | None,
    role: str | None,
    tenant_id: int | None = None,
) -> dict:
    """
    Edita um acesso. Nome e e-mail são da PESSOA (valem em todos os clientes
    dela); o papel é deste cliente. Trocar o e-mail muda o login dela.
    """
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Informe o nome da pessoa.")
    email = _clean_email(email)
    role = _clean_role(role)

    with connection() as db:
        member = _membership(db, user_id, tenant_id)
        # Todo cliente precisa manter pelo menos um responsável, senão
        # ninguém consegue administrar os acessos daquele ambiente.
        if member["role"] == "client_admin" and role != "client_admin":
            if not _other_owners(db, member["tenant_id"], user_id):
                raise ValueError("O cliente precisa de pelo menos um responsável.")
        try:
            db.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", (name, email, user_id))
        except (sqlite3.IntegrityError, psycopg.IntegrityError) as exc:
            raise ValueError("Este e-mail já possui uma conta.") from exc
        db.execute(
            "UPDATE tenant_members SET role = ? WHERE user_id = ? AND tenant_id = ?",
            (role, user_id, member["tenant_id"]),
        )

    return get_user(user_id, member["tenant_id"])


def set_user_password(user_id: int, password: str | None) -> None:
    if len(password or "") < 8:
        raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
    with connection() as db:
        found = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not found:
            raise ValueError("Acesso não encontrado.")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )


def delete_user(user_id: int, tenant_id: int | None = None) -> dict:
    """
    Tira o acesso da pessoa a um cliente.

    Se era o único cliente dela, a conta inteira some (sem cliente, o login
    não abriria nada). Se ela acessa outros, só este vínculo sai — a pessoa
    continua entrando nos demais com a mesma senha. O último responsável do
    cliente continua protegido.
    """
    with connection() as db:
        member = _membership(db, user_id, tenant_id)
        if member["role"] == "client_admin" and not _other_owners(db, member["tenant_id"], user_id):
            raise ValueError(
                "Este é o único responsável do cliente. Promova outra pessoa antes de excluir."
            )
        db.execute(
            "DELETE FROM tenant_members WHERE user_id = ? AND tenant_id = ?", (user_id, member["tenant_id"])
        )
        remaining = db.execute(
            "SELECT COUNT(*) AS total FROM tenant_members WHERE user_id = ?", (user_id,)
        ).fetchone()["total"]
        if not remaining:
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {**member, "id": user_id, "account_deleted": not remaining}


def delete_tenant(tenant_id: int) -> dict:
    """
    Remove o cliente e tudo que depende dele.

    Apaga vínculos, convites e as métricas já sincronizadas. Quem só acessava
    este cliente perde a conta junto; quem acessa outros continua entrando
    neles. As linhas de mídia são apagadas explicitamente para o comportamento
    ser o mesmo no SQLite e no Postgres, sem depender de ON DELETE CASCADE.
    """
    with connection() as db:
        tenant = db.execute(
            "SELECT id, name, slug FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        if not tenant:
            raise ValueError("Cliente não encontrado.")

        members = [row["user_id"] for row in db.execute(
            "SELECT user_id FROM tenant_members WHERE tenant_id = ?", (tenant_id,)
        ).fetchall()]
        for table in ("media_daily_metrics", "media_sync_state", "media_sync_windows", "media_period_reach"):
            db.execute(f"DELETE FROM {table} WHERE tenant_id = ?", (tenant_id,))
        db.execute("DELETE FROM user_invites WHERE tenant_id = ?", (tenant_id,))
        db.execute("DELETE FROM tenant_members WHERE tenant_id = ?", (tenant_id,))
        for user_id in members:
            left = db.execute(
                "SELECT COUNT(*) AS total FROM tenant_members WHERE user_id = ?", (user_id,)
            ).fetchone()["total"]
            if not left:
                db.execute("DELETE FROM users WHERE id = ? AND role != 'superadmin'", (user_id,))
        db.execute("UPDATE users SET last_tenant_id = NULL WHERE last_tenant_id = ?", (tenant_id,))
        db.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))

    return dict(tenant)


def set_user_active(user_id: int, active: bool, tenant_id: int | None = None) -> None:
    """Suspende ou reativa o acesso a UM cliente; os outros clientes da pessoa seguem iguais."""
    with connection() as db:
        member = _membership(db, user_id, tenant_id)
        if not active and member["role"] == "client_admin":
            if not _other_owners(db, member["tenant_id"], user_id, active_only=True):
                raise ValueError("O cliente ficaria sem nenhum responsável ativo.")
        db.execute(
            "UPDATE tenant_members SET active = ? WHERE user_id = ? AND tenant_id = ?",
            (1 if active else 0, user_id, member["tenant_id"]),
        )


# --------------------------------------------------------------------------
# Convites
# --------------------------------------------------------------------------

INVITE_TTL_DAYS = 7


def create_invite(
    tenant_id: int,
    *,
    name: str | None,
    email: str | None,
    role: str | None = "client",
    invited_by: int | None = None,
) -> dict:
    """
    Cria um convite e devolve o token.

    O convidado define a própria senha ao aceitar — o administrador nunca
    precisa inventar e transmitir uma senha, que é o jeito de senha
    provisória vazar por WhatsApp e nunca ser trocada.
    """
    import secrets

    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Informe o nome da pessoa convidada.")
    email = _clean_email(email)
    role = _clean_role(role)

    with connection() as db:
        tenant = db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not tenant:
            raise ValueError("Cliente não encontrado.")
        # E-mail com conta em OUTRO cliente pode ser convidado: ao aceitar, este
        # cliente se soma aos dela, com a mesma senha. Só não faz sentido
        # convidar quem já entra neste.
        taken = db.execute("SELECT id, role FROM users WHERE email = ?", (email,)).fetchone()
        if taken and taken["role"] == "superadmin":
            raise ValueError("Este e-mail é da conta da agência.")
        if taken and db.execute(
            "SELECT 1 FROM tenant_members WHERE user_id = ? AND tenant_id = ?", (taken["id"], tenant_id)
        ).fetchone():
            raise ValueError("Esta pessoa já tem acesso a este cliente.")

        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS)
        # Um convite pendente por e-mail e cliente: reenviar substitui o anterior.
        db.execute(
            "DELETE FROM user_invites WHERE email = ? AND tenant_id = ? AND accepted_at IS NULL",
            (email, tenant_id),
        )
        db.execute(
            "INSERT INTO user_invites "
            "(token, tenant_id, email, name, role, invited_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token, tenant_id, email, name, role, invited_by, _now(),
             expires.isoformat(timespec="seconds")),
        )

    return {"token": token, "email": email, "name": name, "role": role}


def get_invite(token: str | None) -> dict | None:
    token = (token or "").strip()
    if not token:
        return None
    with connection() as db:
        row = db.execute(
            """
            SELECT i.*, t.name AS tenant_name, t.slug AS tenant_slug, t.logo_data,
                   t.primary_color, t.secondary_color, t.theme_data, t.status AS tenant_status
            FROM user_invites i
            JOIN tenants t ON t.id = i.tenant_id
            WHERE i.token = ?
            """,
            (token,),
        ).fetchone()
    if not row:
        return None
    invite = dict(row)
    # Quem já tem conta aceita com a senha que já usa (o convite soma um
    # cliente); quem não tem cria a senha agora.
    invite["has_account"] = _user_by_email(invite["email"]) is not None
    if invite["accepted_at"]:
        return {**invite, "state": "accepted"}
    if invite["expires_at"] < _now():
        return {**invite, "state": "expired"}
    if invite["tenant_status"] != "active":
        return {**invite, "state": "inactive"}
    return {**invite, "state": "pending"}


def accept_invite(token: str | None, *, password: str | None, name: str | None = None) -> dict:
    """
    Converte o convite em acesso real. Idempotente por token.

    Duas situações:

    * **E-mail sem conta** — cria a pessoa com a senha escolhida agora.
    * **E-mail que já tem conta** (em outro cliente) — confere a senha ATUAL
      dela e soma este cliente aos que ela já acessa. Sem essa conferência,
      quem recebesse o link de outra pessoa ganharia acesso à conta dela.
    """
    invite = get_invite(token)
    if not invite:
        raise ValueError("Convite não encontrado.")
    if invite["state"] == "accepted":
        raise ValueError("Este convite já foi utilizado.")
    if invite["state"] == "expired":
        raise ValueError("Este convite expirou. Peça um novo ao administrador.")
    if invite["state"] == "inactive":
        raise ValueError("O acesso deste cliente está suspenso.")

    with connection() as db:
        existing = db.execute(
            "SELECT id, role, password_hash FROM users WHERE email = ?", (invite["email"],)
        ).fetchone()
        if existing:
            if existing["role"] == "superadmin":
                raise ValueError("Este e-mail é da conta da agência.")
            if not check_password_hash(existing["password_hash"], password or ""):
                raise ValueError("Senha incorreta. Use a senha com que você já entra no painel.")
            user_id = existing["id"]
        else:
            if len(password or "") < 8:
                raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
            final_name = (name or "").strip() or invite["name"]
            user_id = _insert_user(db, final_name, invite["email"], password)
        _add_membership(db, user_id, invite["tenant_id"], invite["role"])
        db.execute("UPDATE users SET last_tenant_id = ? WHERE id = ?", (invite["tenant_id"], user_id))
        db.execute("UPDATE user_invites SET accepted_at = ? WHERE token = ?", (_now(), token))

    return get_user(user_id, invite["tenant_id"])


def list_pending_invites(tenant_id: int | None) -> list[dict]:
    if not tenant_id:
        return []
    with connection() as db:
        rows = db.execute(
            "SELECT token, name, email, role, created_at, expires_at FROM user_invites "
            "WHERE tenant_id = ? AND accepted_at IS NULL ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
    now = _now()
    return [{**dict(row), "expired": row["expires_at"] < now} for row in rows]


def revoke_invite(token: str | None) -> None:
    with connection() as db:
        db.execute("DELETE FROM user_invites WHERE token = ? AND accepted_at IS NULL", (token,))
