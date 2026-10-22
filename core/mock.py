"""
Camada de dados MOCK — 100% front-end, nenhuma chamada externa.

Tudo é determinístico (PRNG com semente fixa): o mesmo período devolve sempre
os mesmos números. Isso importa porque um dashboard que muda de valor a cada
render é impossível de revisar visualmente e impossível de printar.

Quando as APIs de Meta Ads e Google Ads entrarem, ESTE é o único arquivo a
trocar: as telas consomem apenas o dicionário devolvido por `get_dataset()`.
O formato de saída é o contrato.
"""

from __future__ import annotations

import random
import zlib
from datetime import date, timedelta
from functools import lru_cache

# Data de referência do dataset de demonstração.
REFERENCE_DATE = date(2026, 8, 6)


# --------------------------------------------------------------------------
# Períodos
# --------------------------------------------------------------------------

# "Últimos N dias" termina ONTEM, como no Gerenciador da Meta e no Google
# Ads. Incluir o dia corrente (ainda pela metade) deixava o total diferente do
# que o cliente via na plataforma para o mesmo rótulo.
PERIODS = [
    {"id": "today", "label": "Hoje", "days": 1, "include_today": True, "compare": "o dia anterior"},
    {"id": "yesterday", "label": "Ontem", "days": 1, "compare": "o dia anterior"},
    {"id": "7d", "label": "Últimos 7 dias", "days": 7, "compare": "os 7 dias anteriores"},
    {"id": "30d", "label": "Últimos 30 dias", "days": 30, "compare": "os 30 dias anteriores"},
    {"id": "month", "label": "Este mês", "calendar": "month", "compare": "o período anterior"},
    {"id": "90d", "label": "Últimos 90 dias", "days": 90, "compare": "os 90 dias anteriores"},
    {"id": "180d", "label": "Últimos 6 meses", "days": 180, "compare": "os 6 meses anteriores"},
    {"id": "year", "label": "Este ano", "calendar": "year", "compare": "o período anterior"},
]

DEFAULT_PERIOD = "30d"


def get_period(period_id: str) -> dict:
    for period in PERIODS:
        if period["id"] == period_id:
            resolved = dict(period)
            today = date.today()
            if period.get("calendar") == "month":
                resolved["days"] = today.day
            elif period.get("calendar") == "year":
                resolved["days"] = (today - today.replace(month=1, day=1)).days + 1
            return resolved
    return get_period(DEFAULT_PERIOD)


# --------------------------------------------------------------------------
# Série diária
# --------------------------------------------------------------------------

