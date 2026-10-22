"""
Login.

Uma coluna, um cartão, três campos. A tela anterior tinha manifesto, números
de vitrine que não vinham de lugar nenhum e um botão "Entrar com Google"
desativado — tudo isso competia com a única coisa que a pessoa veio fazer.

A marca é a do cliente quando a URL diz de quem se trata (`?next=/slug`, o
redirecionamento da URL curta do cliente); senão, a da agência. Ver
`ui.auth_layout`.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate

from core.auth import sign_in
from core.branding import brand_for_request
from core.storage import authenticate, get_tenant_by_slug
from ui.auth_layout import auth_screen
from ui.icons import icon
from ui.primitives import checkbox, field, text_input

dash.register_page(__name__, path="/login", name="Entrar", title="Entrar")


def layout(**_query):
    brand = brand_for_request("/login")
    client = brand.get("name") if brand.get("name") != "V4 Company" else None

    body = [
        field(
            "Usuário ou e-mail",
            text_input("voce@empresa.com.br", "mail", "text", id="login-email", autoComplete="username"),
        ),
        field(
            "Senha",
            html.Div(
                [
                    text_input("Sua senha", "lock", "password", id="login-password",
                               autoComplete="current-password"),
                    html.Button(
                        icon("eye", 18),
                        id="login-show",
                        n_clicks=0,
                        type="button",
                        className="field__action",
                        title="Mostrar senha",
                        **{"aria-label": "Mostrar senha"},
                    ),
                ],
                className="field__with-action",
            ),
            className="form-space",
        ),
        html.Div(
            checkbox("Manter conectado neste dispositivo", checked=True, id="login-remember"),
            className="auth-card__row",
        ),
        html.Button(
            [html.Span("Entrar"), icon("arrow-right", 18)],
            id="login-submit",
            n_clicks=0,
            className="btn btn--primary btn--lg btn--block",
        ),
        html.Div(id="login-feedback", className="form-feedback", role="alert"),
    ]

    return auth_screen(
        brand,
        "Entrar",
        f"Acesse o painel de {client}." if client else "Acesse o painel de performance.",
        body,
        footer="Ainda não tem acesso? Peça um convite a quem administra o painel da sua empresa.",
        extra=[dcc.Location(id="login-redirect", refresh=True)],
    )


@callback(
    Output("login-password", "type"),
    Output("login-show", "children"),
    Output("login-show", "title"),
    Input("login-show", "n_clicks"),
    State("login-password", "type"),
    prevent_initial_call=True,
)
def _toggle_password(clicks, current):
    if not clicks:
        raise PreventUpdate
    showing = current == "password"
    return (
        "text" if showing else "password",
        icon("eye-off" if showing else "eye", 18),
        "Ocultar senha" if showing else "Mostrar senha",
    )


@callback(
    Output("login-feedback", "children"),
    Output("login-feedback", "className"),
    Output("login-redirect", "href"),
    Input("login-submit", "n_clicks"),
    Input("login-password", "n_submit"),
    State("login-email", "value"),
    State("login-password", "value"),
    State("login-remember", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def _login(_clicks, _submit, email, password, remember, search):
    if not (email or "").strip() or not password:
        return "Informe o usuário e a senha.", "form-feedback form-feedback--error", dash.no_update

    user = authenticate(email, password)
    if not user:
        return "Usuário ou senha inválidos.", "form-feedback form-feedback--error", dash.no_update

    sign_in(user, remember="on" in (remember or []))
    destination = "/admin" if user["role"] == "superadmin" else "/"
    if search and search.startswith("?next="):
        requested = search.removeprefix("?next=").split("&", 1)[0]
        # O master acaba de entrar sem cliente escolhido: uma tela de cliente
        # pedida pelo `next` não tem o que mostrar, então ele fica na lista.
        if requested in {"/", "/meta-ads", "/google-ads", "/campanhas"} and user["role"] != "superadmin":
            destination = requested
        elif requested.count("/") == 1:
            tenant = get_tenant_by_slug(requested.removeprefix("/"))
            if tenant and (user["role"] == "superadmin" or user.get("tenant_id") == tenant["id"]):
                destination = requested
    return "Tudo certo. Abrindo o painel…", "form-feedback form-feedback--success", destination
