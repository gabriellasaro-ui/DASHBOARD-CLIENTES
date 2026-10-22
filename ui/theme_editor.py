"""
Editor da aparência do painel do cliente, usado no /admin.

Tudo que o administrador escolhe aqui aparece na prévia NA HORA, desenhada
com os mesmos tokens que o painel de verdade usa (`core.branding.style_variables`).
Ou seja: a prévia não é uma aproximação — se ela está legível, o painel está.

Os temas prontos só preenchem os campos de cor; dali, cada cor continua
ajustável. Contraste insuficiente aparece aqui como aviso e é recusado no
salvar (`core.tenant_theme.clean_theme`).
"""

from __future__ import annotations

from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate

from core.branding import brand_font_url, contrast_ratio, style_variables
from core.tenant_theme import (
    COLOR_KEYS,
    DEFAULT_THEME,
    FONTS,
    HEX_COLOR,
    MIN_TEXT_CONTRAST,
    PRESETS,
    RADII,
    parse_theme,
)
from ui.icons import icon
from ui.primitives import classes, color_input, field, form_section

# Formulários com o editor: os dois do /admin e a tela de aparência do cliente.
PREFIXES = ("admin-new", "admin-edit", "client-theme")

# Campo de cor de cada chave do tema (o id final é f"{prefix}-{sufixo}").
COLOR_FIELDS = {
    "text_color": ("text", "Cor do texto"),
    "background_color": ("background", "Cor de fundo"),
    "surface_color": ("surface", "Cor dos cards"),
    "sidebar_color": ("sidebar", "Cor do menu lateral"),
}


def _color_id(prefix: str, key: str) -> dict:
    return {"type": "color-value", "group": "tenant", "for": f"{prefix}-{COLOR_FIELDS[key][0]}"}


def _all_fonts_url() -> str:
    """Todas as fontes do catálogo, peso 400 e 600: a lista mostra cada uma nela mesma."""
    families = [family for _, _, family in FONTS.values() if family]
    query = "&".join(f"family={family.replace(' ', '+')}:wght@400;600" for family in families)
    return f"https://fonts.googleapis.com/css2?{query}&display=swap"


def _font_dropdown(component_id: str, value: str):
    return dcc.Dropdown(
        id=component_id,
        options=[
            # O nome de cada fonte escrito NELA: escolher fonte pelo nome é
            # adivinhar.
            {"label": html.Span(label, style={"fontFamily": stack}), "value": key, "search": label}
            for key, (label, stack, _) in FONTS.items()
        ],
        value=value,
        clearable=False,
        searchable=True,
        className="select",
    )


def appearance_section(prefix: str, theme_data, brand: dict):
    """A seção "Aparência do painel" do formulário do cliente."""
    theme = parse_theme(theme_data)

    controls = html.Div(
        [
            _group(
                "Temas prontos",
                "Um ponto de partida: preenche as cores, que continuam ajustáveis.",
                html.Div([_preset_button(prefix, key, preset) for key, preset in PRESETS.items()],
                         className="theme-presets"),
            ),
            _group(
                "Tipografia",
                None,
                html.Div(
                    [
                        field("Texto", _font_dropdown(f"{prefix}-font-body", theme["font_body"])),
                        field("Títulos", _font_dropdown(f"{prefix}-font-heading", theme["font_heading"])),
                    ],
                    className="form-grid form-grid--2",
                ),
            ),
            _group(
                "Cores",
                "Tons de texto, bordas e sombras saem destas quatro.",
                html.Div(
                    [
                        field(label, color_input(f"{prefix}-{suffix}", theme[key], group="tenant"))
                        for key, (suffix, label) in COLOR_FIELDS.items()
                    ],
                    className="form-grid form-grid--2",
                ),
            ),
            _group(
                "Cantos",
                None,
                dcc.RadioItems(
                    id=f"{prefix}-radius",
                    options=[
                        {"label": html.Span([html.Span(className=f"radius-sample radius-sample--{key}"), label],
                                            className="radius-option"),
                         "value": key}
                        for key, (label, *_rest) in RADII.items()
                    ],
                    value=theme["radius"],
                    className="radio-group",
                    labelClassName="radio-option",
                    inputClassName="radio-option__input",
                ),
            ),
        ],
        className="appearance__controls",
    )

    preview = html.Div(
        [
            html.Div("Prévia ao vivo", className="appearance__title"),
            # A logo já salva acompanha a prévia; uma logo nova enviada agora
            # entra no lugar dela (ver `_preview`).
            dcc.Store(id=f"{prefix}-theme-logo", data=brand.get("logo_data")),
            html.Div(theme_preview(theme, brand), id=f"{prefix}-theme-preview"),
            html.Div(_check(theme), id=f"{prefix}-theme-check"),
        ],
        className="appearance__preview",
    )

    return form_section(
        "Aparência do painel",
        [
            html.Link(rel="stylesheet", href=_all_fonts_url()),
            # Controles à esquerda, prévia à direita e FIXA na rolagem: cada
            # ajuste aparece ao lado de onde se mexe, sem rolar até o fim.
            html.Div([controls, preview], className="appearance"),
        ],
        hint="Fonte, cores e cantos do painel deste cliente. Vale também para a tela de login dele.",
    )


