"""Dataset multi-tenant alimentado pelas APIs oficiais de mídia paga."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
import threading
import time

from core.auth import active_tenant
from core.integrations import google_ads, meta_ads
from core.mock import DEFAULT_PERIOD, METRIC_KEYS, METRIC_LABELS, PERIODS, STATUS_LABEL, get_period
from core.storage import (
    get_media_rows, get_media_sync_state, get_period_reach, get_tenant, media_data_bounds, set_period_reach,
)


_DATASET_LOCKS: dict[tuple, threading.Lock] = {}
_DATASET_LOCKS_GUARD = threading.Lock()


def _last_delivery(tenant_id: int | None, platform: str) -> str | None:
    """Data mais recente com dado gravado, em todo o histórico da conta."""
    if not tenant_id:
        return None
    try:
        bounds = media_data_bounds(tenant_id, platform)
    except Exception:
        # Informação de apoio: nunca pode derrubar a leitura do painel.
        return None
    return (bounds or {}).get("last_date")


METRICS = [
    ("investimento", "Investimento", "wallet", "currency", "neutral"),
    ("cpa", "CPA", "target", "currency_cents", "down"),
    ("cpl", "CPL", "user-plus", "currency_cents", "down"),
    ("leads", "Leads", "magnet", "int", "up"),
    ("ctr", "CTR", "mouse-pointer-click", "percent", "up"),
    ("cpm", "CPM", "layers", "currency_cents", "down"),
    ("cpc", "CPC", "pointer", "currency_cents", "down"),
    ("impressoes", "Impressões", "eye", "compact", "up"),
    ("alcance", "Alcance", "radar", "compact", "up"),
    ("cliques", "Cliques", "mouse-pointer-2", "compact", "up"),
    ("sessoes", "Sessões", "globe", "compact", "up"),
]

LEAD_ACTIONS = (
    "lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead",
    "omni_lead", "onsite_web_lead",
)
PURCHASE_ACTIONS = (
    "offsite_conversion.fb_pixel_purchase", "omni_purchase", "purchase",
)


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _variation(current: float, previous: float) -> float:
    return ((current - previous) / previous * 100) if previous else 0.0


def _metric(key, label, icon, kind, good, value, previous=0.0, spark=None) -> dict:
    return {
        "key": key, "label": label, "icon": icon, "type": kind, "good": good,
        "value": value, "previous": previous, "variation": _variation(value, previous),
        "spark": spark or [],
    }


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _blank_row(day: str) -> dict:
    return {
        "date": day, "investimento": 0.0, "receita": 0.0, "impressoes": 0,
        "cliques": 0, "leads": 0.0, "conversoes": 0.0, "alcance": 0,
        "cpl": 0.0, "cpc": 0.0, "ctr": 0.0, "cpm": 0.0, "receita_acumulada": 0.0,
    }


def _blank_series(start: date, end: date) -> list[dict]:
    return [_blank_row(day.isoformat()) for day in _dates(start, end)]


def _finalize_series(rows: list[dict]) -> list[dict]:
    """
    Deriva as métricas por dia.

    `receita` continua sendo ingerida da plataforma e somada aqui, mas não é
    exposta em lugar nenhum da interface — o acumulado sobrevive só como base
    de comparação interna.
    """
    running = 0.0
    for row in rows:
        running += row["receita"]
        row["cpl"] = _safe_div(row["investimento"], row["leads"])
        row["cpc"] = _safe_div(row["investimento"], row["cliques"])
        row["ctr"] = _safe_div(row["cliques"], row["impressoes"]) * 100
        row["cpm"] = _safe_div(row["investimento"], row["impressoes"]) * 1000
        row["receita_acumulada"] = running
    return rows


def _totals(series: list[dict]) -> dict:
    total = {
        key: sum(_number(row.get(key)) for row in series)
        for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance")
    }
    total.update(
        {
            "cpa": _safe_div(total["investimento"], total["conversoes"]),
            "cpl": _safe_div(total["investimento"], total["leads"]),
            "ctr": _safe_div(total["cliques"], total["impressoes"]) * 100,
            "cpm": _safe_div(total["investimento"], total["impressoes"]) * 1000,
            "cpc": _safe_div(total["investimento"], total["cliques"]),
            "sessoes": round(total["cliques"] * 0.94),
            "frequencia": _safe_div(total["impressoes"], total["alcance"]),
        }
    )
    return total


def _kpis(current: dict, previous: dict, series: list[dict]) -> list[dict]:
    result = []
    for key, label, icon, kind, good in METRICS:
        spark_key = key if key in series[0] else "investimento"
        if key == "alcance":
            # Não existe alcance por dia; a curva de impressões dá o formato.
            spark_key = "impressoes"
        step = max(1, len(series) // 12)
        result.append(
            _metric(
                key, label, icon, kind, good, current.get(key, 0), previous.get(key, 0),
                [row.get(spark_key, 0) for row in series[::step]][-12:],
            )
        )
    return result


def _first_action(row: dict, field: str, types: tuple[str, ...]) -> float:
    values = {item.get("action_type"): _number(item.get("value")) for item in row.get(field, [])}
    for action_type in types:
        if action_type in values:
            return values[action_type]
    return 0.0


def _status(value: str | None) -> str:
    value = (value or "").upper()
    if value == "ENABLED" or value == "ACTIVE":
        return "active"
    if value == "PAUSED":
        return "paused"
    return "ended"


def _meta_values(row: dict) -> dict:
    spend = _number(row.get("spend"))
    impressions = int(_number(row.get("impressions")))
    clicks = int(_number(row.get("clicks")))
    leads = _first_action(row, "actions", LEAD_ACTIONS)
    conversions = _first_action(row, "actions", PURCHASE_ACTIONS) or leads
    revenue = _first_action(row, "action_values", PURCHASE_ACTIONS)
    reach = int(_number(row.get("reach")))
    return {
        "investimento": spend, "receita": revenue, "impressoes": impressions,
        "cliques": clicks, "leads": leads, "conversoes": conversions, "alcance": reach,
        "ctr": _number(row.get("ctr"), _safe_div(clicks, impressions) * 100),
        "cpc": _number(row.get("cpc"), _safe_div(spend, clicks)),
        "cpm": _number(row.get("cpm"), _safe_div(spend, impressions) * 1000),
        "cpl": _safe_div(spend, leads),
    }


def _meta_entity_rows(
    rows: list[dict],
    level: str,
    statuses: dict[str, str],
    creatives: dict[str, dict] | None = None,
) -> list[dict]:
    name_key = {"campaign": "campaign_name", "adset": "adset_name", "ad": "ad_name"}[level]
    id_key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level]
    result = []
    for row in rows:
        values = _meta_values(row)
        entity_id = str(row.get(id_key) or "")
        creative = (creatives or {}).get(entity_id, {}) if level == "ad" else {}
        result.append(
            {
                "id": entity_id,
                "nome": row.get(name_key) or "Sem nome",
                "status": _status(statuses.get(entity_id) or creative.get("status") or "ACTIVE"), "canal": "meta",
                "campaign_id": str(row.get("campaign_id") or ""),
                "adset_id": str(row.get("adset_id") or ""),
                "campanha": row.get("campaign_name"),
                "conjunto": row.get("adset_name"),
                "creative_url": creative.get("url"),
                "creative_quality": creative.get("quality"),
                **values,
            }
        )
    return result


def _rollup_meta_ads(ads: list[dict], level: str) -> list[dict]:
    """Agrupa os anuncios localmente para poupar chamadas na API da Meta."""
    key_name = "campaign_id" if level == "campaign" else "adset_id"
    grouped: dict[str, dict] = {}
    for ad in ads:
        fallback_name = ad.get("campanha") if level == "campaign" else ad.get("conjunto")
        entity_id = str(ad.get(key_name) or fallback_name or ad.get("id") or "")
        if not entity_id:
            continue
        name = fallback_name
        current = grouped.setdefault(
            entity_id,
            {
                "id": entity_id,
                "nome": name or ad.get("nome") or "Sem nome",
                "status": ad.get("status") or "active",
                "canal": "meta",
                "campanha": ad.get("campanha"),
                "conjunto": ad.get("conjunto") if level == "adset" else None,
                "investimento": 0.0,
                "receita": 0.0,
                "impressoes": 0,
                "cliques": 0,
                "leads": 0.0,
                "conversoes": 0.0,
                "alcance": 0,
            },
        )
        for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance"):
            current[key] += _number(ad.get(key))
        if ad.get("status") == "active":
            current["status"] = "active"

    for current in grouped.values():
        current.update(
            {
                "ctr": _safe_div(current["cliques"], current["impressoes"]) * 100,
                "cpc": _safe_div(current["investimento"], current["cliques"]),
                "cpm": _safe_div(current["investimento"], current["impressoes"]) * 1000,
                "cpl": _safe_div(current["investimento"], current["leads"]),
            }
        )
    return sorted(grouped.values(), key=lambda row: row["investimento"], reverse=True)


def _series_from_storage(rows: list[dict], start: date, end: date) -> list[dict]:
    series = _blank_series(start, end)
    by_date = {row["date"]: row for row in series}
    for source in rows:
        if source.get("level") != "account":
            continue
        target = by_date.get(source.get("metric_date"))
        if not target:
            continue
        for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance"):
            target[key] = _number(source.get(key))
    return _finalize_series(series)


def _stored_entities(rows: list[dict], level: str, channel: str) -> list[dict]:
    grouped: dict[str, dict] = {}
    for source in rows:
        if source.get("level") != level:
            continue
        entity_id = str(source.get("entity_id") or "")
        if not entity_id:
            continue
        current = grouped.setdefault(
            entity_id,
            {
                "id": entity_id,
                "nome": source.get("name") or "Sem nome",
                "status": source.get("status") or "active",
                "canal": channel,
                "campaign_id": str(source.get("campaign_id") or ""),
                "adset_id": str(source.get("parent_id") or "") if channel == "meta" else "",
                "campanha": source.get("campaign_name"),
                "conjunto": source.get("parent_name"),
                "creative_url": source.get("creative_url"),
                "creative_quality": source.get("creative_quality"),
                "correspondencia": (source.get("match_type") or "").replace("_", " ").title(),
                "qs": _number(source.get("quality_score")),
                "posicao": 0.0,
                "investimento": 0.0,
                "receita": 0.0,
                "impressoes": 0,
                "cliques": 0,
                "leads": 0.0,
                "conversoes": 0.0,
                "alcance": 0,
                "_is_weight": 0.0,
                "_top_weight": 0.0,
                "_share_impressions": 0.0,
            },
        )
        for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance"):
            current[key] += _number(source.get(key))
        impressions = _number(source.get("impressoes"))
        if source.get("impression_share") is not None:
            current["_is_weight"] += _number(source.get("impression_share")) * impressions
            current["_top_weight"] += _number(source.get("top_impression_share")) * impressions
            current["_share_impressions"] += impressions
        if source.get("metric_date", "") >= current.get("_latest", ""):
            current["_latest"] = source.get("metric_date")
            current["status"] = source.get("status") or current["status"]
            current["creative_url"] = source.get("creative_url") or current.get("creative_url")
            current["creative_quality"] = source.get("creative_quality") or current.get("creative_quality")
            if source.get("quality_score") is not None:
                current["qs"] = _number(source.get("quality_score"))

    for current in grouped.values():
        current.update(
            {
                "ctr": _safe_div(current["cliques"], current["impressoes"]) * 100,
                "cpc": _safe_div(current["investimento"], current["cliques"]),
                "cpm": _safe_div(current["investimento"], current["impressoes"]) * 1000,
                "cpl": _safe_div(current["investimento"], current["leads"]),
                "impression_share": _safe_div(current["_is_weight"], current["_share_impressions"]),
                "top_impression_share": _safe_div(current["_top_weight"], current["_share_impressions"]),
            }
        )
        for key in ("_is_weight", "_top_weight", "_share_impressions", "_latest"):
            current.pop(key, None)
    return sorted(grouped.values(), key=lambda row: row["investimento"], reverse=True)


def _stored_connection(sync: dict | None, has_rows: bool) -> dict:
    if not sync:
        return {
            "status": "syncing" if not has_rows else "connected",
            "message": "Aguardando a primeira sincronizacao." if not has_rows else "Dados salvos no banco.",
        }
    if sync.get("status") == "success":
        return {
            "status": "connected",
            "message": "Dados carregados do banco.",
            "synced_at": sync.get("finished_at"),
        }
    if sync.get("status") == "running":
        return {
            "status": "stale" if has_rows else "syncing",
            "message": "Sincronizacao em andamento. Exibindo os dados ja salvos." if has_rows else "Primeira sincronizacao em andamento.",
            "synced_at": sync.get("finished_at"),
        }
    return {
        "status": "stale" if has_rows else "error",
        "message": "A ultima sincronizacao falhou; os dados anteriores foram preservados." if has_rows else (sync.get("error_message") or "Falha na sincronizacao."),
        "error_detail": sync.get("error_message"),
        "request_id": sync.get("request_id"),
        "synced_at": sync.get("finished_at"),
    }


def _load_meta(
    account_id: str | None,
    start: date,
    end: date,
    previous_start: date,
    previous_end: date,
    tenant_id: int | None = None,
) -> dict:
    result = {
        "status": "unconfigured", "message": "Conta Meta Ads não vinculada.",
        "series": _blank_series(start, end), "previous": _blank_series(previous_start, previous_end),
        "campaigns": [], "adsets": [], "ads": [],
    }
    if not account_id:
        return result
    if not tenant_id:
        result.update({"status": "error", "message": "Tenant nao informado para leitura do banco."})
        return result
    rows = get_media_rows(tenant_id, "meta", previous_start.isoformat(), end.isoformat())
    current_rows = [row for row in rows if start.isoformat() <= row["metric_date"] <= end.isoformat()]
    previous_rows = [row for row in rows if previous_start.isoformat() <= row["metric_date"] <= previous_end.isoformat()]
    ads = _stored_entities(current_rows, "ad", "meta")
    connection = _stored_connection(get_media_sync_state(tenant_id, "meta"), bool(rows))
    result.update(
        {
            **connection,
            "series": _series_from_storage(current_rows, start, end),
            "previous": _series_from_storage(previous_rows, previous_start, previous_end),
            "campaigns": _rollup_meta_ads(ads, "campaign"),
            "adsets": _rollup_meta_ads(ads, "adset"),
            "ads": ads,
        }
    )
    return result


def _google_values(metrics: dict) -> dict:
    spend = _number(metrics.get("costMicros")) / 1_000_000
    impressions = int(_number(metrics.get("impressions")))
    clicks = int(_number(metrics.get("clicks")))
    conversions = _number(metrics.get("conversions"))
    revenue = _number(metrics.get("conversionsValue"))
    return {
        "investimento": spend, "receita": revenue, "impressoes": impressions,
        "cliques": clicks, "leads": conversions, "conversoes": conversions, "alcance": 0,
        "ctr": _number(metrics.get("ctr"), _safe_div(clicks, impressions)) * (100 if _number(metrics.get("ctr")) <= 1 else 1),
        "cpc": _number(metrics.get("averageCpc")) / 1_000_000 if metrics.get("averageCpc") is not None else _safe_div(spend, clicks),
        "cpm": _safe_div(spend, impressions) * 1000,
        "cpl": _safe_div(spend, conversions),
    }


def _aggregate_google(rows: list[dict], entity: str, name: str, status: str, *, extra=None) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        node = row.get(entity, {})
        entity_id = str(node.get("id") or node.get("resourceName") or node.get(name) or "")
        if not entity_id:
            continue
        values = _google_values(row.get("metrics", {}))
        current = grouped.setdefault(
            entity_id,
            {
                "nome": node.get(name) or f"Item {entity_id}", "status": _status(node.get(status)),
                "canal": "google", "investimento": 0.0, "receita": 0.0, "impressoes": 0,
                "cliques": 0, "leads": 0.0, "conversoes": 0.0, "alcance": 0,
            },
        )
        for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes"):
            current[key] += values[key]
        if extra:
            current.update(extra(row))
    for current in grouped.values():
        current.update(
            {
                "ctr": _safe_div(current["cliques"], current["impressoes"]) * 100,
                "cpc": _safe_div(current["investimento"], current["cliques"]),
                "cpm": _safe_div(current["investimento"], current["impressoes"]) * 1000,
                "cpl": _safe_div(current["investimento"], current["leads"]),
            }
        )
    return [
        row for row in grouped.values()
        if row["investimento"] or row["impressoes"] or row["cliques"] or row["conversoes"]
    ]


def _google_query(customer_id: str, start: date, end: date, kind: str) -> list[dict]:
    window = f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"
    metrics = (
        "metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.ctr, "
        "metrics.average_cpc, metrics.conversions, metrics.conversions_value"
    )
    if kind == "account":
        # O total da conta vem da própria conta, não da soma das campanhas:
        # é o mesmo número do Gerenciador, com campanha removida ou não.
        return google_ads.search(customer_id, f"""
            SELECT segments.date, {metrics} FROM customer WHERE {window}
        """)
    if kind == "campaign":
        # Campanha removida que gastou no período continua na tabela — sem
        # ela as linhas não fechavam com o total da conta.
        return google_ads.search(customer_id, f"""
            SELECT segments.date, campaign.id, campaign.name, campaign.status, {metrics},
                   metrics.search_impression_share, metrics.search_top_impression_share
            FROM campaign WHERE {window}
        """)
    if kind == "group":
        return google_ads.search(customer_id, f"""
            SELECT segments.date, campaign.id, campaign.name,
                   ad_group.id, ad_group.name, ad_group.status, {metrics}
            FROM ad_group WHERE {window} AND ad_group.status != 'REMOVED'
        """)
    if kind == "keyword":
        return google_ads.search(customer_id, f"""
            SELECT segments.date, campaign.id, campaign.name, ad_group.id, ad_group.name,
                   ad_group_criterion.criterion_id, ad_group_criterion.keyword.text,
                   ad_group_criterion.keyword.match_type, ad_group_criterion.status,
                   ad_group_criterion.quality_info.quality_score, {metrics}
            FROM keyword_view WHERE {window} AND ad_group_criterion.status != 'REMOVED'
        """)
    return google_ads.search(customer_id, f"""
        SELECT segments.date, campaign.id, campaign.name, ad_group.id, ad_group.name,
               ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, {metrics}
        FROM ad_group_ad WHERE {window} AND ad_group_ad.status != 'REMOVED'
    """)


def _google_keyword_extra(row: dict) -> dict:
    criterion = row.get("adGroupCriterion", {})
    quality = criterion.get("qualityInfo", {}).get("qualityScore")
    match = criterion.get("keyword", {}).get("matchType", "")
    return {
        "nome": criterion.get("keyword", {}).get("text") or "Palavra-chave",
        "qs": _number(quality), "posicao": 0.0,
        "correspondencia": match.replace("_", " ").title(),
    }


def _google_ad_extra(row: dict) -> dict:
    ad = row.get("adGroupAd", {}).get("ad", {})
    return {"nome": ad.get("name") or f"Anúncio {ad.get('id', '')}".strip()}


def _load_google(
    customer_id: str | None,
    start: date,
    end: date,
    previous_start: date,
    previous_end: date,
    tenant_id: int | None = None,
) -> dict:
    result = {
        "status": "unconfigured", "message": "Conta Google Ads não vinculada.",
        "series": _blank_series(start, end), "previous": _blank_series(previous_start, previous_end),
        "campaigns": [], "groups": [], "keywords": [], "ads": [], "auction": {},
    }
    if not customer_id:
        return result
    if not tenant_id:
        result.update({"status": "error", "message": "Tenant nao informado para leitura do banco."})
        return result
    rows = get_media_rows(tenant_id, "google", previous_start.isoformat(), end.isoformat())
    current_rows = [row for row in rows if start.isoformat() <= row["metric_date"] <= end.isoformat()]
    previous_rows = [row for row in rows if previous_start.isoformat() <= row["metric_date"] <= previous_end.isoformat()]
    campaigns = _stored_entities(current_rows, "campaign", "google")
    weighted_denominator = sum(row.get("impressoes", 0) for row in campaigns if row.get("impression_share"))
    auction = {
        "is": _safe_div(
            sum(row.get("impression_share", 0) * row.get("impressoes", 0) for row in campaigns),
            weighted_denominator,
        ) * 100,
        "top_is": _safe_div(
            sum(row.get("top_impression_share", 0) * row.get("impressoes", 0) for row in campaigns),
            weighted_denominator,
        ) * 100,
    }
    result.update(
        {
            **_stored_connection(get_media_sync_state(tenant_id, "google"), bool(rows)),
            "series": _series_from_storage(current_rows, start, end),
            "previous": _series_from_storage(previous_rows, previous_start, previous_end),
            "campaigns": campaigns,
            "groups": _stored_entities(current_rows, "group", "google"),
            "keywords": _stored_entities(current_rows, "keyword", "google"),
            "ads": _stored_entities(current_rows, "ad", "google"),
            "auction": auction,
        }
    )
    return result


REACH_TTL_SECONDS = 60 * 60


def _reach_is_fresh(fetched_at: str | None, end: date) -> bool:
    """Período fechado há dias não muda mais; o recente é revalidado a cada hora."""
    if end < date.today() - timedelta(days=3):
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except (TypeError, ValueError):
        return False
    return (datetime.now(UTC) - fetched).total_seconds() < REACH_TTL_SECONDS


def _meta_period_reach(tenant_id: int | None, account_id: str | None, start: date, end: date) -> float | None:
    """
    Alcance da Meta no período, como o Gerenciador mostra.

    Não dá para tirar das linhas diárias: a Meta não devolve mais `reach` por
    dia, e mesmo quando devolvia, somar dias contava a mesma pessoa várias
    vezes. É uma consulta agregada por período, guardada no banco para a
    tela não depender da API a cada abertura. Se a API falhar, vale o último
    valor salvo; sem nenhum, `None` (a tela mostra zero, não um palpite).
    """
    if not (tenant_id and account_id):
        return None
    key = (start.isoformat(), end.isoformat())
    try:
        cached = get_period_reach(tenant_id, "meta", account_id, *key)
    except Exception:
        cached = None
    if cached and _reach_is_fresh(cached.get("fetched_at"), end):
        return float(cached["reach"])
    try:
        reach = meta_ads.window_totals(account_id, *key)["reach"]
        set_period_reach(tenant_id, "meta", account_id, *key, reach)
        return reach
    except Exception:
        return float(cached["reach"]) if cached else None


def _apply_reach(target: dict, reach: float | None, impressions: float) -> None:
    target["alcance"] = reach or 0
    target["frequencia"] = _safe_div(impressions, reach or 0)


def _merge_series(*series_sets: list[dict]) -> list[dict]:
    if not series_sets:
        return []
    merged = [_blank_row(row["date"]) for row in series_sets[0]]
    by_date = {row["date"]: row for row in merged}
    for series in series_sets:
        for row in series:
            target = by_date[row["date"]]
            for key in ("investimento", "receita", "impressoes", "cliques", "leads", "conversoes", "alcance"):
                target[key] += _number(row.get(key))
    return _finalize_series(merged)


def _platform_metrics(platform: str, current: dict, previous: dict, series: list[dict], details: dict) -> list[dict]:
    definitions = [
        ("investimento", "Investimento", "wallet", "currency", "neutral"),
        ("impressoes", "Impressões", "eye", "compact", "up"),
        ("cliques", "Cliques", "mouse-pointer-2", "compact", "up"),
        ("ctr", "CTR", "mouse-pointer-click", "percent", "up"),
        ("cpc", "CPC médio", "pointer", "currency_cents", "down"),
        ("cpl", "CPL", "user-plus", "currency_cents", "down"),
        ("cpa", "CPA", "target", "currency_cents", "down"),
    ]
    if platform == "meta":
        definitions = [
            ("investimento", "Investimento", "wallet", "currency", "neutral"),
            ("cpm", "CPM", "layers", "currency_cents", "down"),
            ("ctr", "CTR", "mouse-pointer-click", "percent", "up"),
            ("cpc", "CPC", "pointer", "currency_cents", "down"),
            ("cliques", "Cliques", "mouse-pointer-2", "compact", "up"),
            ("alcance", "Alcance", "radar", "compact", "up"),
            ("impressoes", "Impressões", "eye", "compact", "up"),
            ("frequencia", "Frequência", "repeat", "decimal", "down"),
            ("leads", "Resultados", "flag", "int", "up"),
            ("cpl", "CPL", "user-plus", "currency_cents", "down"),
            ("cpa", "CPA", "target", "currency_cents", "down"),
        ]
    metrics = [
        _metric(key, label, icon, kind, good, current.get(key, 0), previous.get(key, 0))
        for key, label, icon, kind, good in definitions
    ]
    if platform == "google":
        auction = details.get("auction", {})
        quality_rows = [row for row in details.get("keywords", []) if row.get("qs")]
        qs = _safe_div(sum(row["qs"] * max(1, row.get("impressoes", 0)) for row in quality_rows),
                       sum(max(1, row.get("impressoes", 0)) for row in quality_rows))
        metrics.extend(
            [
                _metric("is", "Impression Share", "chart-pie", "percent", "up", auction.get("is", 0)),
                _metric("top_is", "Top Impression", "arrow-up-narrow-wide", "percent", "up", auction.get("top_is", 0)),
                _metric("search_is", "Search Imp. Share", "search", "percent", "up", auction.get("is", 0)),
                _metric("qs", "Quality Score médio", "gauge", "decimal", "up", qs),
            ]
        )
    return metrics


def _meta_highlights(campaigns: list[dict]) -> list[dict]:
    if not campaigns:
        return []
    with_leads = [row for row in campaigns if row.get("leads")]
    by_cpl = sorted(with_leads or campaigns, key=lambda row: row.get("cpl", 0))
    return [
        {"label": "Melhor campanha", "hint": "maior volume de leads", "item": max(campaigns, key=lambda row: row.get("leads", 0)),
         "metric": "leads", "type": "int", "tone": "positive", "icon": "trophy"},
        {"label": "Pior campanha", "hint": "lead mais caro do período", "item": by_cpl[-1],
         "metric": "cpl", "type": "currency_cents", "tone": "negative", "icon": "trending-down"},
        {"label": "Maior CTR", "hint": "melhor taxa de clique", "item": max(campaigns, key=lambda row: row.get("ctr", 0)),
         "metric": "ctr", "type": "percent", "tone": "neutral", "icon": "mouse-pointer-click"},
        {"label": "Menor CPL", "hint": "lead mais barato do período", "item": by_cpl[0],
         "metric": "cpl", "type": "currency_cents", "tone": "positive", "icon": "award"},
        {"label": "Maior gasto", "hint": "maior fatia do investimento", "item": max(campaigns, key=lambda row: row.get("investimento", 0)),
         "metric": "investimento", "type": "currency", "tone": "neutral", "icon": "wallet"},
    ]


@lru_cache(maxsize=256)
def _dataset_cached(
    period_id: str,
    tenant_id: int,
    meta_account: str | None,
    google_customer: str | None,
    today: str,
    _window: int = 0,
) -> dict:
    period = get_period(period_id)
    end = date.fromisoformat(today)
    if period.get("calendar") == "month":
        start = end.replace(day=1)
    elif period.get("calendar") == "year":
        start = end.replace(month=1, day=1)
    else:
        # Janela móvel fecha ontem, igual ao Gerenciador (ver PERIODS).
        if not period.get("include_today"):
            end -= timedelta(days=1)
        start = end - timedelta(days=period["days"] - 1)
    period["days"] = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period["days"] - 1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        meta_future = pool.submit(
            _load_meta, meta_account, start, end, previous_start, previous_end, tenant_id
        )
        google_future = pool.submit(
            _load_google, google_customer, start, end, previous_start, previous_end, tenant_id
        )
        reach_future = pool.submit(_meta_period_reach, tenant_id, meta_account, start, end)
        previous_reach_future = pool.submit(
            _meta_period_reach, tenant_id, meta_account, previous_start, previous_end
        )
        meta = meta_future.result()
        google = google_future.result()
        reach = reach_future.result()
        previous_reach = previous_reach_future.result()
    series = _merge_series(meta["series"], google["series"])
    previous_series = _merge_series(meta["previous"], google["previous"])
    totals = _totals(series)
    previous = _totals(previous_series)
    meta_totals, meta_previous = _totals(meta["series"]), _totals(meta["previous"])
    google_totals, google_previous = _totals(google["series"]), _totals(google["previous"])
    # Alcance é só da Meta (o Google não informa) e vem do período inteiro.
    # A frequência é sempre impressões da Meta sobre o alcance da Meta.
    for target, value, impressions in (
        (totals, reach, meta_totals["impressoes"]),
        (meta_totals, reach, meta_totals["impressoes"]),
        (previous, previous_reach, meta_previous["impressoes"]),
        (meta_previous, previous_reach, meta_previous["impressoes"]),
    ):
        _apply_reach(target, value, impressions)
    campaigns = meta["campaigns"] + google["campaigns"]
    channels = [
        {"key": "meta", "nome": "Meta Ads", "valor": meta_totals["investimento"]},
        {"key": "google", "nome": "Google Ads", "valor": google_totals["investimento"]},
    ]
    funnel = [
        {"etapa": "Impressões", "valor": totals["impressoes"], "taxa": 100.0, "do_topo": 100.0},
        {"etapa": "Cliques", "valor": totals["cliques"], "taxa": _safe_div(totals["cliques"], totals["impressoes"]) * 100,
         "do_topo": _safe_div(totals["cliques"], totals["impressoes"]) * 100},
        {"etapa": "Leads", "valor": totals["leads"], "taxa": _safe_div(totals["leads"], totals["cliques"]) * 100,
         "do_topo": _safe_div(totals["leads"], totals["impressoes"]) * 100},
    ]
    return {
        "tenant_id": tenant_id, "period": period,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "series": series, "totals": totals, "previous": previous,
        "kpis": _kpis(totals, previous, series), "channels": channels, "funnel": funnel,
        "campaigns": campaigns,
        "connections": {
            "meta": {key: meta.get(key) for key in ("status", "message", "error_detail", "request_id", "synced_at") if meta.get(key)},
            "google": {key: google.get(key) for key in ("status", "message", "error_detail", "request_id", "synced_at") if google.get(key)},
        },
        # Última data com veiculação em TODO o histórico, não só no período.
        # É o que distingue "a campanha parou em junho" de "a integração
        # quebrou" quando a tela aparece vazia.
        "last_delivery": {
            "meta": _last_delivery(tenant_id, "meta"),
            "google": _last_delivery(tenant_id, "google"),
        },
        "meta": {
            "metrics": _platform_metrics("meta", meta_totals, meta_previous, meta["series"], meta),
            "campaigns": meta["campaigns"], "adsets": meta["adsets"], "ads": meta["ads"],
            "highlights": _meta_highlights(meta["campaigns"]), "series": meta["series"],
        },
        "google": {
            "metrics": _platform_metrics("google", google_totals, google_previous, google["series"], google),
            "campaigns": google["campaigns"], "groups": google["groups"],
            "keywords": google["keywords"], "ads": google["ads"], "series": google["series"],
        },
    }


# Validade do dataset em memória. Em produção o site e o sincronizador são
# processos (containers) separados, e o site roda com vários processos: o
# `clear_cache()` do sincronizador não alcança a memória do site. Sem prazo,
# o painel mostraria os números da primeira leitura indefinidamente.
DATASET_TTL_SECONDS = 60


def _dataset(period_id: str, tenant_id: int, meta_account: str | None, google_customer: str | None, today: str) -> dict:
    """Serializa misses iguais para callbacks simultaneas nao duplicarem APIs."""
    key = (period_id, tenant_id, meta_account, google_customer, today)
    with _DATASET_LOCKS_GUARD:
        lock = _DATASET_LOCKS.setdefault(key, threading.Lock())
    with lock:
        return _dataset_cached(*key, int(time.time() // DATASET_TTL_SECONDS))


def get_dataset(period_id: str = DEFAULT_PERIOD, tenant_id: int | None = None) -> dict:
    tenant = get_tenant(tenant_id) if tenant_id else active_tenant()
    if not tenant:
        # Sem tenant não há consulta externa nem dado de outro cliente.
        return _dataset(period_id, 0, None, None, date.today().isoformat())
    return _dataset(
        period_id, tenant["id"], tenant.get("meta_ad_account_id"),
        tenant.get("google_ads_customer_id"), date.today().isoformat(),
    )


def clear_cache() -> None:
    _dataset_cached.cache_clear()
