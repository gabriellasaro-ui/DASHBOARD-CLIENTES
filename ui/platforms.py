"""
Marcas das plataformas de mídia.

As logos vêm dos PNGs oficiais na raiz do projeto, embutidos como data-URI:
assim não dependem de rota estática, não somem se a pasta de assets mudar e
não fazem uma requisição extra por linha de tabela.

São logos de terceiros — não recebem a cor do cliente nem a tinta do tema.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

from dash import html

BASE_DIR = Path(__file__).resolve().parent.parent

LOGO_FILES = {
    "meta": BASE_DIR / "meta ads.png",
    "google": BASE_DIR / "google ads.png",
}

LABELS = {"meta": "Meta Ads", "google": "Google Ads"}


@lru_cache(maxsize=4)
def logo_data(platform: str) -> str | None:
    path = LOGO_FILES.get(platform)
    if not path or not path.exists():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def platform_mark(platform: str, size: int = 20):
    """Logo da plataforma. Sem o arquivo, cai na inicial para não sumir."""
    source = logo_data(platform)
    label = LABELS.get(platform, platform)

    if source:
        return html.Img(
            src=source,
            alt="",
            title=label,
            className=f"platform-mark platform-mark--{platform}",
            style={"width": f"{size}px", "height": f"{size}px"},
            **{"aria-hidden": "true"},
        )

    return html.Span(
        label[:1].upper(),
        className=f"platform-mark platform-mark--{platform} platform-mark--fallback",
        style={"width": f"{size}px", "height": f"{size}px"},
        title=label,
    )
