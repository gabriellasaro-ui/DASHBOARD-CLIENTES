"""
Os blocos que o cliente escolhe mostrar (ver `core.layouts.WIDGETS`).

Cada bloco existe em dois tamanhos:

* **painel** — o card normal do dashboard, com altura fixa e largura em
  colunas da grade (`span`);
* **tv** — o mesmo conteúdo para ocupar uma fatia da tela inteira: o gráfico
  cresce até o espaço que sobrar no card (`charts.graph(fill=True)`), sem
  altura fixa que corte o conteúdo numa TV de outra resolução.

O "Desempenho" do painel continua sendo o gráfico personalizável de
`pages/dashboard.py`; aqui fica a versão fixa (investimento e leads).
"""

from __future__ import annotations

from dash import html

from core import fmt
from core.layouts import WIDGETS
from core.theme import entity_color, series_color
from ui import charts
from ui.icons import icon
from ui.platforms import platform_mark
from ui.primitives import card, card_header

# Largura de cada bloco no painel, em colunas de 12.
DASHBOARD_SPAN = {
    "desempenho": 8, "canais": 4, "cpl": 8, "funil": 4, "leads_dia": 6, "acumulado": 6,
    "meta_diario": 6, "google_diario": 6, "top_campanhas": 6, "criativo_campeao": 6,
}


def _legend_pair(total_invest, total_leads):
    return [
        {"label": "Investimento", "color": series_color("primary"), "shape": "line", "value": fmt.brl(total_invest)},
        {"label": "Leads", "color": series_color("secondary"), "shape": "line", "value": fmt.integer(total_leads)},
    ]


def _channel_legend(channels):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(className="legend__swatch", style={"background": entity_color(item["key"])}),
                    html.Span(item["nome"], className="grow truncate"),
                    html.Span(fmt.brl(item["valor"]), className="legend__value"),
                ],
                className="legend__item channel-legend__item",
            )
            for item in channels
        ],
        className="channel-legend",
    )


def _top_campaigns(campaigns, limit=6):
    """
    Nome na linha de cima, com a largura toda do card; barra e números embaixo.

    Com nome, barra e números lado a lado, o nome ficava com um terço do card e
    era cortado logo no começo — justamente a parte que o diferencia.
    """
    rows = sorted(campaigns, key=lambda row: row.get("investimento", 0), reverse=True)[:limit]
    if not rows:
        return html.P("Sem campanhas com investimento no período.", className="t-micro top-campaigns__empty")
    top = rows[0].get("investimento") or 1
    return html.Div(
        [
            html.Div(
                [
                    platform_mark(row.get("canal") or "meta", 16),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(row.get("nome") or "Sem nome", className="top-campaigns__name",
                                              title=row.get("nome")),
                                    html.Strong(fmt.brl(row.get("investimento", 0)),
                                                className="top-campaigns__value"),
                                ],
                                className="top-campaigns__line",
                            ),
                            html.Div(
                                [
                                    html.Div(html.Span(style={"width": f"{row.get('investimento', 0) / top * 100:.0f}%"}),
                                             className="top-campaigns__bar"),
                                    html.Span(f'{fmt.integer(row.get("leads", 0))} leads · CPL '
                                              f'{fmt.brl_cents(row.get("cpl", 0))}', className="top-campaigns__meta"),
                                ],
                                className="top-campaigns__line",
                            ),
                        ],
                        className="top-campaigns__main",
                    ),
                ],
                className="top-campaigns__row",
            )
            for row in rows
        ],
        className="top-campaigns",
    )


