"""
Dashboard principal.

Ordem de leitura pensada de cima para baixo: as métricas primeiro (o "como
estamos"), depois as curvas (o "como chegamos aqui") e por último a tabela de
campanhas (o "onde mexer"). Quem só tem dez segundos lê a primeira faixa e já
sabe a saúde da conta.

Quais métricas aparecem na primeira faixa é escolha do cliente, feita no
seletor da topbar e guardada no navegador.
"""

from __future__ import annotations

import dash
from dash import ALL, Input, Output, State, callback, ctx, html
from dash.exceptions import PreventUpdate

from core import fmt
from core.auth import active_tenant
from core.data import DEFAULT_PERIOD, METRIC_KEYS, get_dataset, get_period
from core.theme import entity_color, series_color
from ui import charts
from ui.kpi import kpi_grid
from ui.primitives import card, card_header, empty_state
from ui.shell import page_head, select_client_state
from ui.tables import data_table

dash.register_page(__name__, path="/", name="Dashboard", title="Dashboard")


def _sanitize(selected):
    """
    A seleção fica salva no navegador, então pode estar velha: se uma métrica
    foi retirada do produto, a chave dela continua no `localStorage` de quem
    já usou o app. Chave desconhecida é descartada; e se TODAS forem
    desconhecidas, a seleção é tratada como inexistente e volta ao padrão —
    senão o cliente abriria o painel vazio sem entender por quê.
    """
    if selected is None:
        return list(METRIC_KEYS)

    known = [key for key in METRIC_KEYS if key in selected]
    if selected and not known:
        return list(METRIC_KEYS)
    return known


def _kpi_section(kpis, selected, compare_label):
    """A faixa de métricas respeita a seleção; sem nenhuma, explica o caminho."""
    visible = [k for k in kpis if k["key"] in selected]

    if not visible:
        return card(
            empty_state(
                title="Nenhuma métrica selecionada",
                description=(
                    "Escolha quais indicadores quer acompanhar no botão "
                    "\"Métricas\", no topo da tela."
                ),
                glyph="sliders-horizontal",
            ),
            className="anim-up",
            style={"marginBottom": "22px"},
        )

    return kpi_grid(visible, compare_label=compare_label)


def _plot_config(config) -> tuple[list[str], dict]:
    """
    Configuração do gráfico personalizável, higienizada.

    Vive no `localStorage`, então pode chegar velha ou adulterada: métrica que
    não existe mais é descartada e, sem nada válido, volta ao padrão.
    """
    config = config if isinstance(config, dict) else {}
    keys = [key for key in config.get("metrics") or [] if key in charts.PLOTTABLE]
    colors = config.get("colors") if isinstance(config.get("colors"), dict) else {}
    return (keys or list(charts.DEFAULT_PLOT)), colors


def _custom_chart_card(series, keys, colors):
    """Gráfico que o cliente monta, com o painel de ajuste no próprio card."""
    from ui.icons import icon

    legend_items = [
        {
            "label": charts.PLOTTABLE[key]["label"],
            "color": colors.get(key) or series_color(
                ["primary", "secondary", "tertiary", "neutral"][position % 4]
            ),
            "shape": "line",
        }
        for position, key in enumerate(keys)
    ]

    return card(
        [
            card_header(
                "Desempenho",
                subtitle="Escolha as métricas e as cores no botão à direita",
                action=html.Div(
                    [
                        html.Div(charts.legend(legend_items), id="chart-legend",
                         className="chart-card__legend"),
                        html.Div(
                            [
                                html.Button(
                                    [icon("sliders-horizontal", 15), html.Span("Personalizar")],
                                    id="chart-trigger",
                                    n_clicks=0,
                                    type="button",
                                    className="btn btn--outline btn--sm",
                                ),
                                html.Div(id="chart-scrim", n_clicks=0, className="scrim hide"),
                                html.Div(
                                    charts.chart_settings(keys, colors),
                                    id="chart-menu",
                                    className="pop pop--right hide",
                                    style={"width": "290px"},
                                ),
                            ],
                            className="pop-anchor",
                        ),
                    ],
                    className="row gap-3",
                ),
            ),
            # O wrapper é quem a callback troca: o gráfico dentro dele é só
            # o container do Chart.js, refeito com a especificação nova.
            html.Div(charts.graph(charts.custom_series(series, keys, colors)), id="chart-figure"),
        ],
        className="span-8",
    )


