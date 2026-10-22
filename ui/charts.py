"""
Gráficos — desenhados pelo Chart.js no navegador.

O Python continua decidindo TUDO que é regra: quais séries entram, em que
unidade, com que cor, onde ficam as marcas do eixo e como cada valor aparece
escrito. O que sai daqui é uma especificação em JSON, gravada no atributo
`data-chart` do container; `assets/50-charts.js` lê esse atributo e desenha.
Trocar a especificação (período, métrica, cor) redesenha o mesmo gráfico.

Regras aplicadas em todos eles, sem exceção:

* **Um eixo Y só.** Nunca dois eixos com escalas diferentes — é o erro que
  faz duas curvas parecerem se cruzar quando não se cruzam. Investimento e
  CPL convivem porque são a mesma unidade (R$). Séries de unidades
  diferentes são comparadas em base 100, nunca em dois eixos.
* **Grade só na horizontal**, hairline, sólida. Vertical vira ruído.
* **Legenda em HTML, fora do gráfico**, com swatch + nome + valor: a
  identidade da série nunca depende só da cor.
* **Rótulo seletivo.** Número em cima de cada ponto não é lido por ninguém;
  o eixo, a legenda e o tooltip carregam o resto.
* Marca fina: linha de 2px, barra com topo arredondado de 4px, área a 10%.
"""

from __future__ import annotations

import json
import math

from dash import html

from core import fmt
from core.theme import entity_color, ordinal_ramp, series_color
from ui.primitives import card, card_header, legend

# --------------------------------------------------------------------------
# Utilitários de eixo
# --------------------------------------------------------------------------

def _nice_ticks(top: float, count: int = 4) -> list[float]:
    """Marcas de eixo em números redondos (0 / 5 mil / 10 mil), nunca quebrados."""
    if top <= 0:
        return [0]

    raw_step = top / count
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for multiple in (1, 2, 2.5, 5, 10):
        step = magnitude * multiple
        if step >= raw_step:
            break

    # A última marca precisa FICAR ACIMA do topo, não parar antes dele.
    # Com a parada em `<= top`, um pico de 260 gerava marcas [0, 100, 200] e
    # o eixo terminava em 200 — a linha era cortada no meio do card.
    ticks, value = [0.0], 0.0
    while value < top:
        value += step
        ticks.append(value)
    return ticks


def _y_axis(values, formatter) -> dict:
    """Marcas do eixo Y já escritas: o navegador não reformata número."""
    top = max(values) if values else 0
    ticks = _nice_ticks(top * 1.08)
    if len(ticks) == 1:
        # Série toda zerada: um eixo de 0 a 1 em vez de uma linha colada no
        # chão sem escala nenhuma.
        ticks = [0.0, 1.0]
    return {"ticks": ticks, "labels": [formatter(tick) for tick in ticks]}


def _labels(series: list[dict]) -> list[str]:
    return [fmt.short_date(row["date"]) for row in series]


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _spec(kind: str, height: int, labels: list[str], datasets: list[dict], **extra) -> dict:
    return {"kind": kind, "height": height, "labels": labels, "datasets": datasets, **extra}


# --------------------------------------------------------------------------
# Séries temporais
# --------------------------------------------------------------------------

# Métricas que o cliente pode plotar, com a unidade de cada uma.
# A unidade é o que decide se duas séries podem dividir o mesmo eixo.
# Alcance não entra: a Meta não informa alcance por dia, só por período.
PLOTTABLE = {
    "investimento": {"label": "Investimento", "unit": "brl", "fmt": fmt.brl},
    "cpl": {"label": "CPL", "unit": "brl", "fmt": fmt.brl_cents},
    "cpc": {"label": "CPC", "unit": "brl", "fmt": fmt.brl_cents},
    "cpm": {"label": "CPM", "unit": "brl", "fmt": fmt.brl_cents},
    "leads": {"label": "Leads", "unit": "count", "fmt": fmt.integer},
    "cliques": {"label": "Cliques", "unit": "count", "fmt": fmt.integer},
    "impressoes": {"label": "Impressões", "unit": "count", "fmt": fmt.compact},
    "ctr": {"label": "CTR", "unit": "pct", "fmt": fmt.pct},
}

DEFAULT_PLOT = ["investimento", "leads"]


def _axis_formatter(unit: str):
    return {"brl": fmt.brl_compact, "pct": fmt.pct, "count": fmt.compact}[unit]


