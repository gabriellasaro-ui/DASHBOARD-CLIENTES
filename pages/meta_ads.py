"""
Meta Ads — layout exclusivo.

O que diferencia esta tela do dashboard geral: as métricas são as da
plataforma (frequência, alcance, resultados), a hierarquia
campanha → conjunto → anúncio aparece como um único bloco com abas, e há um
painel lateral de leituras prontas — melhor, pior, maior CTR, menor CPL,
maior gasto. É a pergunta que o cliente faz primeiro, respondida sem
precisar ordenar tabela.
"""

from __future__ import annotations

import dash
from dash import ALL, Input, Output, callback, ctx, html

from core import fmt
from core.auth import active_tenant
from core.data import DEFAULT_PERIOD, get_dataset, get_period
from core.theme import series_color
from ui import charts
from ui.icons import icon
from ui.kpi import kpi_grid
from ui.primitives import badge, card, card_header, classes, no_delivery_state, segmented
from ui.shell import page_head, select_client_state
from ui.tables import data_table

dash.register_page(__name__, path="/meta-ads", name="Meta Ads", title="Meta Ads")

TABS = [
    {"label": "Campanhas", "value": "meta-campanhas", "count": 7},
    {"label": "Conjuntos", "value": "meta-conjuntos", "count": 8},
    {"label": "Anúncios", "value": "meta-anuncios", "count": 10},
]

TAB_TITLES = {
    "meta-campanhas": ("Campanhas", "Nível mais alto da estrutura da conta"),
    "meta-conjuntos": ("Conjuntos de anúncios", "Onde moram público, orçamento e otimização"),
    "meta-anuncios": ("Anúncios", "Criativos em veiculação no período"),
}


def _connection_badge(connection: dict):
    status = connection.get("status")
    labels = {
        "connected": "Conta conectada",
        "unconfigured": "Conta não vinculada",
        "syncing": "Sincronizando dados",
        "stale": "Último dado válido",
        "error": "Meta temporariamente limitada",
    }
    tones = {"connected": "positive", "unconfigured": "neutral", "syncing": "neutral", "stale": "warning", "error": "negative"}
    return html.Span(
        badge(labels.get(status, "Conexão indisponível"), tones.get(status, "neutral"), dot=True),
        title=connection.get("message", ""),
    )


def _connection_notice(connection: dict):
    status = connection.get("status")
    if status not in ("error", "stale"):
        return None
    stale = status == "stale"
    request_id = connection.get("request_id")
    return html.Div(
        [
            icon("refresh-cw" if stale else "alert-triangle", 20),
            html.Div(
                [
                    html.Strong("Dados preservados" if stale else "A Meta bloqueou temporariamente as consultas"),
                    html.P(connection.get("message") or "Nova tentativa automática em até 10 minutos."),
                    html.Small(f"ID da requisição: {request_id}") if request_id else None,
                ]
            ),
        ],
        className=classes("connection-notice", "connection-notice--stale" if stale else "connection-notice--error"),
        role="status",
    )


def _highlights(items):
    """Painel lateral: uma leitura pronta por linha, com o número que a sustenta."""
    rows = []

    for entry in items:
        item = entry["item"]
        tone = entry["tone"]
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                [icon(entry["icon"], 18), html.Span(entry["label"])],
                                className="highlight__label",
                            ),
                            html.Span(
                                fmt.by_type(entry["type"], item[entry["metric"]]),
                                className=classes(
                                    "highlight__value",
                                    f"kpi__delta--{tone}" if tone != "neutral" else None,
                                ),
                            ),
                        ],
                        className="highlight__head",
                    ),
                    html.Span(item["nome"], className="highlight__name", title=item["nome"]),
                    html.Span(entry["hint"], className="highlight__hint"),
                ],
                className="highlight",
            )
        )

    return rows


def _body(period_id: str, active_tab: str = "meta-campanhas"):
    # Master sem cliente escolhido (ex.: navegou pelo menu lateral).
    if not active_tenant():
        return [select_client_state()]
    data = get_dataset(period_id)
    period = get_period(period_id)
    meta = data["meta"]
    series = meta["series"]
    title, subtitle = TAB_TITLES[active_tab]
    tabs = [
        {**tab, "count": len(meta[{"meta-campanhas": "campaigns", "meta-conjuntos": "adsets", "meta-anuncios": "ads"}[tab["value"]]])}
        for tab in TABS
    ]

    total_invest = sum(c["investimento"] for c in meta["campaigns"])
    total_leads = sum(c.get("leads", 0) for c in meta["campaigns"])

    cabecalho = [
        page_head(
            "Meta Ads",
            [("Canais", None), ("Meta Ads", None)],
            description=(
                f'{fmt.long_date(data["range"]["start"])} a {fmt.long_date(data["range"]["end"])} '
                f'· comparado com {period["compare"]}'
            ),
            glyph="brand-meta",
            actions=_connection_badge(data["connections"]["meta"]),
        ),
        _connection_notice(data["connections"]["meta"]),
    ]

    # Conta ligada e sincronizada, mas sem nenhuma entrega no período: mostrar
    # KPIs zerados, gráfico reto e três abas vazias faz parecer defeito da
    # integração. O estado explícito diz o que houve e desde quando.
    if not meta["campaigns"] and not meta["adsets"] and not meta["ads"]:
        return [
            *cabecalho,
            no_delivery_state("Meta Ads", data.get("last_delivery", {}).get("meta")),
        ]

    return [
        *cabecalho,

        kpi_grid(meta["metrics"], compare_label=period["compare"]),

        html.Div(
            [
                charts.chart_card(
                    "Desempenho diário",
                    figure=charts.custom_series(series, ["investimento", "leads"], {}),
                    subtitle="Investimento e leads gerados no Meta Ads",
                    legend_items=[
                        {"label": "Investimento", "color": series_color("primary"), "shape": "line",
                         "value": fmt.brl(total_invest)},
                        {"label": "Leads", "color": series_color("secondary"), "shape": "line",
                         "value": fmt.integer(total_leads)},
                    ],
                    className="span-8",
                ),
                card(
                    [
                        card_header(
                            "Destaques do período",
                            subtitle="Extremos da conta, já calculados",
                            lead_icon="sparkles",
                        ),
                        html.Div(_highlights(meta["highlights"]), style={"paddingBottom": "4px"}),
                    ],
                    className="span-4",
                ),
            ],
            className="grid",
        ),

        # Campanha → conjunto → anúncio no mesmo bloco: é a mesma estrutura,
        # muda só o nível. Três cards separados fariam o cliente rolar três vezes.
        html.Div(
            [
                html.Div(
                    segmented(tabs, active_tab, "meta-tab", "meta"),
                    style={"marginBottom": "12px"},
                ),
                data_table(active_tab, period_id, title, subtitle=subtitle),
            ],
            id="meta-tabs",
        ),
    ]


def layout():
    return html.Div(_body(DEFAULT_PERIOD), id="page-meta", className="anim-up")


@callback(
    Output("page-meta", "children"),
    Input("period-store", "data"),
    Input("refresh-store", "data"),
    Input({"type": "meta-tab", "group": "meta", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _reload(period_id, _tick, _clicks):
    trigger = ctx.triggered_id
    tab = trigger["value"] if isinstance(trigger, dict) else "meta-campanhas"
    return _body(period_id or DEFAULT_PERIOD, tab)