def pick_champion(ads: list[dict]):
    """
    (campeão, critério, próximos dois) entre os anúncios da Meta do período.

    Com lead no período, ganha quem trouxe MAIS leads (empate: o de menor
    CPL). Sem nenhum lead — conta de tráfego, de vídeo, ou semana fraca —
    ganha quem trouxe mais cliques, e a tela diz que o critério mudou: um
    "campeão" com zero leads sem explicação pareceria erro.
    """
    active = [ad for ad in ads if ad.get("investimento") or ad.get("impressoes")]
    if not active:
        return None, None, []
    if any(ad.get("leads") for ad in active):
        ranked = sorted(active, key=lambda ad: (-(ad.get("leads") or 0), ad.get("cpl") or float("inf")))
        reason = "Mais leads no período"
    else:
        ranked = sorted(active, key=lambda ad: (-(ad.get("cliques") or 0), -(ad.get("ctr") or 0)))
        reason = "Mais cliques no período (nenhum anúncio gerou lead)"
    return ranked[0], reason, ranked[1:3]


def _creative_image(url: str | None, className: str):
    """
    Imagem como fundo sobre um marcador de "sem imagem".

    O link da imagem que a Meta devolve expira em alguns dias; vencido, uma
    tag <img> viraria o ícone de imagem quebrada na TV. Como fundo de CSS, o
    link morto simplesmente não pinta, e o marcador de baixo aparece.
    """
    layers = [html.Span(icon("eye-off", 22), className="champion__placeholder")]
    if url:
        safe = url.replace('"', "%22")
        layers.append(html.Span(className="champion__picture", style={"backgroundImage": f'url("{safe}")'}))
    return html.Div(layers, className=className)


def _champion(ads: list[dict]):
    best, reason, runners = pick_champion(ads)
    if not best:
        return html.P("Sem anúncios da Meta com entrega no período.", className="t-micro champion__empty"), None

    stats = [
        ("Leads", fmt.integer(best.get("leads", 0))),
        ("CPL", fmt.brl_cents(best.get("cpl", 0)) if best.get("leads") else "—"),
        ("Investimento", fmt.brl(best.get("investimento", 0))),
        ("CTR", fmt.pct(best.get("ctr", 0))),
    ]
    body = html.Div(
        [
            html.Div(
                [
                    _creative_image(best.get("creative_url"), "champion__media"),
                    html.Span([icon("trophy", 14), html.Span("Campeão")], className="champion__badge"),
                ],
                className="champion__media-wrap",
            ),
            html.Div(
                [
                    html.Span(best.get("campanha") or "Meta Ads", className="champion__context"),
                    html.Strong(best.get("nome") or "Anúncio", className="champion__name", title=best.get("nome")),
                    html.Div(
                        [html.Div([html.Span(label), html.Strong(value)], className="champion__stat")
                         for label, value in stats],
                        className="champion__stats",
                    ),
                    html.Div(
                        [
                            html.Span("Logo atrás", className="champion__runners-title"),
                            *[
                                html.Div(
                                    [
                                        _creative_image(ad.get("creative_url"), "champion__thumb"),
                                        html.Div(
                                            [
                                                html.Span(ad.get("nome") or "Anúncio", className="champion__runner-name",
                                                          title=ad.get("nome")),
                                                html.Span(
                                                    f'{fmt.integer(ad.get("leads", 0))} leads · '
                                                    f'{fmt.integer(ad.get("cliques", 0))} cliques',
                                                    className="champion__runner-meta",
                                                ),
                                            ],
                                            className="champion__runner-text",
                                        ),
                                    ],
                                    className="champion__runner",
                                )
                                for ad in runners
                            ],
                        ],
                        className="champion__runners",
                    ) if runners else None,
                ],
                className="champion__info",
            ),
        ],
        className="champion",
    )
    return body, reason