def custom_series(series: list[dict], keys: list[str], colors: dict[str, str]) -> dict:
    """
    Gráfico montado pelo cliente: ele escolhe as métricas e as cores.

    A regra de UM eixo continua valendo, e é ela que decide o modo:

    * **Mesma unidade** (só reais, ou só contagens) — valores absolutos, um
      eixo só, leitura direta.
    * **Unidades diferentes** (ex.: investimento e CTR) — tudo indexado em
      base 100 no primeiro dia. É a alternativa documentada ao segundo eixo:
      com duas escalas, duas curvas parecem se cruzar sem se cruzar, e a
      leitura fica errada. Indexado, o que se compara é o RITMO de variação.
    """
    keys = [key for key in keys if key in PLOTTABLE] or list(DEFAULT_PLOT)
    labels = _labels(series)
    units = {PLOTTABLE[key]["unit"] for key in keys}
    indexed = len(units) > 1

    datasets: list[dict] = []
    plotted: list[float] = []

    for position, key in enumerate(keys):
        spec = PLOTTABLE[key]
        raw = [_number(row.get(key)) for row in series]

        if indexed:
            base = next((value for value in raw if value), 0) or 1
            values = [value / base * 100 for value in raw]
        else:
            values = raw

        plotted.extend(values)
        datasets.append(
            {
                "label": spec["label"],
                "data": values,
                "color": colors.get(key) or series_color(
                    ["primary", "secondary", "tertiary", "neutral"][position % 4]
                ),
                # O tooltip mostra sempre o valor REAL, mesmo no modo indexado:
                # ninguém quer saber que algo está em "112 pontos de base".
                "display": [spec["fmt"](value) for value in raw],
            }
        )

    if indexed:
        y_axis = _y_axis(plotted, lambda tick: f"{int(tick)}")
    else:
        y_axis = _y_axis(plotted, _axis_formatter(units.pop()))

    return _spec("line", 268, labels, datasets, y=y_axis, indexed=indexed)


def cost_line(series: list[dict], key: str, color: str, label: str, height: int = 238) -> dict:
    """
    Série temporal de uma métrica de custo (CPL, CPC).

    Uma única linha, com marcador só no último ponto: o "agora" merece um
    ponto, o resto não.
    """
    values = [_number(row.get(key)) for row in series]
    return _spec(
        "line",
        height,
        _labels(series),
        [{
            "label": label,
            "data": values,
            "color": color,
            "display": [fmt.brl_cents(value) for value in values],
            "lastPoint": True,
        }],
        y=_y_axis(values, fmt.brl_cents),
    )


def cumulative_area(series: list[dict], key: str = "investimento") -> dict:
    """Acumulado do período — área única, wash de 10%."""
    running, values = 0.0, []
    for row in series:
        running += _number(row.get(key))
        values.append(running)

    return _spec(
        "line",
        214,
        _labels(series),
        [{
            "label": "Acumulado",
            "data": values,
            "color": series_color("primary"),
            "display": [fmt.brl(value) for value in values],
            "fill": True,
        }],
        y=_y_axis(values, fmt.brl_compact),
        xTicks=5,
    )


def daily_bars(series: list[dict], key: str, color: str, label: str) -> dict:
    """Coluna diária de uma métrica de contagem (conversões, leads)."""
    values = [_number(row.get(key)) for row in series]
    return _spec(
        "bar",
        214,
        _labels(series),
        [{
            "label": label,
            "data": values,
            "color": color,
            "display": [fmt.integer(value) for value in values],
        }],
        y=_y_axis(values, fmt.compact),
        xTicks=5,
    )


def channel_donut(channels: list[dict]) -> dict:
    """
    Distribuição por canal.

    Três cores de identidade + um cinza para "Outros". A rosca não tem rótulo
    interno: os nomes e valores ficam na legenda HTML ao lado, que aguenta
    texto sem apertar as fatias. No miolo, só o total.
    """
    values = [_number(channel["valor"]) for channel in channels]
    total = sum(values)
    return _spec(
        "doughnut",
        206,
        [channel["nome"] for channel in channels],
        [{
            "label": "Investimento",
            "data": values,
            "colors": [entity_color(channel["key"]) for channel in channels],
            "display": [
                f"{fmt.brl(value)} · {fmt.pct(value / total * 100 if total else 0, 1)}"
                for value in values
            ],
        }],
        center={"value": fmt.brl_compact(total), "label": "investido"},
    )


# --------------------------------------------------------------------------
# Funil — HTML, não canvas
# --------------------------------------------------------------------------

