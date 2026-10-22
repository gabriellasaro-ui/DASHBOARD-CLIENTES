"""
Tema dos gráficos — o mesmo design system dos tokens CSS, em Python.

As cores das séries NÃO são fixas: elas são derivadas da cor do cliente
ativo (ver `core/branding.py`), então trocar a cor no admin repinta gráfico,
sparkline e funil, não só o botão.

As séries são nomeadas por PAPEL (`primary`, `secondary`, `tertiary`) e não
por cor. Chamar de "azul" o que hoje pode ser roxo, verde ou laranja seria
mentir no nome da variável — e foi exatamente o que travou o whitelabel.

O que a cor do cliente não governa, de propósito:

* **Verde e vermelho de status.** Se a marca é verde, "caiu 8%" não pode
  aparecer em verde.
* **A grade e os eixos.** São cinza recessivo em qualquer marca; grade
  colorida disputa atenção com o dado.
"""

from __future__ import annotations

from core.branding import DEFAULT_PRIMARY, DEFAULT_SECONDARY, brand_palette
from core.tenant_theme import DEFAULT_THEME, parse_theme

DEFAULT_SURFACE = DEFAULT_THEME["surface_color"]

# --------------------------------------------------------------------------
# Cores que não dependem da marca
# --------------------------------------------------------------------------

STATUS = {
    "positive": "#16A34A",
    "negative": "#E5001A",
    "warning": "#B45309",
}

INK = {
    "primary": "#0B0B0D",
    "secondary": "#52565E",
    "muted": "#767B84",
    "faint": "#9AA0A9",
}

CHROME = {
    "grid": "#EEF0F2",
    "axis": "#E6E7EA",
    "surface": "#FFFFFF",
    "spike": "#C4C8CE",
}

FONT = "Inter, system-ui, -apple-system, Segoe UI, sans-serif"

# Entidade → papel na paleta. A cor segue a ENTIDADE, nunca a posição no
# ranking: se um filtro tira uma campanha, as demais não trocam de cor.
ENTITY_ROLE = {
    "investimento": "primary",
    "cpl": "primary",
    "meta": "primary",
    "receita": "secondary",
    "leads": "secondary",
    "organico": "secondary",
    "cliques": "tertiary",
    "google": "tertiary",
    "outros": "neutral",
}


# --------------------------------------------------------------------------
# Paleta do cliente ativo
# --------------------------------------------------------------------------

_REQUEST_CACHE_KEY = "_pulse_brand_colors"


def _active_brand_colors() -> tuple[str, str, str]:
    """
    Cores do cliente em contexto. Fora de um request (import, script, teste)
    devolve o padrão em vez de estourar — desenhar um gráfico não pode
    depender de haver alguém logado.

    O resultado é memorizado NO REQUEST (`flask.g`). Sem isso cada chamada
    de `series_color`/`entity_color` reabria a sessão e o tenant no banco —
    uma célula de tabela por vez, 124 conexões e 10 segundos para montar a
    tela do Meta. A marca não muda no meio de uma requisição, então uma
    resolução por requisição basta.
    """
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SURFACE

        cached = getattr(g, _REQUEST_CACHE_KEY, None)
        if cached is not None:
            return cached

        colors = _resolve_brand_colors()
        setattr(g, _REQUEST_CACHE_KEY, colors)
        return colors
    except Exception:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SURFACE


def _surface(record: dict | None) -> str:
    """Cor dos cards do cliente: é sobre ela que as séries precisam aparecer."""
    return parse_theme((record or {}).get("theme_data"))["surface_color"]


def _resolve_brand_colors() -> tuple[str, str, str]:
    try:
        from core.auth import active_tenant, current_user, is_superadmin

        user = current_user()
        if not user:
            return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SURFACE
        if is_superadmin(user):
            # O master vê os dados do cliente selecionado, então os gráficos
            # usam a cor DESSE cliente — é o que ele mostra na reunião.
            tenant = active_tenant(user)
            if tenant:
                return (
                    tenant.get("primary_color") or DEFAULT_PRIMARY,
                    tenant.get("secondary_color") or DEFAULT_SECONDARY,
                    _surface(tenant),
                )
            return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SURFACE
        return (
            user.get("primary_color") or DEFAULT_PRIMARY,
            user.get("secondary_color") or DEFAULT_SECONDARY,
            _surface(user),
        )
    except Exception:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SURFACE


def palette() -> dict:
    """Paleta de gráfico do cliente ativo, por papel."""
    primary, secondary, surface = _active_brand_colors()
    resolved = brand_palette(primary, secondary, surface)
    series = resolved["series"]
    return {
        "primary": series[0],
        "secondary": series[1],
        "tertiary": series[2],
        "neutral": series[3],
        "ordinal": resolved["ordinal"],
    }


def series_color(role: str) -> str:
    """Cor de um papel de série (`primary`, `secondary`, `tertiary`, `neutral`)."""
    return palette().get(role, palette()["primary"])


def entity_color(key: str | None) -> str:
    """Cor de uma entidade nomeada (investimento, receita, meta, google…)."""
    return series_color(ENTITY_ROLE.get(key or "", "neutral"))


def ordinal_ramp() -> list[str]:
    """Rampa de matiz única do funil, na cor do cliente."""
    return palette()["ordinal"]


def surface_color() -> str:
    """Cor dos cards do cliente ativo (o anel da sparkline usa ela)."""
    return _active_brand_colors()[2]
