"""
Stat tiles — os cards de KPI.

Contrato de cada card: rótulo · valor · variação assinada contra um período
nomeado · sparkline de 12 pontos. Compactos de propósito: são 20 métricas e
o cliente precisa ver todas sem rolar.

A sparkline é gerada como SVG em Python e aplicada como `background-image`.
Vinte gráficos de verdade dentro de vinte cards custaria caro para desenhar
uma informação que é, aqui, só "o formato da curva".
"""

from __future__ import annotations

from urllib.parse import quote

from dash import html

from core import fmt
from core.theme import series_color, surface_color
from ui.icons import icon
from ui.primitives import card, classes

SPARK_W = 78
SPARK_H = 24


def _sparkline_uri(points: list[float]) -> str | None:
    """Sparkline como data-URI: traço rebaixado + ponto final destacado."""
    if not points or len(points) < 2:
        return None

    lowest, highest = min(points), max(points)
    span = (highest - lowest) or 1
    step = SPARK_W / (len(points) - 1)
    pad = 3

    coords = [
        (i * step, SPARK_H - pad - ((value - lowest) / span) * (SPARK_H - pad * 2))
        for i, value in enumerate(points)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"{line} {SPARK_W},{SPARK_H} 0,{SPARK_H}"
    end_x, end_y = coords[-1]
    accent = series_color("primary")   # segue a cor do cliente

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SPARK_W}" height="{SPARK_H}" '
        f'viewBox="0 0 {SPARK_W} {SPARK_H}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{accent}" stop-opacity="0.14"/>'
        f'<stop offset="100%" stop-color="{accent}" stop-opacity="0"/>'
        f"</linearGradient></defs>"
        f'<polygon points="{area}" fill="url(#g)"/>'
        f'<polyline points="{line}" fill="none" stroke="{accent}" '
        f'stroke-opacity="0.6" stroke-width="1.5" stroke-linecap="round" '
        f'stroke-linejoin="round"/>'
        # anel na cor da superfície para o ponto final não se fundir à linha
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="3.4" fill="{surface_color()}"/>'
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="2.2" fill="{accent}"/>'
        f"</svg>"
    )

    return f'url("data:image/svg+xml,{quote(svg, safe="")}")'


def _delta_tone(variation: float, good: str) -> str:
    """
    Traduz a variação em tom.

    Métrica de custo que sobe é ruim, mesmo o número tendo crescido — é o erro
    de leitura mais comum em dashboard de mídia, então o card resolve isso.
    Investimento não tem direção "boa": fica em cinza, sem julgamento.
    """
    if good == "neutral" or abs(variation) < 0.05:
        return "flat"
    rising_is_good = good == "up"
    return "positive" if (variation > 0) == rising_is_good else "negative"


def kpi_card(metric: dict, compare_label: str = "período anterior"):
    variation = metric.get("variation", 0.0)
    tone = _delta_tone(variation, metric.get("good", "up"))
    arrow = "arrow-up-right" if variation > 0 else ("arrow-down-right" if variation < 0 else "arrow-right")
    spark = _sparkline_uri(metric.get("spark") or [])

    return card(
        [
            html.Div(
                [
                    html.Span(metric["label"], className="kpi__label", title=metric["label"]),
                    icon(metric["icon"], 20, className="kpi__icon"),
                ],
                className="kpi__top",
            ),
            html.Div(fmt.by_type(metric["type"], metric["value"]), className="kpi__value"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                [icon(arrow, 12), html.Span(fmt.delta(variation))],
                                className=classes("kpi__delta", f"kpi__delta--{tone}"),
                            ),
                            html.Span(f"vs. {compare_label}", className="kpi__compare"),
                        ],
                        className="col gap-1",
                        style={"minWidth": "0"},
                    ),
                    html.Div(
                        className="kpi__spark",
                        style={
                            "width": f"{SPARK_W}px",
                            "height": f"{SPARK_H}px",
                            "backgroundImage": spark,
                            "backgroundRepeat": "no-repeat",
                        },
                    )
                    if spark
                    else None,
                ],
                className="kpi__foot",
            ),
        ],
        # o hover do KPI é próprio (scale), não o do card genérico (translate),
        # para os dois não brigarem pela mesma propriedade transform
        className="kpi",
    )


def kpi_grid(metrics: list[dict], compare_label: str = "período anterior"):
    return html.Div(
        [kpi_card(metric, compare_label) for metric in metrics],
        className="kpi-grid",
    )