def _group(title: str, hint: str | None, body):
    return html.Div(
        [
            html.Div(
                [html.Div(title, className="appearance__title"),
                 html.Span(hint, className="appearance__hint") if hint else None],
                className="appearance__group-head",
            ),
            body,
        ],
        className="appearance__group",
    )


def _preset_button(prefix: str, key: str, preset: dict):
    """Miniatura do painel no tema: menu, fundo e um card, como ele vai ficar."""
    return html.Button(
        [
            html.Span(
                [
                    html.Span(className="theme-preset__menu", style={"background": preset["sidebar_color"]}),
                    html.Span(
                        [
                            html.Span(className="theme-preset__line",
                                      style={"background": preset["text_color"]}),
                            html.Span(className="theme-preset__card",
                                      style={"background": preset["surface_color"]}),
                        ],
                        className="theme-preset__page",
                        style={"background": preset["background_color"]},
                    ),
                ],
                className="theme-preset__thumb",
            ),
            html.Span(preset["label"], className="theme-preset__label"),
        ],
        id={"type": "theme-preset", "mode": prefix, "key": key},
        n_clicks=0,
        type="button",
        className="theme-preset",
        title=f"Aplicar o tema {preset['label']}",
    )


# --------------------------------------------------------------------------
# Prévia
# --------------------------------------------------------------------------

def theme_preview(theme: dict, brand: dict):
    """
    Miniatura do painel com o tema aplicado: menu, topo, dois KPIs e um card
    de gráfico. Usa as mesmas variáveis do painel real no container.
    """
    brand = {**brand, "theme": theme}
    name = brand.get("name") or "Cliente"
    logo = brand.get("logo_data")
    bars = [38, 62, 48, 80, 56, 92, 70]

    return html.Div(
        [
            html.Link(rel="stylesheet", href=brand_font_url(brand)) if brand_font_url(brand) else None,
            html.Div(
                [
                    html.Img(src=logo, className="theme-preview__logo") if logo
                    else html.Span(name[:1].upper(), className="theme-preview__mark"),
                    *[
                        html.Span(
                            [icon(glyph, 15)],
                            className=classes("theme-preview__nav", "theme-preview__nav--active" if active else None),
                        )
                        for glyph, active in (("layout-dashboard", True), ("wallet", False), ("magnet", False))
                    ],
                ],
                className="theme-preview__sidebar",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Strong(name, className="theme-preview__title"),
                                    html.Span("Visão geral · últimos 30 dias", className="theme-preview__muted"),
                                ]
                            ),
                            html.Span("Atualizar", className="btn btn--primary btn--sm"),
                        ],
                        className="theme-preview__top",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(label, className="theme-preview__muted"),
                                    html.Strong(value, className="theme-preview__value"),
                                    html.Span(delta, className="theme-preview__delta"),
                                ],
                                className="card theme-preview__kpi",
                            )
                            for label, value, delta in (
                                ("Investimento", "R$ 6.564", "▲ 12,4%"),
                                ("Leads", "39", "▲ 8,1%"),
                            )
                        ],
                        className="theme-preview__kpis",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Strong("Desempenho", className="theme-preview__card-title"),
                                    html.Span("Investimento por dia", className="theme-preview__muted"),
                                ]
                            ),
                            html.Div(
                                [html.Span(style={"height": f"{height}%"}) for height in bars],
                                className="theme-preview__bars",
                            ),
                        ],
                        className="card theme-preview__chart",
                    ),
                ],
                className="theme-preview__main",
            ),
        ],
        className="theme-preview",
        style=style_variables(brand),
    )


