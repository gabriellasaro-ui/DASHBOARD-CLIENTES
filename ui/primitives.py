"""
Primitivos do design system.

Card, badge, botão, campo, avatar, skeleton, estados vazios — o vocabulário
que todas as telas reusam. Se um elemento aparece em duas páginas, ele mora
aqui; nenhuma página inventa a própria versão de um botão.
"""

from __future__ import annotations

import re

import dash
import dash_daq as daq
from dash import Input, MATCH, Output, State, callback, ctx, dcc, html

from ui.icons import icon

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def classes(*parts) -> str:
    """Junta classes ignorando None/False — evita ' ' sobrando no HTML."""
    return " ".join(str(p) for p in parts if p)


# --------------------------------------------------------------------------
# Card
# --------------------------------------------------------------------------

def card(children, className: str = "", interactive: bool = False, **kwargs):
    return html.Section(
        children,
        className=classes("card", "card--interactive" if interactive else None, className),
        **kwargs,
    )


def card_header(title, subtitle=None, action=None, lead_icon=None, className=""):
    return html.Header(
        [
            html.Div(
                [
                    html.Div(
                        [icon(lead_icon, 18) if lead_icon else None, html.Span(title)],
                        className="card__title",
                    ),
                    html.P(subtitle, className="card__subtitle") if subtitle else None,
                ],
                className="card__title-wrap",
            ),
            html.Div(action, style={"flex": "none"}) if action is not None else None,
        ],
        className=classes("card__header", className),
    )


def card_body(children, className="", flush=False):
    return html.Div(
        children,
        className=classes("card__body", "card__body--flush" if flush else None, className),
    )


# --------------------------------------------------------------------------
# Badge
# --------------------------------------------------------------------------

def badge(label, tone: str = "neutral", dot: bool = False, lead_icon=None, className=""):
    """A cor nunca fica sozinha: sempre acompanha rótulo e, se for estado, ponto."""
    return html.Span(
        [
            html.Span(className="badge__dot") if dot else None,
            icon(lead_icon, 11) if lead_icon else None,
            html.Span(label),
        ],
        className=classes("badge", f"badge--{tone}", className),
    )


def status_badge(status: str, mapping: dict):
    config = mapping.get(status, {"label": status, "tone": "neutral"})
    return badge(config["label"], config["tone"], dot=True)


# --------------------------------------------------------------------------
# Botão
# --------------------------------------------------------------------------

def button(
    label=None,
    variant: str = "secondary",
    size: str = "md",
    lead_icon=None,
    trail_icon=None,
    className="",
    **kwargs,
):
    size_class = {"sm": "btn--sm", "lg": "btn--lg", "icon": "btn--icon"}.get(size)
    icon_size = 19 if size == "lg" else 17

    return html.Button(
        [
            icon(lead_icon, icon_size) if lead_icon else None,
            html.Span(label) if label else None,
            icon(trail_icon, icon_size, style={"opacity": "0.7"}) if trail_icon else None,
        ],
        className=classes("btn", f"btn--{variant}", size_class, className),
        **kwargs,
    )


