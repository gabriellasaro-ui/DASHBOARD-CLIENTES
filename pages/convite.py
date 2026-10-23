"""
Aceite de convite: a pessoa convidada define a própria senha.

O administrador nunca inventa nem transmite a senha de ninguém. Ele gera um
link, manda pelo canal que preferir, e quem recebe escolhe a senha na hora de
entrar. Senha provisória enviada por mensagem é a que vaza e nunca é trocada.

A tela já vem com a marca do cliente que convidou — o token identifica o
tenant antes de existir sessão.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html
from flask import has_request_context, request

from core.auth import sign_in
from core.branding import brand_for_request, brand_for_tenant
from core.storage import ROLE_LABELS, accept_invite, get_invite
from ui.auth_layout import auth_screen
from ui.icons import icon
from ui.primitives import field, text_input

dash.register_page(__name__, path="/convite", name="Convite", title="Convite")


STATE_MESSAGES = {
    "expired": (
        "Este convite expirou",
        "Convites valem por 7 dias. Peça um novo link para quem administra o painel.",
    ),
    "accepted": (
        "Este convite já foi usado",
        "O acesso correspondente já existe. Entre com o seu e-mail e senha.",
    ),
    "inactive": (
        "Acesso suspenso",
        "O ambiente deste cliente está inativo no momento. Fale com o administrador.",
    ),
    "missing": (
        "Convite não encontrado",
        "O link pode ter sido digitado incompleto. Confira o endereço recebido.",
    ),
}


def _notice(state: str):
    title, description = STATE_MESSAGES[state]
    body = [
        dcc.Link(
            [html.Span("Ir para o login"), icon("arrow-right", 18)],
            href="/login",
            className="btn btn--primary btn--lg btn--block",
        ),
    ]
    return title, description, body


def _existing_account_form(invite: dict):
    """E-mail que já entra em outro cliente: só a senha atual, e o cliente se soma."""
    role_label = ROLE_LABELS.get(invite["role"], "Acesso")
    subtitle = [
        "Você já tem uma conta com ", html.Strong(invite["email"]), ". Confirme sua senha para somar ",
        html.Strong(invite["tenant_name"]), f" aos seus clientes, como {role_label.lower()}.",
    ]
    body = [
        dcc.Input(id="invite-name", type="hidden", value=invite["name"]),
        dcc.Input(id="invite-confirm", type="hidden", value=""),
        field("Sua senha atual", text_input("A senha com que você já entra", "lock", "password",
                                            id="invite-password", autoComplete="current-password")),
        html.Button(
            [html.Span("Adicionar acesso e entrar"), icon("arrow-right", 18)],
            id="invite-submit", n_clicks=0, className="btn btn--primary btn--lg btn--block",
            style={"marginTop": "22px"},
        ),
        html.Div(id="invite-feedback", className="form-feedback", role="alert"),
    ]
    return "Novo cliente no seu acesso", subtitle, body


def _form(invite: dict):
    if invite.get("has_account"):
        return _existing_account_form(invite)
    role_label = ROLE_LABELS.get(invite["role"], "Acesso")
    subtitle = [
        "Você foi convidado para o painel de ",
        html.Strong(invite["tenant_name"]),
        f" como {role_label.lower()}. Defina sua senha para entrar.",
    ]
    body = [
        field("Seu nome", text_input("Nome completo", "user", id="invite-name", value=invite["name"])),
        # O e-mail vem travado: é ele que o convite autoriza. Editável,
        # viraria um jeito de criar acesso para outra pessoa.
        field(
            "E-mail de acesso",
            text_input("", "mail", "email", id="invite-email", value=invite["email"], disabled=True),
            hint="Definido pelo convite. Use este e-mail para entrar.",
            className="form-space",
        ),
        field("Senha", text_input("Mínimo de 8 caracteres", "lock", "password", id="invite-password",
                                  autoComplete="new-password"),
              className="form-space"),
        field("Confirmar senha", text_input("Repita a senha", "lock", "password", id="invite-confirm",
                                            autoComplete="new-password"),
              className="form-space"),
        html.Button(
            [html.Span("Criar acesso e entrar"), icon("arrow-right", 18)],
            id="invite-submit",
            n_clicks=0,
            className="btn btn--primary btn--lg btn--block",
            style={"marginTop": "22px"},
        ),
        html.Div(id="invite-feedback", className="form-feedback", role="alert"),
    ]
    return "Criar seu acesso", subtitle, body


def layout(token: str | None = None, **_query):
    # O Dash entrega `?token=` como argumento. `request.args` aqui não serve:
    # o layout é montado numa requisição interna do Dash, sem a URL da tela
    # — lendo de lá, todo link de convite caía em "Convite não encontrado".
    if not token and has_request_context():
        token = request.args.get("token")
    invite = get_invite(token)
    state = invite["state"] if invite else "missing"
    title, subtitle, body = _form(invite) if state == "pending" else _notice(state)

    return auth_screen(
        brand_for_tenant(invite) if invite else brand_for_request("/convite"),
        title,
        subtitle,
        body,
        footer="Seu acesso é individual: cada pessoa entra com o próprio e-mail.",
        extra=[dcc.Location(id="invite-redirect", refresh=True), dcc.Store(id="invite-token", data=token)],
    )


@callback(
    Output("invite-feedback", "children"),
    Output("invite-feedback", "className"),
    Output("invite-redirect", "href"),
    Input("invite-submit", "n_clicks"),
    State("invite-token", "data"),
    State("invite-name", "value"),
    State("invite-password", "value"),
    State("invite-confirm", "value"),
    prevent_initial_call=True,
)
def _accept(_clicks, token, name, password, confirmation):
    invite = get_invite(token) or {}
    # Conta existente confirma só a senha atual; conta nova repete a senha.
    if not invite.get("has_account") and password != confirmation:
        return "As senhas não coincidem.", "form-feedback form-feedback--error", dash.no_update

    try:
        # Entra direto, já no cliente do convite.
        sign_in(accept_invite(token, password=password, name=name))
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error", dash.no_update

    return "Acesso criado. Abrindo seu painel...", "form-feedback form-feedback--success", "/"
