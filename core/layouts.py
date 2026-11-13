"""
Quais blocos aparecem na tela: o painel do cliente e cada tela de TV.

Um "layout" é só uma lista do que mostrar, na ordem do catálogo abaixo:

* `widgets` — os blocos (indicadores, gráficos, funil, campanhas);
* `kpis` — quais indicadores entram na faixa de cards (só nas TVs; no painel
  isso continua no botão "Métricas" do topo, por navegador);
* `period` — o período fixo da tela de TV (a TV não tem quem mexa no filtro).

O que vem do banco ou do formulário passa sempre por `clean_*`: bloco que
saiu do catálogo some, lista vazia volta ao padrão. Uma configuração velha
nunca pode derrubar a tela de uma TV que ninguém está olhando.
"""

from __future__ import annotations

import json

from core.data import METRICS
from core.mock import PERIODS

# id -> (rótulo, descrição curta, cabe na TV?)
WIDGETS: dict[str, tuple[str, str, bool]] = {
    "kpis": ("Indicadores", "Faixa de cards com os números do período", True),
    "desempenho": ("Desempenho diário", "Investimento e leads, dia a dia", True),
    "canais": ("Distribuição dos canais", "Quanto foi para Meta e para Google", True),
    "cpl": ("Custo por lead", "CPL dia a dia", True),
    "funil": ("Funil", "Impressões, cliques e leads", True),
    "leads_dia": ("Leads por dia", "Barras de leads diários", True),
    "acumulado": ("Investimento acumulado", "Quanto já foi investido no período", True),
    "meta_diario": ("Meta Ads — dia a dia", "Investimento e leads só da Meta", True),
    "google_diario": ("Google Ads — dia a dia", "Investimento e leads só do Google", True),
    "top_campanhas": ("Principais campanhas", "As campanhas com mais investimento", True),
    "criativo_campeao": ("Criativo campeão", "O anúncio da Meta com mais resultado, com a imagem", True),
    "campanhas": ("Tabela de campanhas", "Todas as campanhas, com busca e ordenação", False),
}

DASHBOARD_DEFAULT = ["kpis", "desempenho", "canais", "cpl", "funil", "leads_dia", "acumulado", "campanhas"]
TV_DEFAULT_WIDGETS = ["kpis", "desempenho", "canais", "cpl", "top_campanhas", "criativo_campeao"]
TV_DEFAULT_KPIS = ["investimento", "leads", "cpl", "ctr", "cpc", "cpm"]

# Mais que isso numa TV vira letra miúda: o espaço é dividido entre todos.
TV_MAX_CHARTS = 8
TV_MAX_KPIS = 8

METRIC_LABELS = {key: label for key, label, *_ in METRICS}
PERIOD_IDS = [period["id"] for period in PERIODS]


def _load(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def _in_catalog(items, allowed) -> list[str]:
    """Mantém a ordem do CATÁLOGO, não a dos cliques, e descarta o que sumiu."""
    chosen = set(items or [])
    return [key for key in allowed if key in chosen]


def clean_dashboard(raw) -> dict:
    widgets = _in_catalog(_load(raw).get("widgets"), WIDGETS)
    return {"widgets": widgets or list(DASHBOARD_DEFAULT)}


def clean_tv(raw) -> dict:
    data = _load(raw)
    widgets = [key for key in _in_catalog(data.get("widgets"), WIDGETS) if WIDGETS[key][2]]
    kpis = _in_catalog(data.get("kpis"), METRIC_LABELS)[:TV_MAX_KPIS]
    charts = [key for key in widgets if key != "kpis"][:TV_MAX_CHARTS]
    widgets = (["kpis"] if "kpis" in widgets else []) + charts
    period = data.get("period") if data.get("period") in PERIOD_IDS else "30d"
    return {
        "widgets": widgets or list(TV_DEFAULT_WIDGETS),
        "kpis": kpis or list(TV_DEFAULT_KPIS),
        "period": period,
    }


def dumps(config: dict) -> str:
    return json.dumps(config, sort_keys=True)


def widget_options(tv: bool = False) -> list[dict]:
    return [
        {"label": label, "value": key, "title": hint}
        for key, (label, hint, fits_tv) in WIDGETS.items()
        if fits_tv or not tv
    ]


def kpi_options() -> list[dict]:
    return [{"label": label, "value": key} for key, label in METRIC_LABELS.items()]


def period_options() -> list[dict]:
    return [{"label": period["label"], "value": period["id"]} for period in PERIODS]
