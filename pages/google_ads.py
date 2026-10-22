"""
Google Ads — mesmo padrão visual do Meta, métricas da plataforma.

As quatro métricas de leilão (IS, Top Impression, Search IS, Quality Score)
ficam no mesmo bloco das demais de propósito: elas explicam POR QUE o
volume está onde está, e separá-las em outro card faria o cliente ler o
resultado sem a causa.
"""

from __future__ import annotations

import dash
from dash import ALL, Input, Output, callback, ctx, html

from core import fmt
from core.auth import active_tenant
from core.data import DEFAULT_PERIOD, get_dataset, get_period
from core.theme import series_color
from ui import charts
from ui.kpi import kpi_grid
from ui.primitives import badge, card, card_header, no_delivery_state, segmented
from ui.shell import page_head, select_client_state
from ui.tables import data_table

dash.register_page(__name__, path="/google-ads", name="Google Ads", title="Google Ads")

TABS = [
    {"label": "Campanhas", "value": "google-campanhas", "count": 7},
    {"label": "Grupos", "value": "google-grupos", "count": 8},
    {"label": "Palavras-chave", "value": "google-keywords", "count": 12},
    {"label": "Anúncios", "value": "google-anuncios", "count": 8},
]

TAB_TITLES = {
    "google-campanhas": ("Campanhas", "Search, Shopping, PMax, Display e YouTube"),
    "google-grupos": ("Grupos de anúncios", "Agrupamento temático dentro de cada campanha"),
    "google-keywords": ("Palavras-chave", "Termos comprados, com correspondência e Quality Score"),
    "google-anuncios": ("Anúncios", "Criativos e variações em veiculação"),
}


def _connection_badge(connection: dict):
    status = connection.get("status")
    labels = {
        "connected": "Conta conectada",
        "unconfigured": "Conta não vinculada",
        "syncing": "Sincronizando dados",
        "stale": "Último dado válido",
        "error": "Erro na sincronização",
    }
    tones = {"connected": "positive", "unconfigured": "neutral", "syncing": "neutral", "stale": "warning", "error": "negative"}
    return html.Span(
        badge(labels.get(status, "Conexão indisponível"), tones.get(status, "neutral"), dot=True),
        title=connection.get("message", ""),
    )


def _auction_panel(metrics):
    """
    Leilão em barras de participação: percentual pede uma leitura de
    "quanto do total", e uma barra faz isso melhor que o número sozinho.
    """
    auction = [m for m in metrics if m["key"] in ("is", "top_is", "search_is")]
    rows = []

    for metric in auction:
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(metric["label"], className="highlight__label"),
                            html.Span(fmt.pct(metric["value"], 1), className="highlight__value"),
                        ],
                        className="highlight__head",
                    ),
                    html.Div(
                        html.Span(
                            className="cell-bar__fill",
                            style={"width": f'{metric["value"]:.0f}%'},
                        ),
                        className="cell-bar__track",
                        style={"width": "100%", "height": "5px", "marginTop": "8px"},
                    ),
                    html.Span(
                        f'{fmt.pct(100 - metric["value"], 1)} do leilão ainda disponível',
                        className="highlight__hint",
                        style={"marginTop": "6px"},
                    ),
                ],
                className="highlight",
            )
        )

    quality = next(m for m in metrics if m["key"] == "qs")
    rows.append(
        html.Div(
            [
                html.Div(
                    [
                        html.Span("Quality Score médio", className="highlight__label"),
                        html.Span(f'{fmt.dec(quality["value"], 1)} / 10', className="highlight__value"),
                    ],
                    className="highlight__head",
                ),
                html.Span(
                    "Acima de 7 reduz o CPC no leilão",
                    className="highlight__hint",
                    style={"marginTop": "4px"},
                ),
            ],
            className="highlight",
        )
    )

    return rows


def _body(period_id: str, active_tab: str = "google-campanhas"):
    # Master sem cliente escolhido (ex.: navegou pelo menu lateral).
    if not active_tenant():
        return [select_client_state()]
    data = get_dataset(period_id)
    period = get_period(period_id)
    google = data["google"]
    series = google["series"]
    title, subtitle = TAB_TITLES[active_tab]
    tabs = [
        {**tab, "count": len(google[{
            "google-campanhas": "campaigns", "google-grupos": "groups",
            "google-keywords": "keywords", "google-anuncios": "ads",
        }[tab["value"]]])}
        for tab in TABS
    ]

    total_invest = sum(c["investimento"] for c in google["campaigns"])
    total_leads = sum(c.get("leads", 0) for c in google["campaigns"])

    cabecalho = [
        page_head(
            "Google Ads",
            [("Canais", None), ("Google Ads", None)],
            description=(
                f'{fmt.long_date(data["range"]["start"])} a {fmt.long_date(data["range"]["end"])} '
                f'· comparado com {period["compare"]}'
            ),
            glyph="brand-google",
            actions=_connection_badge(data["connections"]["google"]),
        ),
    ]

    # Mesma regra da tela do Meta: conta ligada e sem entrega no período é um
    # estado próprio, não uma tela quebrada.
    if not google["campaigns"] and not google["groups"] and not google["ads"]:
        return [
            *cabecalho,
            no_delivery_state("Google Ads", data.get("last_delivery", {}).get("google")),
        ]

    return [
        *cabecalho,

        kpi_grid(google["metrics"], compare_label=period["compare"]),

        html.Div(
            [
                charts.chart_card(
                    "Desempenho diário",
                    figure=charts.custom_series(series, ["investimento", "leads"], {}),
                    subtitle="Investimento e leads gerados no Google Ads",
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
                            "Participação no leilão",
                            subtitle="Quanto do mercado disponível a conta captura",
                            lead_icon="gauge",
                        ),
                        html.Div(_auction_panel(google["metrics"]), style={"paddingBottom": "4px"}),
                    ],
                    className="span-4",
                ),
            ],
            className="grid",
        ),

        html.Div(
            [
                charts.chart_card(
                    "Cliques por dia",
                    figure=charts.daily_bars(series, "cliques", series_color("tertiary"), "Cliques"),
                    subtitle=f'{fmt.compact(sum(r["cliques"] for r in series))} no período',
                    className="span-6",
                ),
                charts.chart_card(
                    "Leads por dia",
                    figure=charts.daily_bars(series, "leads", series_color("secondary"), "Leads"),
                    subtitle=f'{fmt.integer(sum(r["leads"] for r in series))} no período',
                    className="span-6",
                ),
            ],
            className="grid",
        ),

        html.Div(
            [
                html.Div(
                    segmented(tabs, active_tab, "google-tab", "google"),
                    style={"marginBottom": "12px"},
                ),
                data_table(active_tab, period_id, title, subtitle=subtitle),
            ],
            id="google-tabs",
        ),
    ]


def layout():
    return html.Div(_body(DEFAULT_PERIOD), id="page-google", className="anim-up")


@callback(
    Output("page-google", "children"),
    Input("period-store", "data"),
    Input("refresh-store", "data"),
    Input({"type": "google-tab", "group": "google", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _reload(period_id, _tick, _clicks):
    trigger = ctx.triggered_id
    tab = trigger["value"] if isinstance(trigger, dict) else "google-campanhas"
    return _body(period_id or DEFAULT_PERIOD, tab)