def link_button(label, href, variant="secondary", size="md", lead_icon=None, className="", **kwargs):
    size_class = {"sm": "btn--sm", "lg": "btn--lg", "icon": "btn--icon"}.get(size)
    return dcc.Link(
        [icon(lead_icon, 17) if lead_icon else None, html.Span(label) if label else None],
        href=href,
        className=classes("btn", f"btn--{variant}", size_class, className),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Campos
# --------------------------------------------------------------------------

def form_section(title, children, hint=None, first=False):
    """
    Bloco de formulário com título próprio.

    Substitui o improviso anterior — um rótulo minúsculo em caixa alta, uma
    linha de popover reaproveitada como divisória e margens escritas à mão em
    cada lugar. Como componente, o espaçamento entre blocos é sempre o mesmo e
    o título tem peso de verdade, então o olho encontra as seções.
    """
    return html.Section(
        [
            html.Div(
                [
                    html.H3(title, className="form-section__title"),
                    html.P(hint, className="form-section__hint") if hint else None,
                ],
                className="form-section__head",
            ),
            html.Div(children, className="form-section__body"),
        ],
        className=classes("form-section", "form-section--first" if first else None),
    )


def field(label=None, control=None, hint=None, className=""):
    return html.Div(
        [
            html.Label(label, className="field__label") if label else None,
            control,
            html.P(hint, className="field__hint") if hint else None,
        ],
        className=classes("field", className),
    )


def text_input(placeholder="", lead_icon=None, input_type="text", className="", **kwargs):
    return html.Div(
        [
            icon(lead_icon, 18, className="field__icon") if lead_icon else None,
            dcc.Input(
                type=input_type,
                placeholder=placeholder,
                className=classes("input", "input--with-icon" if lead_icon else None, className),
                debounce=False,
                **kwargs,
            ),
        ],
        className="field__wrap",
    )


def color_input(field_id: str, value: str = "#E5001A", group: str = "form", **kwargs):
    """
    Seletor de cor: amostra que abre um picker completo + hexadecimal digitável.

    O picker é o `dash_daq.ColorPicker` — o Dash não expõe `<input
    type="color">` (o `dcc.Input` recusa o tipo `color` e o módulo `html` não
    traz `Input`), então o mapa de cores nativo do sistema está fora de
    alcance. O daq entrega o mesmo: espectro contínuo, qualquer cor.

    Ele fica dentro de um popover porque tem ~220px de altura: aberto direto
    no formulário, dois campos de cor tomariam metade da tela.

    O campo de hexadecimal continua ao lado — colar um valor de marca é mais
    rápido do que perseguir o tom no espectro, e é ele que guarda o valor.

    `group` separa usos que não podem se confundir. Sem ele, uma callback que
    escuta `{"type": "color-value", "for": ALL}` numa tela casava também com
    os campos de cor de OUTRA tela, ficava elegível lá e quebrava procurando
    componentes que só existem na tela de origem.
    """
    anchor = {"group": group, "for": field_id}
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "",
                        id={"type": "color-open", **anchor},
                        n_clicks=0,
                        className="color-field__swatch",
                        style={"background": value},
                        title="Escolher cor",
                        **{"aria-label": "Escolher cor"},
                    ),
                    dcc.Input(
                        type="text",
                        value=value,
                        id={"type": "color-value", **anchor},
                        className="input input--sm color-field__hex tabular",
                        maxLength=7,
                        spellCheck=False,
                        **kwargs,
                    ),
                ],
                className="color-field__head",
            ),
            html.Div(id={"type": "color-scrim", **anchor}, n_clicks=0, className="scrim hide"),
            html.Div(
                daq.ColorPicker(
                    id={"type": "color-picker", **anchor},
                    value={"hex": value},
                    size=228,
                ),
                id={"type": "color-pop", **anchor},
                className="pop color-field__pop hide",
            ),
        ],
        className="color-field",
    )


@callback(
    Output({"type": "color-pop", "group": MATCH, "for": MATCH}, "className"),
    Output({"type": "color-scrim", "group": MATCH, "for": MATCH}, "className"),
    Input({"type": "color-open", "group": MATCH, "for": MATCH}, "n_clicks"),
    Input({"type": "color-scrim", "group": MATCH, "for": MATCH}, "n_clicks"),
    State({"type": "color-pop", "group": MATCH, "for": MATCH}, "className"),
    prevent_initial_call=True,
)
def _toggle_color_picker(open_clicks, _scrim, pop_class):
    opening = "hide" in (pop_class or "") and ctx.triggered_id.get("type") == "color-open"
    return (
        classes("pop", "color-field__pop", None if opening else "hide"),
        classes("scrim", None if opening else "hide"),
    )


@callback(
    Output({"type": "color-value", "group": MATCH, "for": MATCH}, "value"),
    Input({"type": "color-picker", "group": MATCH, "for": MATCH}, "value"),
    prevent_initial_call=True,
)
def _picker_to_hex(picked):
    """
    O picker escreve no campo de hexadecimal, e não o contrário.

    Fluxo em mão única de propósito: sincronizar os dois lados criaria um
    ciclo (picker escreve no campo, campo reposiciona o picker, que escreve
    de novo). O campo é a fonte da verdade; o picker é uma forma de preenchê-lo.
    """
    hex_value = (picked or {}).get("hex")
    return hex_value.upper() if hex_value else dash.no_update


@callback(
    Output({"type": "color-open", "group": MATCH, "for": MATCH}, "style"),
    Input({"type": "color-value", "group": MATCH, "for": MATCH}, "value"),
)
def _preview_color(value):
    """Amostra acompanha o que está escrito, inclusive digitado à mão."""
    value = (value or "").strip()
    if not HEX_COLOR.fullmatch(value):
        return {"background": "repeating-linear-gradient(45deg,#EEE 0 6px,#FFF 6px 12px)"}
    return {"background": value}


def checkbox(label, checked=False, **kwargs):
    """
    Checkbox de uma opção só.

    Usa `dcc.Checklist` em vez de um `<input>` cru porque assim o estado é
    real (clicável, acessível, legível por callback) — o CSS em
    20-components.css substitui o visual padrão inteiro.
    """
    return dcc.Checklist(
        options=[{"label": label, "value": "on"}],
        value=["on"] if checked else [],
        className="checkbox-group",
        labelClassName="checkbox",
        inputClassName="checkbox__box",
        **kwargs,
    )


# --------------------------------------------------------------------------
# Avatar e marca
# --------------------------------------------------------------------------

def avatar(initials: str, size: str = "md", className=""):
    return html.Span(initials, className=classes("avatar", f"avatar--{size}", className))