def _build_series(days: int, end: date, seed: int) -> list[dict]:
    """
    Série diária com sazonalidade semanal (fim de semana mais fraco) e uma
    tendência de alta suave — o formato que um e-commerce real desenha.
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    running_total = 0

    for offset in range(days - 1, -1, -1):
        day = end - timedelta(days=offset)
        weekend = 0.72 if day.weekday() >= 5 else 1.0
        trend = 1 + ((days - offset) / days) * 0.22
        noise = 0.86 + rng.random() * 0.30

        investimento = round(3850 * weekend * trend * noise)
        # multiplicador de retorno do dia — matemática interna para dar
        # dispersão realista à receita; não é exposto como métrica
        retorno = 3.4 + rng.random() * 1.9 + (trend - 1) * 1.4
        receita = round(investimento * retorno)
        impressoes = round(investimento * (44 + rng.random() * 12))
        cliques = round(impressoes * (0.0186 + rng.random() * 0.011))
        leads = round(cliques * (0.116 + rng.random() * 0.045))
        conversoes = round(leads * (0.235 + rng.random() * 0.09))

        running_total += receita

        rows.append(
            {
                "date": day.isoformat(),
                "investimento": investimento,
                "receita": receita,
                "impressoes": impressoes,
                "cliques": cliques,
                "leads": leads,
                "conversoes": conversoes,
                "cpl": investimento / leads,
                "cpc": investimento / cliques,
                "receita_acumulada": running_total,
            }
        )

    return rows


def _total(rows: list[dict], key: str) -> int:
    return sum(row[key] for row in rows)


def _aggregate(rows: list[dict]) -> dict:
    investimento = _total(rows, "investimento")
    receita = _total(rows, "receita")
    impressoes = _total(rows, "impressoes")
    cliques = _total(rows, "cliques")
    leads = _total(rows, "leads")
    conversoes = _total(rows, "conversoes")

    alcance = round(impressoes / 1.62)
    sessoes = round(cliques * 0.94)

    # `conversoes` continua sendo apurado porque é o denominador do CPA,
    # mas não é exibido em lugar nenhum da interface.
    return {
        "investimento": investimento,
        "receita": receita,
        "cpa": investimento / conversoes,
        "cpl": investimento / leads,
        "leads": leads,
        "conversoes": conversoes,
        "ctr": cliques / impressoes * 100,
        "cpm": investimento / impressoes * 1000,
        "cpc": investimento / cliques,
        "impressoes": impressoes,
        "alcance": alcance,
        "cliques": cliques,
        "sessoes": sessoes,
        "frequencia": impressoes / alcance,
    }


# --------------------------------------------------------------------------
# Definição das 20 métricas do painel principal
# --------------------------------------------------------------------------
# `good` diz se SUBIR é bom. É o que decide a cor da seta: um CPA que sobe
# 12% é uma seta vermelha, mesmo o número tendo "crescido".

METRICS = [
    ("investimento", "Investimento", "wallet", "currency", "neutral"),
    ("receita", "Receita", "circle-dollar-sign", "currency", "up"),
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

# Chaves de todas as métricas disponíveis, na ordem em que aparecem.
# O seletor de métricas da topbar trabalha em cima desta lista.
METRIC_KEYS = [key for key, *_ in METRICS]
METRIC_LABELS = {key: label for key, label, *_ in METRICS}


def _build_kpis(current: dict, previous: dict, rows: list[dict]) -> list[dict]:
    """Monta os KPIs com variação e a sparkline de 12 pontos do stat tile."""
    step = max(1, len(rows) // 12)
    kpis = []

    for key, label, icon, kind, good in METRICS:
        value = current[key]
        prior = previous[key]
        variation = ((value - prior) / prior * 100) if prior else 0.0

        # A sparkline mostra o comportamento da própria métrica quando ela
        # existe na série diária; caso contrário cai na receita, que é a
        # curva de referência do negócio.
        source_key = key if key in rows[0] else "receita"
        spark = [row[source_key] for row in rows[::step]][-12:]

        kpis.append(
            {
                "key": key,
                "label": label,
                "icon": icon,
                "type": kind,
                "good": good,
                "value": value,
                "previous": prior,
                "variation": variation,
                "spark": spark,
            }
        )

    return kpis


# --------------------------------------------------------------------------
# Tabelas
# --------------------------------------------------------------------------

CAMPAIGN_ROWS = [
    ("[MET] Conversão — Retargeting 30d", "meta", "active"),
    ("[GAD] Search — Marca (Exata)", "google", "active"),
    ("[MET] Aquisição — Lookalike 1% Compradores", "meta", "active"),
    ("[GAD] Performance Max — Catálogo Full", "google", "active"),
    ("[MET] Prospecção — Interesses Amplos", "meta", "active"),
    ("[GAD] Search — Concorrentes", "google", "paused"),
    ("[MET] Vídeo — Topo de Funil Q3", "meta", "active"),
    ("[GAD] Display — Remarketing Dinâmico", "google", "active"),
    ("[MET] Leads — Formulário Instantâneo", "meta", "active"),
    ("[GAD] Shopping — Best Sellers", "google", "active"),
    ("[MET] Escala — Advantage+ Compras", "meta", "active"),
    ("[GAD] YouTube — Demonstração do Produto", "google", "paused"),
    ("[MET] Reengajamento — Carrinho Abandonado", "meta", "active"),
    ("[GAD] Search — Genéricas Categoria", "google", "draft"),
]

ADSET_NAMES = [
    "LAL 1% — Compradores 180d",
    "Retargeting — Visitantes 14d",
    "Interesses — Fitness + Wellness",
    "Broad — 25-44 todos os gêneros",
    "Carrinho Abandonado — 7d",
    "Engajamento IG — 90d",
    "LAL 3% — Leads Qualificados",
    "Geo — Capitais Sudeste",
]

AD_NAMES = [
    "VD_01 — Depoimento cliente 15s",
    "IM_04 — Carrossel benefícios",
    "VD_07 — Unboxing vertical",
    "IM_02 — Prova social estático",
    "VD_11 — Antes e depois",
    "IM_09 — Oferta frete grátis",
    "VD_03 — Fundador explicando",
    "IM_06 — Comparativo concorrente",
    "VD_14 — UGC criador parceiro",
    "IM_12 — Selo de garantia",
]

GROUP_NAMES = [
    "Marca — Exata",
    "Marca — Frase",
    "Categoria — Genéricas",
    "Concorrente — Direto",
    "Long tail — Comparativos",
    "Localização — Cidade",
    "Dinâmico — Site",
    "Promocional — Cupom",
]

KEYWORD_ROWS = [
    ("[marca oficial]", "Exata", 9),
    ('"comprar marca online"', "Frase", 8),
    ("+plataforma +gestão +tráfego", "Ampla", 7),
    ("[marca concorrente]", "Exata", 5),
    ('"melhor software marketing"', "Frase", 7),
    ("+dashboard +campanhas", "Ampla", 6),
    ("[preço marca]", "Exata", 8),
    ('"marca cupom desconto"', "Frase", 9),
    ("+relatório +meta +ads", "Ampla", 6),
    ("[marca login]", "Exata", 10),
    ('"alternativa concorrente"', "Frase", 6),
    ("+agência +performance +digital", "Ampla", 5),
]

GOOGLE_AD_NAMES = [
    "RSA — Marca | Headline A/B",
    "RSA — Categoria | Benefício",
    "RSA — Concorrente | Comparativo",
    "RSA — Promoção | Cupom 15%",
    "Display — Banner 300x250",
    "Display — Responsivo catálogo",
    "YouTube — Bumper 6s",
    "YouTube — In-stream 30s",
]


def _split_budget(count: int, total: float, rng: random.Random) -> list[int]:
    """Reparte um total entre N linhas com pesos aleatórios porém estáveis."""
    weights = [0.4 + rng.random() for _ in range(count)]
    weight_sum = sum(weights)
    return [round(total * w / weight_sum) for w in weights]


def _row_metrics(investimento: int, rng: random.Random) -> dict:
    # O multiplicador de receita continua existindo como matemática interna
    # (é o que dá dispersão realista às linhas), mas não é exposto: ROAS saiu
    # do produto.
    receita = round(investimento * (1.5 + rng.random() * 4.6))
    impressoes = max(1, round(investimento * (38 + rng.random() * 22)))
    cliques = max(1, round(impressoes * (0.013 + rng.random() * 0.02)))
    conversoes = max(1, round(cliques * (0.02 + rng.random() * 0.05)))

    return {
        "investimento": investimento,
        "impressoes": impressoes,
        "cliques": cliques,
        "ctr": cliques / impressoes * 100,
        "cpc": investimento / cliques,
        "cpm": investimento / impressoes * 1000,
        "conversoes": conversoes,
        "cpa": investimento / conversoes,
        "receita": receita,
    }


def _build_campaigns(total_invest: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    budgets = _split_budget(len(CAMPAIGN_ROWS), total_invest, rng)
    rows = []

    for index, ((nome, canal, status), investimento) in enumerate(
        zip(CAMPAIGN_ROWS, budgets)
    ):
        metrics = _row_metrics(investimento, rng)
        leads = max(1, round(metrics["cliques"] * (0.09 + rng.random() * 0.07)))
        rows.append(
            {
                "id": f"c{index + 1}",
                "nome": nome,
                "canal": canal,
                "status": status,
                "leads": leads,
                "cpl": investimento / leads,
                **metrics,
            }
        )

    return rows


def _build_rows(names: list, total_invest: int, seed: int, extra=None) -> list[dict]:
    rng = random.Random(seed)
    budgets = _split_budget(len(names), total_invest, rng)
    rows = []

    for index, (entry, investimento) in enumerate(zip(names, budgets)):
        nome = entry[0] if isinstance(entry, tuple) else entry
        row = {
            "id": f"r{index + 1}",
            "nome": nome,
            "status": "paused" if index % 7 == 5 else "active",
            **_row_metrics(investimento, rng),
        }
        if extra is not None:
            row.update(extra(entry, index, rng))
        rows.append(row)

    return rows


def _metric(key, label, icon, kind, good, value, variation) -> dict:
    return {
        "key": key,
        "label": label,
        "icon": icon,
        "type": kind,
        "good": good,
        "value": value,
        "variation": variation,
        "spark": [],
    }


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def get_dataset(period_id: str = DEFAULT_PERIOD) -> dict:
    period = get_period(period_id)
    # crc32 e não hash(): o hash de string em Python é randomizado por
    # processo, o que faria os números mudarem a cada restart do servidor.
    seed = zlib.crc32(period_id.encode("utf-8"))

    # Períodos de 1 dia ainda precisam de uma curva para desenhar: usamos a
    # janela mínima de 7 pontos para o gráfico não virar um ponto solto.
    days = period["days"]
    end = REFERENCE_DATE

    series = _build_series(days, end, seed)
    prior_series = _build_series(days, end - timedelta(days=days), seed + 977)

    current = _aggregate(series)
    previous = _aggregate(prior_series)

    kpis = _build_kpis(current, previous, series)
    campaigns = _build_campaigns(current["investimento"], seed + 31)

    meta_invest = sum(c["investimento"] for c in campaigns if c["canal"] == "meta")
    google_invest = sum(c["investimento"] for c in campaigns if c["canal"] == "google")

    # ---- Distribuição por canal -------------------------------------------
    # Três cores de identidade + um cinza para "Outros". A legenda traz nome
    # e valor em texto, então a leitura nunca depende só da cor.
    channels = [
        {"key": "meta", "nome": "Meta Ads", "valor": meta_invest},
        {"key": "google", "nome": "Google Ads", "valor": google_invest},
        {"key": "organico", "nome": "Orgânico + CRM", "valor": round(current["investimento"] * 0.11)},
        {"key": "outros", "nome": "Outros", "valor": round(current["investimento"] * 0.06)},
    ]

    # ---- Funil -------------------------------------------------------------
    # Termina em Leads: a etapa de venda foi retirada do produto junto com a
    # métrica de conversões.
    stages = [
        {"etapa": "Impressões", "valor": current["impressoes"]},
        {"etapa": "Cliques", "valor": current["cliques"]},
        {"etapa": "Leads", "valor": current["leads"]},
    ]
    funnel = []
    for index, stage in enumerate(stages):
        funnel.append(
            {
                **stage,
                "taxa": 100.0 if index == 0 else stage["valor"] / stages[index - 1]["valor"] * 100,
                "do_topo": stage["valor"] / stages[0]["valor"] * 100,
            }
        )

    # ---- Meta Ads ----------------------------------------------------------
    meta_share = meta_invest / current["investimento"]
    meta_impressoes = round(current["impressoes"] * meta_share)
    meta_cliques = round(current["cliques"] * meta_share)
    meta_conversoes = max(1, round(current["conversoes"] * 0.58))
    meta_leads = round(current["leads"] * 0.62)
    meta_alcance = round(meta_impressoes / 1.74)

    meta_metrics = [
        _metric("investimento", "Investimento", "wallet", "currency", "neutral", meta_invest, 8.4),
        _metric("cpm", "CPM", "layers", "currency_cents", "down", meta_invest / meta_impressoes * 1000, -4.1),
        _metric("ctr", "CTR", "mouse-pointer-click", "percent", "up", meta_cliques / meta_impressoes * 100, 6.7),
        _metric("cpc", "CPC", "pointer", "currency_cents", "down", meta_invest / meta_cliques, -2.9),
        _metric("cliques", "Cliques", "mouse-pointer-2", "compact", "up", meta_cliques, 11.2),
        _metric("alcance", "Alcance", "radar", "compact", "up", meta_alcance, 9.5),
        _metric("impressoes", "Impressões", "eye", "compact", "up", meta_impressoes, 12.8),
        _metric("frequencia", "Frequência", "repeat", "decimal", "down", meta_impressoes / meta_alcance, 3.2),
        _metric("resultados", "Resultados", "flag", "int", "up", meta_leads, 14.6),
        _metric("cpl", "CPL", "user-plus", "currency_cents", "down", meta_invest / meta_leads, -5.4),
        _metric("cpa", "CPA", "target", "currency_cents", "down", meta_invest / meta_conversoes, -6.8),
    ]

    meta_campaigns = [c for c in campaigns if c["canal"] == "meta"]
    by_cpl = sorted(meta_campaigns, key=lambda c: c["cpl"])
    by_ctr = sorted(meta_campaigns, key=lambda c: c["ctr"])
    by_spend = sorted(meta_campaigns, key=lambda c: c["investimento"])
    by_revenue = sorted(meta_campaigns, key=lambda c: c["receita"])

    # Sem ROAS, a leitura de eficiência passa a ser o CPL: é o custo com
    # denominador visível no produto, já que conversões também saiu.
    meta_highlights = [
        {"label": "Melhor campanha", "hint": "maior receita gerada", "item": by_revenue[-1],
         "metric": "receita", "type": "currency", "tone": "positive", "icon": "trophy"},
        {"label": "Pior campanha", "hint": "lead mais caro do período", "item": by_cpl[-1],
         "metric": "cpl", "type": "currency_cents", "tone": "negative", "icon": "trending-down"},
        {"label": "Maior CTR", "hint": "melhor taxa de clique", "item": by_ctr[-1],
         "metric": "ctr", "type": "percent", "tone": "neutral", "icon": "mouse-pointer-click"},
        {"label": "Menor CPL", "hint": "lead mais barato do período", "item": by_cpl[0],
         "metric": "cpl", "type": "currency_cents", "tone": "positive", "icon": "award"},
        {"label": "Maior gasto", "hint": "maior fatia do investimento", "item": by_spend[-1],
         "metric": "investimento", "type": "currency", "tone": "neutral", "icon": "wallet"},
    ]

    # ---- Google Ads --------------------------------------------------------
    google_share = google_invest / current["investimento"]
    g_impressoes = round(current["impressoes"] * google_share)
    g_cliques = round(current["cliques"] * google_share)
    g_conversoes = max(1, round(current["conversoes"] * 0.42))
    g_leads = max(1, round(current["leads"] * 0.38))

    google_metrics = [
        _metric("investimento", "Investimento", "wallet", "currency", "neutral", google_invest, 5.2),
        _metric("impressoes", "Impressões", "eye", "compact", "up", g_impressoes, 9.1),
        _metric("cliques", "Cliques", "mouse-pointer-2", "compact", "up", g_cliques, 7.4),
        _metric("ctr", "CTR", "mouse-pointer-click", "percent", "up", g_cliques / g_impressoes * 100, 3.8),
        _metric("cpc", "CPC médio", "pointer", "currency_cents", "down", google_invest / g_cliques, -1.6),
        _metric("cpl", "CPL", "user-plus", "currency_cents", "down", google_invest / max(1, g_leads), -3.9),
        _metric("cpa", "CPA", "target", "currency_cents", "down", google_invest / g_conversoes, -5.7),
        _metric("is", "Impression Share", "chart-pie", "percent", "up", 62.4, 2.1),
        _metric("top_is", "Top Impression", "arrow-up-narrow-wide", "percent", "up", 41.8, -1.4),
        _metric("search_is", "Search Imp. Share", "search", "percent", "up", 58.9, 4.6),
        _metric("qs", "Quality Score médio", "gauge", "decimal", "up", 7.4, 2.8),
    ]

    def keyword_extra(entry, index, rng):
        return {
            "correspondencia": entry[1],
            "qs": entry[2],
            "posicao": round(1 + rng.random() * 2.4, 1),
        }

    def scaled(rows, factor):
        return [
            {
                **row,
                "investimento": round(row["investimento"] * factor),
                "receita": round(row["receita"] * factor),
            }
            for row in rows
        ]

    return {
        "period": period,
        "range": {"start": series[0]["date"], "end": series[-1]["date"]},
        "series": series,
        "totals": current,
        "previous": previous,
        "kpis": kpis,
        "channels": channels,
        "funnel": funnel,
        "campaigns": campaigns,
        "meta": {
            "metrics": meta_metrics,
            "campaigns": meta_campaigns,
            "adsets": _build_rows(ADSET_NAMES, meta_invest, seed + 71),
            "ads": _build_rows(AD_NAMES, meta_invest, seed + 113),
            "highlights": meta_highlights,
            "series": scaled(series, 0.55),
        },
        "google": {
            "metrics": google_metrics,
            "campaigns": [c for c in campaigns if c["canal"] == "google"],
            "groups": _build_rows(GROUP_NAMES, google_invest, seed + 149),
            "keywords": _build_rows(KEYWORD_ROWS, google_invest, seed + 191, keyword_extra),
            "ads": _build_rows(GOOGLE_AD_NAMES, google_invest, seed + 233),
            "series": scaled(series, 0.45),
        },
    }


# --------------------------------------------------------------------------
# Conta / cliente
# --------------------------------------------------------------------------

ACCOUNT = {
    "cliente": "Nutrilab Suplementos",
    "plano": "Growth",
    "gestor": "Gabriel Lisboa",
    "email": "ferramentas.lisboa@v4company.com",
    "iniciais": "GL",
    "contas": [
        {"id": "nutrilab", "nome": "Nutrilab Suplementos", "plano": "Growth"},
        {"id": "vitrine", "nome": "Vitrine Casa & Decor", "plano": "Scale"},
        {"id": "clinix", "nome": "Clinix Odontologia", "plano": "Starter"},
    ],
}

STATUS_LABEL = {
    "active": {"label": "Ativa", "tone": "positive"},
    "paused": {"label": "Pausada", "tone": "warning"},
    "draft": {"label": "Rascunho", "tone": "neutral"},
    "ended": {"label": "Encerrada", "tone": "neutral"},
}

REPORTS = [
    {"id": 1, "nome": "Performance semanal consolidada", "formato": "PDF",
     "frequencia": "Toda segunda, 08:00", "destino": "3 destinatários",
     "atualizado": "2026-08-03", "status": "active"},
    {"id": 2, "nome": "Fechamento mensal — Meta + Google", "formato": "PDF",
     "frequencia": "Dia 1, 09:00", "destino": "5 destinatários",
     "atualizado": "2026-08-01", "status": "active"},
    {"id": 3, "nome": "Base bruta de campanhas", "formato": "CSV",
     "frequencia": "Diário, 06:00", "destino": "Google Drive",
     "atualizado": "2026-08-06", "status": "active"},
    {"id": 4, "nome": "Análise de criativos — Meta", "formato": "PDF",
     "frequencia": "Quinzenal", "destino": "2 destinatários",
     "atualizado": "2026-07-22", "status": "paused"},
    {"id": 5, "nome": "Termos de busca — Google", "formato": "XLSX",
     "frequencia": "Toda sexta, 17:00", "destino": "1 destinatário",
     "atualizado": "2026-07-31", "status": "active"},
]
