"""
Aparência — o próprio cliente personaliza o painel da empresa.

Logo, cores da marca, fontes, cores de fundo/texto/cards/menu e cantos, com
a mesma prévia ao vivo do /admin (`ui.theme_editor`). Só o responsável da
empresa salva (ver `core.auth.can_edit_appearance`); quem é visualizador vê a
tela com o aviso de quem pode mudar.

A mudança vale para todos os acessos da empresa e aparece na hora para quem
salvou: as cores, a logo e a fonte do painel aberto são trocadas no mesmo
clique, sem recarregar.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from core.auth import active_tenant, can_edit_appearance, current_user
from core.branding import brand_font_url, brand_for_tenant, style_variables
from core.data import clear_cache
from core.storage import get_tenant, update_tenant_appearance
from ui.brand_kit import logo_preview, safe_logo, toast, upload_area
from ui.icons import icon
from ui.primitives import card, card_body, card_header, color_input, field, form_section
from ui.shell import brand_logo, page_head, select_client_state
from ui.theme_editor import appearance_section, theme_from_states, theme_states

dash.register_page(__name__, path="/aparencia", name="Aparência", title="Aparência")

PREFIX = "client-theme"
_INTER_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"


def _read_only_notice(tenant: dict):
    owner = tenant.get("owner_email")
    return html.Div(
        [
            icon("lock", 18),
            html.Div(
                [
                    html.Strong("Só o responsável pela conta pode alterar a aparência"),
                    html.Span(
                        f"A mudança vale para todos os acessos da empresa. Fale com {owner}."
                        if owner else "A mudança vale para todos os acessos da empresa."
                    ),
                ]
            ),
        ],
        className="appearance-locked",
        role="note",
    )


def layout(**_query):
    user = current_user()
    tenant = active_tenant()
    if not tenant:
        return html.Div([select_client_state()], className="anim-up")

    editable = can_edit_appearance(user, tenant)
    brand = brand_for_tenant(tenant)

    head = page_head(
        "Aparência",
        [("Conta", None), ("Aparência", None)],
        description=f"Logo, cores e fontes do painel de {tenant['name']}. Vale para todos os acessos da empresa.",
        glyph="palette",
    )

    if not editable:
        return html.Div([head, _read_only_notice(tenant)], className="anim-up")

    return html.Div(
        [
            head,
            # O editor lê o nome do cliente para a prévia; aqui ele não é
            # editável, então vai num campo oculto.
            dcc.Input(id=f"{PREFIX}-name", type="hidden", value=tenant["name"]),
            html.Div(id=f"{PREFIX}-toast"),
            card(
                [
                    card_header("Identidade e tema", "Ajuste à vontade: a prévia mostra o resultado antes de salvar.",
                                lead_icon="palette"),
                    card_body(
                        [
                            form_section(
                                "Marca",
                                [
                                    html.Div(
                                        [
                                            field("Cor principal",
                                                  color_input(f"{PREFIX}-primary", tenant["primary_color"],
                                                              group="tenant")),
                                            field("Cor de apoio",
                                                  color_input(f"{PREFIX}-secondary", tenant["secondary_color"],
                                                              group="tenant")),
                                        ],
                                        className="form-grid form-grid--2",
                                    ),
                                    html.Div(
                                        [
                                            upload_area(f"{PREFIX}-logo", "Trocar logo"),
                                            html.Div(logo_preview(tenant.get("logo_data")),
                                                     id=f"{PREFIX}-logo-preview"),
                                        ],
                                        className="form-space logo-upload",
                                    ),
                                ],
                                hint="A cor principal pinta botões, destaques, gráficos e o ícone da aba.",
                                first=True,
                            ),
                            appearance_section(PREFIX, tenant.get("theme_data"), brand),
                            html.Div(id=f"{PREFIX}-feedback", className="form-feedback", role="alert"),
                            html.Div(
                                html.Button(
                                    [icon("check", 18), html.Span("Salvar aparência")],
                                    id=f"{PREFIX}-save",
                                    n_clicks=0,
                                    className="btn btn--primary",
                                ),
                                className="form-actions",
                            ),
                        ]
                    ),
                ],
            ),
        ],
        className="anim-up appearance-page",
    )


@callback(
    Output(f"{PREFIX}-feedback", "children"),
    Output(f"{PREFIX}-feedback", "className"),
    Output(f"{PREFIX}-toast", "children"),
    Output(f"{PREFIX}-logo-preview", "children", allow_duplicate=True),
    # O painel aberto troca de cara no mesmo clique (ver docstring).
    Output("app-root", "style", allow_duplicate=True),
    Output("brand-logo", "children", allow_duplicate=True),
    Output("brand-font", "href", allow_duplicate=True),
    Input(f"{PREFIX}-save", "n_clicks"),
    State({"type": "color-value", "group": "tenant", "for": f"{PREFIX}-primary"}, "value"),
    State({"type": "color-value", "group": "tenant", "for": f"{PREFIX}-secondary"}, "value"),
    State(f"{PREFIX}-logo", "contents"),
    *theme_states(PREFIX),
    prevent_initial_call=True,
)
def _save(clicks, primary, secondary, logo, *theme_values):
    unchanged = (dash.no_update,) * 5
    if not clicks:
        return dash.no_update, dash.no_update, *unchanged

    tenant = active_tenant()
    # A permissão é conferida de novo no servidor: esconder o botão não basta.
    if not can_edit_appearance(current_user(), tenant):
        return ("Somente o responsável pela conta pode alterar a aparência.",
                "form-feedback form-feedback--error", *unchanged)

    current = get_tenant(tenant["id"]) or tenant
    try:
        updated = update_tenant_appearance(
            tenant["id"],
            primary_color=primary,
            secondary_color=secondary,
            # Sem arquivo novo, a logo atual fica.
            logo_data=safe_logo(logo) if logo else current.get("logo_data"),
            theme=theme_from_states(theme_values),
        )
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error", *unchanged

    clear_cache()
    brand = brand_for_tenant(updated)
    return (
        None,
        "form-feedback",
        toast("Aparência salva. Já vale para todos os acessos da empresa."),
        logo_preview(updated.get("logo_data")),
        style_variables(brand),
        brand_logo(brand),
        brand_font_url(brand) or _INTER_URL,
    )