def _body(period_id: str, selected: list[str], plot_config=None):
    # Master sem cliente escolhido (ex.: navegou pelo menu lateral).
    if not active_tenant():
        return [select_client_state()]
    data = get_dataset(period_id)
    period = get_period(period_id)
    series = data["series"]
    totals = data["totals"]
    plot_keys, plot_colors = _plot_config(plot_config)

    return [
        page_head(
            "Visão geral",
            [("Visão geral", None)],
            description=(
                f'{fmt.long_date(data["range"]["start"])} a {fmt.long_date(data["range"]["end"])} '
                f'· comparado com {period["compare"]}'
            ),
        ),

        # A faixa tem id próprio para o seletor de métricas trocar SÓ ela.
        html.Div(_kpi_section(data["kpis"], selected, period["compare"]), id="kpi-band"),

        # ---- Curvas --------------------------------------------------------
        html.Div(
            [
                _custom_chart_card(series, plot_keys, plot_colors),
                charts.chart_card(
                    "Distribuição dos canais",
                    subtitle="Participação de cada canal no investimento",
                    body=html.Div(
                        [
                            charts.graph(charts.channel_donut(data["channels"])),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                className="legend__swatch",
                                                style={"background": entity_color(c["key"])},
                                            ),
                                            html.Span(c["nome"], className="grow truncate"),
                                            html.Span(fmt.brl(c["valor"]), className="legend__value"),
                                        ],
                                        className="legend__item",
                                        style={"width": "100%", "padding": "5px 0"},
                                    )
                                    for c in data["channels"]
                                ],
                                style={"padding": "0 20px 4px"},
                            ),
                        ]
                    ),
                    className="span-4",
                ),
            ],
            className="grid",
        ),

        html.Div(
            [
                charts.chart_card(
                    "Custo por lead",
                    figure=charts.cost_line(series, "cpl", series_color("primary"), "CPL"),
                    subtitle="Quanto custou cada lead, dia a dia — quanto mais baixo, melhor",
                    legend_items=[
                        {"label": "CPL médio", "color": series_color("primary"), "shape": "line",
                         "value": fmt.brl_cents(totals["cpl"])},
                    ],
                    className="span-8",
                ),
                card(
                    [
                        card_header(
                            "Funil",
                            subtitle="Taxa de passagem entre etapas",
                            lead_icon="funnel",
                        ),
                        charts.funnel_stages(data["funnel"]),
                    ],
                    className="span-4",
                ),
            ],
            className="grid",
        ),

        html.Div(
            [
                charts.chart_card(
                    "Leads por dia",
                    figure=charts.daily_bars(series, "leads", series_color("secondary"), "Leads"),
                    subtitle=f'{fmt.integer(totals["leads"])} no período',
                    className="span-6",
                ),
                charts.chart_card(
                    "Investimento acumulado",
                    figure=charts.cumulative_area(series, "investimento"),
                    subtitle=f'{fmt.brl(totals["investimento"])} no período',
                    className="span-6",
                ),
            ],
            className="grid",
        ),

        # ---- Onde agir -----------------------------------------------------
        data_table(
            "campanhas",
            period_id,
            "Campanhas",
            subtitle="Todos os canais · clique no cabeçalho para ordenar",
        ),
    ]


def layout():
    return html.Div(_body(DEFAULT_PERIOD, METRIC_KEYS), id="page-dashboard", className="anim-up")


@callback(
    Output("page-dashboard", "children"),
    Input("period-store", "data"),
    Input("refresh-store", "data"),
    # Métricas e configuração do gráfico entram como State, não como Input.
    # Cada uma tem a própria callback, que troca só o pedaço que lhe cabe:
    # marcar uma métrica ou uma cor não pode reconstruir KPIs, curvas, funil,
    # rosca e tabela junto — era isso que fazia a tela inteira piscar.
    State("metrics-store", "data"),
    State("chart-store", "data"),
    prevent_initial_call=True,
)
def _reload(period_id, _tick, selected, plot_config):
    return _body(period_id or DEFAULT_PERIOD, _sanitize(selected), plot_config)


@callback(
    Output("kpi-band", "children"),
    Input("metrics-store", "data"),
    State("period-store", "data"),
    prevent_initial_call=True,
)
def _reload_kpis(selected, period_id):
    """Só a faixa de indicadores. O resto da tela não depende da seleção."""
    period_id = period_id or DEFAULT_PERIOD
    data = get_dataset(period_id)
    return _kpi_section(data["kpis"], _sanitize(selected), get_period(period_id)["compare"])


