"""
Segurança — verificação em duas etapas da própria conta.

Cada pessoa ativa o MFA dela mesma: o cadastro precisa do celular dela (o QR
code é lido pelo app autenticador). O master não ativa pela pessoa — ele
EXIGE (no /admin), e aí o cadastro acontece no próximo login dela.

Ativar exige confirmar um código: segredo salvo sem confirmação deixaria a
pessoa trancada fora se o QR tivesse sido lido errado. Desativar também pede
um código, para quem pegar uma sessão aberta não conseguir tirar a proteção.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate
from flask import session

from core import mfa
from core.auth import current_user
from core.storage import disable_mfa, enable_mfa, get_mfa, mark_mfa_step
from ui.auth_layout import setup_steps
from ui.icons import icon
from ui.primitives import badge, card, card_body, card_header, field, text_input
from ui.shell import page_head

dash.register_page(__name__, path="/seguranca", name="Segurança", title="Segurança")

SETUP_KEY = "mfa_setup_secret"


def layout(**_query):
    user = current_user()
    if not user:
        return html.Div()
    state = get_mfa(user["id"])

    if state["enabled"]:
        status = [badge("Ativa", "positive", dot=True),
                  html.P("Ao entrar, além da senha, você digita o código do app autenticador.",
                         className="t-micro security__text")]
        actions = html.Div(
            [
                field("Código atual do app", text_input("000000", "shield-check", "text", id="sec-disable-code",
                                                        inputMode="numeric", maxLength=7, autoComplete="one-time-code"),
                      hint="Exigido pelo administrador: não dá para desativar." if state["required"] else
                      "Para desativar, confirme com o código que aparece agora no app."),
                html.Button("Desativar verificação", id="sec-disable", n_clicks=0,
                            className="btn btn--danger btn--sm", disabled=state["required"],
                            style={"marginTop": "14px"}),
            ],
        )
    else:
        status = [badge("Desativada", "warning", dot=True),
                  html.P("Com a verificação em duas etapas, quem descobrir sua senha ainda precisa do seu "
                         "celular para entrar.", className="t-micro security__text")]
        actions = html.Div(
            [
                html.Button([icon("shield-check", 16), html.Span("Ativar verificação em duas etapas")],
                            id="sec-start", n_clicks=0, className="btn btn--primary btn--sm"),
                html.Div(id="sec-setup"),
                html.Div(
                    [
                        field("Código do app", text_input("000000", "shield-check", "text", id="sec-code",
                                                          inputMode="numeric", maxLength=7,
                                                          autoComplete="one-time-code"),
                              hint="Os 6 números que o app mostra depois de ler o QR code."),
                        html.Button("Confirmar e ativar", id="sec-confirm", n_clicks=0,
                                    className="btn btn--primary btn--sm", style={"marginTop": "14px"}),
                    ],
                    id="sec-confirm-wrap",
                    className="hide",
                ),
            ]
        )

    return html.Div(
        [
            dcc.Location(id="sec-redirect", refresh=True),
            page_head("Segurança", [("Conta", None), ("Segurança", None)],
                      description=f"Proteção do acesso de {user['email']}.", glyph="shield-check"),
            card(
                [
                    card_header("Verificação em duas etapas",
                                "Código de 6 dígitos do Google Authenticator, Microsoft Authenticator ou similar.",
                                lead_icon="shield-check"),
                    card_body(
                        [
                            html.Div(status, className="security__status"),
                            actions,
                            html.Div(id="sec-feedback", className="form-feedback", role="alert"),
                        ]
                    ),
                ],
                className="security-card",
            ),
        ],
        className="anim-up",
    )


@callback(
    Output("sec-setup", "children"),
    Output("sec-confirm-wrap", "className"),
    Output("sec-start", "className"),
    Input("sec-start", "n_clicks"),
    prevent_initial_call=True,
)
def _start(clicks):
    user = current_user()
    if not clicks or not user:
        raise PreventUpdate
    # O segredo só vai para o banco depois do primeiro código certo.
    secret = mfa.new_secret()
    session[SETUP_KEY] = secret
    setup = html.Div(setup_steps(secret, user["email"]), className="mfa-setup--left")
    return setup, None, "hide"


@callback(
    Output("sec-feedback", "children"),
    Output("sec-feedback", "className"),
    Output("sec-redirect", "href"),
    Input("sec-confirm", "n_clicks"),
    Input("sec-code", "n_submit"),
    State("sec-code", "value"),
    prevent_initial_call=True,
)
def _confirm(clicks, submits, code):
    user = current_user()
    if not (clicks or submits) or not user:
        raise PreventUpdate
    secret = session.get(SETUP_KEY)
    if not secret:
        return "Comece de novo: clique em Ativar.", "form-feedback form-feedback--error", dash.no_update
    step = mfa.verify(secret, code)
    if step is None:
        return ("Código incorreto. Confira se o app leu o QR desta tela e tente o código atual.",
                "form-feedback form-feedback--error", dash.no_update)
    enable_mfa(user["id"], secret)
    mark_mfa_step(user["id"], step)
    session.pop(SETUP_KEY, None)
    return "Verificação ativada.", "form-feedback form-feedback--success", "/seguranca"


@callback(
    Output("sec-feedback", "children", allow_duplicate=True),
    Output("sec-feedback", "className", allow_duplicate=True),
    Output("sec-redirect", "href", allow_duplicate=True),
    Input("sec-disable", "n_clicks"),
    State("sec-disable-code", "value"),
    prevent_initial_call=True,
)
def _disable(clicks, code):
    user = current_user()
    if not clicks or not user:
        raise PreventUpdate
    state = get_mfa(user["id"])
    if state["required"]:
        return ("O administrador exige verificação em duas etapas nesta conta.",
                "form-feedback form-feedback--error", dash.no_update)
    if mfa.verify(state["secret"], code, last_step=state["last_step"]) is None:
        return "Código incorreto.", "form-feedback form-feedback--error", dash.no_update
    disable_mfa(user["id"])
    return "Verificação desativada.", "form-feedback form-feedback--success", "/seguranca"
