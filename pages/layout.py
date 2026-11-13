"""
Layout — o que aparece na tela.

Duas coisas, por cliente:

* **Painel** — quais blocos o dashboard mostra (vale para todos os acessos
  do cliente; os indicadores da faixa continuam no botão "Métricas").
* **Telas de TV** — quantas telas quiser, cada uma com nome, período,
  indicadores e gráficos próprios, e um endereço fixo (`/tv/<código>`) para
  deixar aberto na TV. Duas TVs do mesmo cliente podem mostrar coisas
  diferentes: uma só Meta, outra só Google, por exemplo.

Quem altera: o responsável do cliente e o master (mesma regra da
aparência). O visualizador vê os links das telas, para poder abrir numa TV.
"""

from __future__ import annotations

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate
from flask import has_request_context, request

from core import layouts
from core.auth import active_tenant, can_edit_appearance, current_user
from core.mock import PERIODS
from core.storage import delete_tv_screen, get_tv_screen, list_tv_screens, save_tv_screen, set_dashboard_layout
from ui.brand_kit import toast
from ui.icons import icon
from ui.primitives import card, card_body, card_header, field, form_section, text_input
from ui.shell import page_head, select_client_state

dash.register_page(__name__, path="/layout", name="Layout", title="Layout")

PERIOD_LABELS = {period["id"]: period["label"] for period in PERIODS}


def _checklist(component_id, options, value):
    return dcc.Checklist(
        id=component_id,
        options=options,
        value=value,
        className="widget-pick",
        labelClassName="checkbox",
        inputClassName="checkbox__box",
    )


def _tv_url(screen_id: str) -> str:
    base = request.host_url if has_request_context() else "/"
    return f"{base.rstrip('/')}/tv/{screen_id}"


def _screen_list(tenant_id: int, editable: bool):
    screens = list_tv_screens(tenant_id)
    if not screens:
        return html.P("Nenhuma tela criada ainda." + (" Monte a primeira abaixo." if editable else ""),
                      className="t-micro tv-list__empty")
    rows = []
    for screen in screens:
        config = layouts.clean_tv(screen["config"])
        charts = [key for key in config["widgets"] if key != "kpis"]
        url = _tv_url(screen["id"])
        summary = (f'{PERIOD_LABELS.get(config["period"], config["period"])} · '
                   f'{len(config["kpis"]) if "kpis" in config["widgets"] else 0} indicadores · '
                   f'{len(charts)} gráficos')
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span([icon("monitor", 16), html.Strong(screen["name"])], className="tv-list__name"),
                            html.Span(summary, className="t-micro"),
                            html.Div(
                                [
                                    html.Code(url, className="tv-list__url"),
                                    dcc.Clipboard(content=url, title="Copiar link", className="tv-list__copy"),
                                ],
                                className="tv-list__link",
                            ),
                        ],
                        className="tv-list__info",
                    ),
                    html.Div(
                        [
                            html.A([icon("external-link", 15), html.Span("Abrir")], href=url, target="_blank",
                                   className="btn btn--outline btn--sm"),
                            html.Button([icon("pencil", 15), html.Span("Editar")],
                                        id={"type": "tv-edit", "id": screen["id"]}, n_clicks=0,
                                        className="btn btn--outline btn--sm") if editable else None,
                            dcc.ConfirmDialogProvider(
                                html.Button(icon("trash-2", 15), className="btn btn--ghost btn--icon btn--sm",
                                            title="Excluir tela"),
                                id={"type": "tv-delete", "id": screen["id"]},
                                message=f'Excluir a tela "{screen["name"]}"? A TV que estiver com ela aberta '
                                        "passa a mostrar \"Tela indisponível\".",
                            ) if editable else None,
                        ],
                        className="tv-list__actions",
                    ),
                ],
                className="tv-list__row",
            )
        )
    return rows


def _tv_form(config: dict | None = None, name: str | None = None):
    config = layouts.clean_tv(config or {})
    return [
        html.Div(
            [
                field("Nome da tela", text_input("Ex.: TV da recepção", "monitor", id="tv-form-name", value=name)),
                field("Período", dcc.Dropdown(id="tv-form-period", options=layouts.period_options(),
                                              value=config["period"], clearable=False, className="select")),
            ],
            className="form-grid form-grid--2",
        ),
        field(f"Indicadores (até {layouts.TV_MAX_KPIS})",
              _checklist("tv-form-kpis", layouts.kpi_options(), config["kpis"]), className="form-space"),
        field(f"Blocos (até {layouts.TV_MAX_CHARTS} gráficos)",
              _checklist("tv-form-widgets", layouts.widget_options(tv=True), config["widgets"]),
              hint="A tela é dividida entre os blocos escolhidos: quanto menos blocos, maior cada um na TV.",
              className="form-space"),
    ]