@callback(
    Output("chart-menu", "className"),
    Output("chart-scrim", "className"),
    Output("chart-menu", "children"),
    Output("chart-store", "data"),
    # Só o gráfico e a legenda são refeitos — o resto da tela fica parado.
    Output("chart-figure", "children"),
    Output("chart-legend", "children"),
    Input("chart-trigger", "n_clicks"),
    Input("chart-scrim", "n_clicks"),
    Input({"type": "chart-metric", "key": ALL}, "n_clicks"),
    # `group: "chart"` isola dos campos de cor de outras telas. Sem isso a
    # callback ficava elegível no /admin (que também usa color_input) e
    # quebrava procurando o "chart-trigger", que só existe aqui.
    Input({"type": "color-value", "group": "chart", "for": ALL}, "value"),
    State("chart-menu", "className"),
    State("chart-store", "data"),
    State("period-store", "data"),
    prevent_initial_call=True,
)
def _chart_settings(_open, _scrim, metric_clicks, color_values, menu_class, config, period_id):
    """
    Abrir, marcar métrica e trocar cor — tudo numa callback.

    O menu NÃO fecha ao marcar: montar um gráfico é uma sequência de ajustes,
    e reabrir a cada clique tornaria a personalização insuportável.
    """
    from ui.primitives import classes

    trigger = ctx.triggered_id
    kind = trigger.get("type") if isinstance(trigger, dict) else trigger
    was_open = "hide" not in (menu_class or "")
    open_menu = was_open

    # Callbacks com `ALL` também disparam quando os componentes NASCEM (ao
    # entrar na tela ou refazê-la), com n_clicks 0. Sem esta guarda o painel
    # de personalização podia abrir ou trocar métrica sozinho ao entrar.
    fired = ctx.triggered[0].get("value") if ctx.triggered else None
    if kind in ("chart-trigger", "chart-scrim", "chart-metric") and not fired:
        raise PreventUpdate
    # Métrica e cor só mudam com o painel aberto; com ele fechado, o disparo
    # é o nascimento dos campos, não uma escolha.
    if kind in ("chart-metric", "color-value") and not was_open:
        raise PreventUpdate

    keys, colors = _plot_config(config)
    keys = list(keys)
    colors = dict(colors)

    if kind == "chart-trigger":
        open_menu = not was_open
    elif kind == "chart-scrim":
        open_menu = False
    elif kind == "chart-metric":
        key = trigger["key"]
        if key in keys:
            # A última métrica não sai: um gráfico sem série nenhuma é uma
            # caixa vazia, e o caminho de volta não fica óbvio.
            if len(keys) > 1:
                keys.remove(key)
        else:
            keys.append(key)
        # mantém a ordem canônica do catálogo, não a ordem dos cliques
        keys = [item for item in charts.PLOTTABLE if item in keys]
    elif kind == "color-value":
        # Hexadecimal incompleto sendo digitado é ignorado até virar cor válida.
        from ui.primitives import HEX_COLOR

        # `inputs_list` traz uma lista quando o padrão casa vários componentes
        # e um dicionário quando casa um só — normalizar evita iterar as
        # chaves de um dicionário como se fossem componentes.
        entries = ctx.inputs_list[3]
        if isinstance(entries, dict):
            entries = [entries]

        for entry, value in zip(entries or [], color_values or []):
            metric_key = (entry.get("id") or {}).get("for") if isinstance(entry, dict) else None
            if metric_key in charts.PLOTTABLE and HEX_COLOR.fullmatch((value or "").strip()):
                colors[metric_key] = value.strip().upper()

    classe_menu = classes("pop", "pop--right", None if open_menu else "hide")
    classe_scrim = classes("scrim", None if open_menu else "hide")

    # Abrir ou fechar o menu não muda o gráfico. Refazer figura, legenda e o
    # conteúdo do menu nesse caso custava uma leitura do dataset e repintava o
    # card inteiro — era o "clicar em Personalizar recarrega tudo".
    if kind in ("chart-trigger", "chart-scrim"):
        return (
            classe_menu,
            classe_scrim,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )

    series = get_dataset(period_id or DEFAULT_PERIOD)["series"]
    legend_items = [
        {
            "label": charts.PLOTTABLE[key]["label"],
            "color": colors.get(key) or series_color(
                ["primary", "secondary", "tertiary", "neutral"][position % 4]
            ),
            "shape": "line",
        }
        for position, key in enumerate(keys)
    ]

    return (
        classe_menu,
        classe_scrim,
        charts.chart_settings(keys, colors),
        {"metrics": keys, "colors": colors},
        charts.graph(charts.custom_series(series, keys, colors)),
        charts.legend(legend_items),
    )