def funnel_stages(stages: list[dict]):
    """
    Funil desenhado em HTML.

    Escolha deliberada: a informação que importa no funil é a TAXA entre as
    etapas, e ela cabe melhor no espaço vazio entre as barras do que dentro
    de um trapézio. Cada etapa usa um degrau de uma rampa de matiz única
    tirada da cor do cliente, então a cor acompanha a ORDEM em vez de
    inventar uma identidade diferente por etapa.
    """
    nodes = []
    ramp = ordinal_ramp()

    for index, stage in enumerate(stages):
        width = max(stage["do_topo"], 6)

        nodes.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(stage["etapa"], className="funnel__name"),
                            html.Span(fmt.compact(stage["valor"]), className="funnel__value"),
                        ],
                        className="funnel__meta",
                    ),
                    html.Div(
                        className="funnel__bar",
                        style={
                            "width": f"{width}%",
                            "background": ramp[min(index, len(ramp) - 1)],
                        },
                        title=f'{stage["etapa"]}: {fmt.integer(stage["valor"])}',
                    ),
                ],
                className="funnel__stage",
            )
        )

        if index < len(stages) - 1:
            rate = stages[index + 1]["taxa"]
            nodes.append(
                html.Div(
                    [
                        html.Span(className="funnel__step-line"),
                        html.Span(f"{fmt.pct(rate, 1)} avançam"),
                    ],
                    className="funnel__step",
                )
            )

    return html.Div(nodes, className="funnel")


# --------------------------------------------------------------------------
# Card de gráfico
# --------------------------------------------------------------------------

def graph(spec: dict, graph_id: str = None):
    """
    Container do Chart.js: a especificação vai no atributo `data-chart`.

    A altura é fixada no container, e não deixada para o gráfico: o Chart.js
    responsivo mede o PAI, e um pai sem altura faz o canvas crescer a cada
    redimensionamento até empurrar o card de baixo.
    """
    props = {
        "className": "chart-wrap",
        "style": {"height": f"{spec.get('height') or 240}px"},
        "role": "img",
        "aria-label": ", ".join(item.get("label", "") for item in spec.get("datasets", [])),
        # `separators` compacto: o JSON vai inteiro para o HTML.
        "data-chart": json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
    }
    if graph_id:
        props["id"] = graph_id
    return html.Div(**props)


def chart_settings(keys: list[str], colors: dict[str, str]):
    """
    Painel de personalização do gráfico: quais métricas e de que cor.

    A cor fica ao lado da própria métrica, e não numa lista separada de
    cores — assim não existe o passo de "descobrir qual cor é de quem".
    """
    from ui.primitives import classes, color_input

    rows = []
    for position, (key, spec) in enumerate(PLOTTABLE.items()):
        selected = key in keys
        fallback = series_color(["primary", "secondary", "tertiary", "neutral"][position % 4])
        rows.append(
            html.Div(
                [
                    html.Button(
                        [
                            html.Span(className=classes("chart-pick__check",
                                                        "chart-pick__check--on" if selected else None)),
                            html.Span(spec["label"], className="chart-pick__label"),
                            html.Span(
                                {"brl": "R$", "count": "un.", "pct": "%"}[spec["unit"]],
                                className="chart-pick__unit",
                            ),
                        ],
                        id={"type": "chart-metric", "key": key},
                        n_clicks=0,
                        className=classes("chart-pick", "chart-pick--on" if selected else None),
                    ),
                    # Só a métrica marcada mostra a paleta: cor de série que
                    # não está no gráfico é ajuste sem efeito visível.
                    color_input(key, colors.get(key) or fallback, group="chart")
                    if selected
                    else None,
                ],
                className=classes("chart-pick__row", "chart-pick__row--on" if selected else None),
            )
        )

    units = {PLOTTABLE[key]["unit"] for key in keys if key in PLOTTABLE}
    return [
        html.Div("Métricas do gráfico", className="pop__label", style={"padding": "4px 6px"}),
        html.Div(rows, className="chart-pick__list"),
        html.P(
            "Métricas de unidades diferentes são comparadas em base 100 — "
            "dois eixos fariam curvas parecerem se cruzar sem se cruzarem."
            if len(units) > 1
            else "Mesma unidade: os valores aparecem absolutos.",
            className="t-micro",
            style={"padding": "10px 6px 2px", "lineHeight": "1.5"},
        ),
    ]


def chart_card(title, figure=None, subtitle=None, legend_items=None, body=None, className="", lead_icon=None):
    return card(
        [
            card_header(
                title,
                subtitle=subtitle,
                lead_icon=lead_icon,
                action=legend(legend_items) if legend_items else None,
            ),
            body if body is not None else graph(figure),
        ],
        className=className,
    )
