"""
Campanhas — a tabela completa, sem os gráficos.

É a tela de trabalho: quem chega aqui já sabe o que quer procurar. Por isso
só quatro números no topo (o suficiente para dar contexto) e o resto do
espaço todo para a tabela.
"""

from __future__ import annotations

import dash
from dash import ALL, Input, Output, callback, ctx, html

from core.auth import active_tenant
from core.data import DEFAULT_PERIOD, STATUS_LABEL, get_dataset, get_period
from ui.kpi import kpi_grid
from ui.primitives import badge, button, segmented
from ui.shell import page_head, select_client_state
from ui.tables import data_table

dash.register_page(__name__, path="/campanhas", name="Campanhas", title="Campanhas")

TABS = [
    {"label": "Conjuntos", "value": "meta-conjuntos", "count": 0},
    {"label": "Anúncios", "value": "meta-anuncios", "count": 0},
]

TAB_CONFIG = {
    "meta-conjuntos": ("Conjuntos de anúncios", "Estrutura de conjuntos da conta Meta Ads"),
    "meta-anuncios": ("Anúncios", "Clique no criativo para ampliar e consultar as métricas"),
}


def _summary(campaigns):
    invest = sum(c["investimento"] for c in campaigns)
    leads = sum(c["leads"] for c in campaigns)
    cliques = sum(c.get("cliques", 0) for c in campaigns)
    active = sum(1 for c in campaigns if c["status"] == "active")

    return [
        {"key": "ativas", "label": "Campanhas ativas", "icon": "megaphone", "type": "int",
         "good": "up", "value": active, "variation": 0.0, "spark": []},
        {"key": "investimento", "label": "Investimento total", "icon": "wallet", "type": "currency",
         "good": "neutral", "value": invest, "variation": 8.2, "spark": []},
        {"key": "cliques", "label": "Cliques", "icon": "mouse-pointer-2", "type": "compact",
         "good": "up", "value": cliques, "variation": 9.4, "spark": []},
        {"key": "leads", "label": "Leads", "icon": "magnet", "type": "int",
         "good": "up", "value": leads, "variation": 11.3, "spark": []},
        {"key": "cpl", "label": "CPL médio", "icon": "user-plus", "type": "currency_cents",
         "good": "down", "value": invest / leads if leads else 0, "variation": -6.4, "spark": []},
    ]


def _body(period_id: str, active_tab: str = "meta-conjuntos"):
    # Master sem cliente escolhido (ex.: navegou pelo menu lateral).
    if not active_tenant():
        return [select_client_state()]
    data = get_dataset(period_id)
    period = get_period(period_id)
    campaigns = data["campaigns"]
    tabs = [
        {**tab, "count": len({
            "meta-conjuntos": data["meta"]["adsets"],
            "meta-anuncios": data["meta"]["ads"],
        }[tab["value"]])}
        for tab in TABS
    ]
    table_title, table_subtitle = TAB_CONFIG.get(active_tab, TAB_CONFIG["meta-conjuntos"])

    counts = {}
    for campaign in campaigns:
        counts[campaign["status"]] = counts.get(campaign["status"], 0) + 1

    return [
        page_head(
            "Campanhas",
            [("Operação", None), ("Campanhas", None)],
            description=f'{len(campaigns)} campanhas nos últimos {period["days"]} dias, em todos os canais',
            glyph="megaphone",
            actions=html.Div(
                [
                    button("Exportar CSV", variant="outline", size="sm", lead_icon="download"),
                ],
                className="row gap-2",
            ),
        ),

        kpi_grid(_summary(campaigns), compare_label=period["compare"]),

        html.Div(
            [
                badge(
                    f'{STATUS_LABEL[status]["label"]} · {total}',
                    STATUS_LABEL[status]["tone"],
                    dot=True,
                )
                for status, total in counts.items()
            ],
            className="row gap-2",
            style={"marginBottom": "14px"},
        ),

        html.Div(
            segmented(tabs, active_tab, "campaign-entity-tab", "campaigns"),
            style={"marginBottom": "12px"},
        ),

        data_table(
            active_tab,
            period_id,
            table_title,
            subtitle=f"{table_subtitle} · clique no cabeçalho para ordenar",
        ),
    ]


def layout():
    return html.Div(_body(DEFAULT_PERIOD), id="page-campanhas", className="anim-up")


@callback(
    Output("page-campanhas", "children"),
    Input("period-store", "data"),
    Input("refresh-store", "data"),
    Input({"type": "campaign-entity-tab", "group": "campaigns", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _reload(period_id, _tick, _tabs):
    trigger = ctx.triggered_id
    active_tab = trigger["value"] if isinstance(trigger, dict) else "meta-conjuntos"
    return _body(period_id or DEFAULT_PERIOD, active_tab)