def logo(with_text: bool = True, brand_name: str = "V4 Company", logo_data: str | None = None):
    mark = (
        html.Img(src=logo_data, alt=f"Logo {brand_name}", className="logo__image")
        if logo_data
        else html.Span(icon("activity", 17), className="logo__mark")
    )
    return html.Div(
        [
            mark,
            html.Span(
                [
                    html.Span(brand_name, className="logo__name"),
                    html.Span("PERFORMANCE", className="logo__sub"),
                ],
                className="logo__text",
            )
            if with_text
            else None,
        ],
        className="logo",
    )


# --------------------------------------------------------------------------
# Tooltip
# --------------------------------------------------------------------------

def tooltip(children, label: str, align: str = "center"):
    return html.Span(
        [children, html.Span(label, className="tt__bubble", role="tooltip")],
        className=classes("tt", "tt--right" if align == "right" else None),
    )


def hint(label: str):
    """Ponto de interrogação com tooltip — para métricas menos óbvias."""
    return tooltip(html.Button("?", className="hint-dot", **{"aria-label": label}), label)


# --------------------------------------------------------------------------
# Estados
# --------------------------------------------------------------------------

def no_delivery_state(platform: str, last_delivery: str | None = None):
    """
    A conta está ligada, mas não veiculou nada no período.

    É diferente de "deu erro" e de "não tem conta vinculada", e precisa
    aparecer como tal: uma tela em branco com os KPIs zerados leva a concluir
    que a integração quebrou, quando o que houve foi a campanha parar. Por
    isso o estado diz também QUANDO foi a última entrega — é o que responde
    "então nunca teve dado?" sem ninguém precisar abrir a plataforma.
    """
    from core import fmt

    if last_delivery:
        detalhe = (
            f"A última veiculação registrada nesta conta foi em "
            f"{fmt.long_date(last_delivery)}. Aumente o período ou verifique "
            f"se as campanhas estão ativas na plataforma."
        )
    else:
        detalhe = (
            "Ainda não há nenhuma veiculação registrada nesta conta. "
            "Se as campanhas acabaram de subir, os dados aparecem na próxima "
            "sincronização."
        )

    return card(
        empty_state(
            title=f"Sem veiculação no {platform} neste período",
            description=detalhe,
            glyph="pause",
        ),
        className="anim-up",
    )


def empty_state(title="Nenhum resultado", description=None, action=None, glyph="search-x"):
    """Um estado vazio sempre diz o que houve E qual é a próxima ação."""
    return html.Div(
        [
            html.Div(icon(glyph, 22), className="state__icon"),
            html.P(title, className="state__title"),
            html.P(description, className="state__desc") if description else None,
            html.Div(action, className="state__action") if action else None,
        ],
        className="state",
    )


# --------------------------------------------------------------------------
# Navegação secundária
# --------------------------------------------------------------------------

def breadcrumb(items):
    """items: [(rótulo, href|None)] — o último é sempre a página atual."""
    nodes = []
    last = len(items) - 1

    for index, (label, href) in enumerate(items):
        if index == last or not href:
            nodes.append(html.Span(label, className="crumbs__current" if index == last else None))
        else:
            nodes.append(dcc.Link(label, href=href, className="crumbs__link"))
        if index != last:
            nodes.append(icon("chevron-right", 12, className="crumbs__sep"))

    return html.Nav(nodes, className="crumbs", **{"aria-label": "Trilha de navegação"})


def segmented(options, value, id_type: str, group: str):
    """
    Controle segmentado. Cada opção é um botão com id de padrão
    {"type": id_type, "group": group, "value": ...} — assim uma única
    callback com pattern matching atende todos os grupos da tela.
    """
    return html.Div(
        [
            html.Button(
                [
                    html.Span(opt["label"]),
                    html.Span(opt["count"], className="segmented__count")
                    if opt.get("count") is not None
                    else None,
                ],
                id={"type": id_type, "group": group, "value": opt["value"]},
                n_clicks=0,
                className=classes(
                    "segmented__item",
                    "segmented__item--active" if opt["value"] == value else None,
                ),
            )
            for opt in options
        ],
        className="segmented",
        role="tablist",
    )


def legend(items):
    """
    Legenda em HTML, não dentro do gráfico: aqui cabe swatch + nome + valor,
    então a identidade da série nunca depende só da cor.
    """
    return html.Div(
        [
            html.Span(
                [
                    html.Span(
                        className=classes(
                            "legend__swatch",
                            "legend__swatch--line" if item.get("shape") == "line" else None,
                        ),
                        style={"background": item["color"]},
                    ),
                    html.Span(item["label"]),
                    html.Span(item["value"], className="legend__value") if item.get("value") else None,
                ],
                className="legend__item",
            )
            for item in items
        ],
        className="legend",
    )