def _check(theme: dict, invalid: list[str] | None = None):
    """Aviso de legibilidade, com o número — o mesmo critério do salvar."""
    if invalid:
        return html.Div(
            [icon("alert-triangle", 16),
             html.Span(f"Cor incompleta em: {', '.join(invalid)}. Use o formato #RRGGBB.")],
            className="theme-check theme-check--bad",
        )
    worst = min(
        (contrast_ratio(theme["text_color"], theme[key]), where)
        for key, where in (("background_color", "o fundo"), ("surface_color", "os cards"))
    )
    ratio, where = worst
    if ratio < MIN_TEXT_CONTRAST:
        return html.Div(
            [icon("alert-triangle", 16),
             html.Span(f"Texto pouco legível sobre {where}: {ratio:.1f}:1 (mínimo {MIN_TEXT_CONTRAST:.1f}:1). "
                       "Não dá para salvar assim.")],
            className="theme-check theme-check--bad",
        )
    return html.Div(
        [icon("check", 16), html.Span(f"Leitura confortável: contraste mínimo de {ratio:.1f}:1.")],
        className="theme-check",
    )


def theme_from_form(font_body, font_heading, radius, colors: dict) -> dict:
    """Junta os campos do formulário num tema (sem validar — isso é do salvar)."""
    return {
        "font_body": font_body or DEFAULT_THEME["font_body"],
        "font_heading": font_heading or DEFAULT_THEME["font_heading"],
        "radius": radius or DEFAULT_THEME["radius"],
        **{key: (colors.get(key) or "").strip().upper() for key in COLOR_KEYS},
    }


def theme_states(prefix: str) -> list[State]:
    """Os States que um callback precisa para ler o tema do formulário."""
    return [
        State(f"{prefix}-font-body", "value"),
        State(f"{prefix}-font-heading", "value"),
        State(f"{prefix}-radius", "value"),
        *[State(_color_id(prefix, key), "value") for key in COLOR_KEYS],
    ]


def theme_from_states(values: list) -> dict:
    font_body, font_heading, radius, *colors = values
    return theme_from_form(font_body, font_heading, radius, dict(zip(COLOR_KEYS, colors)))


# --------------------------------------------------------------------------
# Callbacks — uma por formulário (criar e editar nunca estão na tela juntos)
# --------------------------------------------------------------------------

def _register(prefix: str) -> None:
    @callback(
        *[Output(_color_id(prefix, key), "value", allow_duplicate=True) for key in COLOR_KEYS],
        Input({"type": "theme-preset", "mode": prefix, "key": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _apply_preset(_clicks):
        # Os botões disparam ao NASCER (n_clicks 0); só clique de verdade vale.
        if not (ctx.triggered and ctx.triggered[0].get("value")):
            raise PreventUpdate
        preset = PRESETS.get(ctx.triggered_id.get("key"))
        if not preset:
            raise PreventUpdate
        return tuple(preset[key] for key in COLOR_KEYS)

    @callback(
        Output(f"{prefix}-theme-preview", "children"),
        Output(f"{prefix}-theme-check", "children"),
        Input(f"{prefix}-font-body", "value"),
        Input(f"{prefix}-font-heading", "value"),
        Input(f"{prefix}-radius", "value"),
        *[Input(_color_id(prefix, key), "value") for key in COLOR_KEYS],
        Input({"type": "color-value", "group": "tenant", "for": f"{prefix}-primary"}, "value"),
        Input({"type": "color-value", "group": "tenant", "for": f"{prefix}-secondary"}, "value"),
        Input(f"{prefix}-logo", "contents"),
        State(f"{prefix}-name", "value"),
        State(f"{prefix}-theme-logo", "data"),
        prevent_initial_call=True,
    )
    def _preview(font_body, font_heading, radius, *rest):
        *colors, primary, secondary, new_logo, name, saved_logo = rest
        raw = theme_from_form(font_body, font_heading, radius, dict(zip(COLOR_KEYS, colors)))
        invalid = [COLOR_FIELDS[key][1].lower() for key in COLOR_KEYS if not HEX_COLOR.fullmatch(raw[key])]
        theme = parse_theme(raw)
        brand = {
            "name": name or "Cliente",
            "logo_data": new_logo if (new_logo or "").startswith("data:image/") else saved_logo,
            "primary_color": primary if HEX_COLOR.fullmatch((primary or "").strip()) else None,
            "secondary_color": secondary if HEX_COLOR.fullmatch((secondary or "").strip()) else None,
        }
        return theme_preview(theme, brand), _check(theme, invalid)


for _prefix in PREFIXES:
    _register(_prefix)
