"""Card ampliado de criativo com as métricas reais do anúncio selecionado."""

from __future__ import annotations

from dash import html

from core import fmt
from core.data import STATUS_LABEL
from ui.icons import icon
from ui.primitives import badge


METRICS = (
    ("investimento", "Investimento", "currency"),
    ("leads", "Resultados", "int"),
    ("cpl", "CPL", "currency_cents"),
    ("cliques", "Cliques", "compact"),
    ("ctr", "CTR", "percent"),
    ("impressoes", "Impressões", "compact"),
    ("cpc", "CPC", "currency_cents"),
    ("cpm", "CPM", "currency_cents"),
)


def preview_card(ad: dict):
    status = STATUS_LABEL.get(ad.get("status"), {"label": "Indisponível", "tone": "neutral"})
    image_url = ad.get("creative_url")
    media = (
        html.Img(
            src=image_url,
            alt=f"Criativo ampliado do anúncio {ad.get('nome', '')}",
            className="ad-preview__image",
        )
        if image_url
        else html.Div(
            [icon("eye-off", 34), html.Span("Imagem do criativo indisponível")],
            className="ad-preview__empty",
        )
    )

    return html.Div(
        [
            html.Div(media, className="ad-preview__media"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span("DETALHES DO ANÚNCIO", className="eyebrow"),
                                    html.H2(ad.get("nome") or "Anúncio sem nome", className="ad-preview__title"),
                                ]
                            ),
                            badge(status["label"], status["tone"], dot=True),
                        ],
                        className="ad-preview__head",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [html.Span("Campanha", className="t-micro"), html.Strong(ad.get("campanha") or "—")],
                                className="ad-preview__context-item",
                            ),
                            html.Div(
                                [html.Span("Conjunto", className="t-micro"), html.Strong(ad.get("conjunto") or "—")],
                                className="ad-preview__context-item",
                            ),
                        ],
                        className="ad-preview__context",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(label, className="ad-preview__metric-label"),
                                    html.Strong(fmt.by_type(kind, ad.get(key, 0)), className="ad-preview__metric-value"),
                                ],
                                className="ad-preview__metric",
                            )
                            for key, label, kind in METRICS
                        ],
                        className="ad-preview__metrics",
                    ),
                    html.A(
                        [icon("external-link", 18), html.Span("Abrir imagem original")],
                        href=image_url,
                        target="_blank",
                        rel="noopener noreferrer",
                        className="btn btn--secondary ad-preview__original",
                    )
                    if image_url
                    else None,
                ],
                className="ad-preview__details",
            ),
        ],
        className="ad-preview__grid",
    )