def layout(**_query):
    user = current_user()
    tenant = active_tenant()
    if not tenant:
        return html.Div([select_client_state()], className="anim-up")
    editable = can_edit_appearance(user, tenant)
    dashboard = layouts.clean_dashboard(tenant.get("layout_data"))

    head = page_head(
        "Layout",
        [("Conta", None), ("Layout", None)],
        description=f"Escolha o que aparece no painel e nas TVs de {tenant['name']}.",
        glyph="layout-dashboard",
    )

    panel_card = card(
        [
            card_header("Painel", "Blocos do dashboard. Vale para todos os acessos do cliente.",
                        lead_icon="layout-dashboard"),
            card_body(
                [
                    _checklist("layout-dash-widgets", layouts.widget_options(), dashboard["widgets"]),
                    html.P("Os indicadores da faixa de cards são escolhidos no botão \"Métricas\", no topo.",
                           className="t-micro", style={"marginTop": "12px"}),
                    html.Div(
                        html.Button([icon("check", 16), html.Span("Salvar painel")], id="layout-dash-save",
                                    n_clicks=0, className="btn btn--primary btn--sm"),
                        className="form-actions",
                    ) if editable else None,
                ]
            ),
        ],
    )

    tv_card = card(
        [
            card_header("Telas de TV", "Cada tela tem um endereço fixo: abra na TV, entre com um acesso do "
                        "cliente e deixe aberto. Ela se atualiza sozinha.", lead_icon="monitor"),
            html.Div(_screen_list(tenant["id"], editable), id="tv-list", className="tv-list"),
            card_body(
                [
                    form_section(
                        "Montar uma tela",
                        [
                            dcc.Store(id="tv-edit-id", data=None),
                            html.Div(id="tv-form-mode", className="t-micro tv-form__mode",
                                     children="Nova tela"),
                            html.Div(_tv_form(), id="tv-form"),
                            html.Div(id="layout-feedback", className="form-feedback", role="alert"),
                            html.Div(
                                [
                                    html.Button("Nova tela em branco", id="tv-form-new", n_clicks=0,
                                                className="btn btn--ghost btn--sm"),
                                    html.Button([icon("check", 16), html.Span("Salvar tela")], id="tv-form-save",
                                                n_clicks=0, className="btn btn--primary btn--sm"),
                                ],
                                className="form-actions form-actions--split",
                            ),
                        ],
                        first=True,
                    ),
                ]
            ) if editable else None,
        ],
    )

    return html.Div(
        [head, html.Div(id="layout-toast"), html.Div([panel_card, tv_card], className="layout-page__cards")],
        className="anim-up layout-page",
    )


def _guard_editor():
    tenant = active_tenant()
    if not can_edit_appearance(current_user(), tenant):
        raise PreventUpdate
    return tenant


@callback(
    Output("layout-toast", "children"),
    Input("layout-dash-save", "n_clicks"),
    State("layout-dash-widgets", "value"),
    prevent_initial_call=True,
)
def _save_dashboard(clicks, widgets):
    if not clicks:
        raise PreventUpdate
    tenant = _guard_editor()
    set_dashboard_layout(tenant["id"], {"widgets": widgets})
    return toast("Painel salvo. Os blocos escolhidos já aparecem no dashboard.")


@callback(
    Output("tv-form", "children"),
    Output("tv-edit-id", "data"),
    Output("tv-form-mode", "children"),
    Input({"type": "tv-edit", "id": ALL}, "n_clicks"),
    Input("tv-form-new", "n_clicks"),
    prevent_initial_call=True,
)
def _pick_screen(_edits, _new):
    # Botões de editar nascem com n_clicks 0 a cada lista refeita.
    if not (ctx.triggered and ctx.triggered[0].get("value")):
        raise PreventUpdate
    tenant = _guard_editor()
    trigger = ctx.triggered_id
    if trigger == "tv-form-new":
        return _tv_form(), None, "Nova tela"
    screen = get_tv_screen(trigger["id"])
    if not screen or screen["tenant_id"] != tenant["id"]:
        raise PreventUpdate
    return _tv_form(screen["config"], screen["name"]), screen["id"], f'Editando "{screen["name"]}"'


@callback(
    Output("tv-list", "children"),
    Output("layout-toast", "children", allow_duplicate=True),
    Output("layout-feedback", "children"),
    Output("layout-feedback", "className"),
    Output("tv-edit-id", "data", allow_duplicate=True),
    Output("tv-form-mode", "children", allow_duplicate=True),
    Input("tv-form-save", "n_clicks"),
    Input({"type": "tv-delete", "id": ALL}, "submit_n_clicks"),
    State("tv-edit-id", "data"),
    State("tv-form-name", "value"),
    State("tv-form-period", "value"),
    State("tv-form-kpis", "value"),
    State("tv-form-widgets", "value"),
    prevent_initial_call=True,
)
def _save_or_delete(_save, _deletes, editing, name, period, kpis, widgets):
    if not (ctx.triggered and ctx.triggered[0].get("value")):
        raise PreventUpdate
    tenant = _guard_editor()
    trigger = ctx.triggered_id

    if isinstance(trigger, dict):
        delete_tv_screen(trigger["id"], tenant["id"])
        cleared = trigger["id"] == editing
        return (_screen_list(tenant["id"], True), toast("Tela excluída."), None, "form-feedback",
                None if cleared else dash.no_update, "Nova tela" if cleared else dash.no_update)

    charts = [key for key in (widgets or []) if key != "kpis"]
    if len(charts) > layouts.TV_MAX_CHARTS or len(kpis or []) > layouts.TV_MAX_KPIS:
        return (dash.no_update, dash.no_update,
                f"Até {layouts.TV_MAX_KPIS} indicadores e {layouts.TV_MAX_CHARTS} gráficos por tela: "
                "mais que isso fica ilegível de longe.", "form-feedback form-feedback--error",
                dash.no_update, dash.no_update)
    if not widgets:
        return (dash.no_update, dash.no_update, "Escolha pelo menos um bloco para a tela.",
                "form-feedback form-feedback--error", dash.no_update, dash.no_update)
    try:
        saved = save_tv_screen(tenant["id"], name=name, screen_id=editing,
                               config={"period": period, "kpis": kpis, "widgets": widgets})
    except ValueError as exc:
        return dash.no_update, dash.no_update, str(exc), "form-feedback form-feedback--error", dash.no_update, \
            dash.no_update
    message = "Tela salva. A TV com ela aberta atualiza sozinha em até 5 minutos." if editing else \
        "Tela criada. Copie o link e abra na TV."
    return (_screen_list(tenant["id"], True), toast(message), None, "form-feedback", saved["id"],
            f'Editando "{saved["name"]}"')