def content(key: str, data: dict, *, tv: bool = False, campaign_limit: int = 6):
    """
    (título, subtítulo, corpo, legenda) de um bloco de gráfico.

    `kpis` e `campanhas` não passam por aqui: a faixa de indicadores e a
    tabela têm forma própria.
    """
    series = data["series"]
    totals = data["totals"]
    graph = (lambda spec: charts.graph(spec, fill=True)) if tv else charts.graph

    if key == "desempenho":
        return ("Desempenho diário", "Investimento e leads no período",
                graph(charts.custom_series(series, ["investimento", "leads"], {})),
                _legend_pair(totals["investimento"], totals["leads"]))
    if key == "canais":
        body = html.Div(
            [html.Div(graph(charts.channel_donut(data["channels"])), className="donut-slot"),
             _channel_legend(data["channels"])],
            className="channels",
        )
        return "Distribuição dos canais", "Participação no investimento", body, None
    if key == "cpl":
        return ("Custo por lead", "Quanto custou cada lead, dia a dia",
                graph(charts.cost_line(series, "cpl", series_color("primary"), "CPL")),
                [{"label": "CPL médio", "color": series_color("primary"), "shape": "line",
                  "value": fmt.brl_cents(totals["cpl"])}])
    if key == "funil":
        return "Funil", "Taxa de passagem entre etapas", charts.funnel_stages(data["funnel"]), None
    if key == "leads_dia":
        return ("Leads por dia", f'{fmt.integer(totals["leads"])} no período',
                graph(charts.daily_bars(series, "leads", series_color("secondary"), "Leads")), None)
    if key == "acumulado":
        return ("Investimento acumulado", f'{fmt.brl(totals["investimento"])} no período',
                graph(charts.cumulative_area(series, "investimento")), None)
    if key in ("meta_diario", "google_diario"):
        platform = "meta" if key == "meta_diario" else "google"
        block = data[platform]
        invest = sum(row["investimento"] for row in block["series"])
        leads = sum(row["leads"] for row in block["series"])
        return ((WIDGETS[key][0]), "Investimento e leads da plataforma",
                graph(charts.custom_series(block["series"], ["investimento", "leads"], {})),
                _legend_pair(invest, leads))
    if key == "criativo_campeao":
        body, reason = _champion(data["meta"]["ads"])
        return "Criativo campeão", reason or "Meta Ads", body, None
    if key == "top_campanhas":
        return ("Principais campanhas", "Maior investimento no período",
                _top_campaigns(data["campaigns"], campaign_limit), None)
    raise KeyError(key)


def dashboard_card(key: str, data: dict):
    title, subtitle, body, legend_items = content(key, data)
    return card(
        [
            card_header(title, subtitle=subtitle, action=charts.legend(legend_items) if legend_items else None),
            body,
        ],
        className=f"span-{DASHBOARD_SPAN.get(key, 6)}",
    )


def tv_card(key: str, data: dict, grid_rows: int = 1):
    # Campanhas: quantas cabem na altura do card (a grade divide a TV em
    # 1 ou 2 linhas). Mais que isso transbordava por baixo do card.
    limit = 7 if grid_rows <= 1 else 4
    title, subtitle, body, legend_items = content(key, data, tv=True, campaign_limit=limit)
    return html.Section(
        [
            html.Header(
                [
                    html.Div([html.H2(title, className="tv-card__title"),
                              html.Span(subtitle, className="tv-card__subtitle")]),
                    charts.legend(legend_items) if legend_items else None,
                ],
                className="tv-card__head",
            ),
            html.Div(body, className="tv-card__body"),
        ],
        className=f"tv-card tv-card--{key}",
    )


def tv_kpi(metric: dict):
    """
    Card de indicador da TV: rótulo, número grande e a variação.

    O "vs. os 30 dias anteriores" sai do card (vai uma vez no cabeçalho da
    tela): repetido em oito cards ele era cortado em todos e espremia o número.
    """
    from ui.kpi import _delta_tone

    variation = metric.get("variation", 0.0)
    tone = _delta_tone(variation, metric.get("good", "up"))
    arrow = "arrow-up-right" if variation > 0 else ("arrow-down-right" if variation < 0 else "arrow-right")
    return html.Div(
        [
            html.Span(metric["label"], className="tv-kpi__label"),
            html.Strong(fmt.by_type(metric["type"], metric["value"]), className="tv-kpi__value"),
            html.Span(
                [icon(arrow, 14), html.Span(fmt.delta(variation))],
                className=f"tv-kpi__delta kpi__delta--{tone}",
            ),
        ],
        className="tv-kpi",
    )
