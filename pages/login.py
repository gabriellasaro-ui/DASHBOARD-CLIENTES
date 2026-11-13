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
from dash import Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate

import time

from flask import current_app, request, session

from core import mfa
from core.auth import sign_in
from core.branding import brand_for_request
from core.storage import authenticate, enable_mfa, get_mfa, get_tenant_by_slug, get_user, mark_mfa_step
from ui.auth_layout import auth_screen, setup_steps
from ui.icons import icon
from ui.primitives import checkbox, field, text_input

dash.register_page(__name__, path="/login", name="Entrar", title="Entrar")


def layout(**_query):
    brand = brand_for_request("/login")
    client = brand.get("name") if brand.get("name") != "V4 Company" else None

    password_step = html.Div(
        [
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
        ],
        id="login-step-password",
    )

    # Segunda etapa: nasce escondida e só aparece depois da senha certa. O QR
    # de cadastro (quando o MFA é exigido e ainda não existe) entra em
    # `login-mfa-setup`.
    mfa_step = html.Div(
        [
            html.Div(id="login-mfa-setup"),
            field(
                "Código do app autenticador",
                text_input("000000", "shield-check", "text", id="login-mfa-code",
                           autoComplete="one-time-code", inputMode="numeric", maxLength=7),
                hint="Os 6 números que aparecem agora no app (mudam a cada 30 segundos).",
            ),
            html.Div(
                checkbox("Não pedir o código neste aparelho por 30 dias", checked=True, id="login-mfa-trust"),
                className="auth-card__row",
                style={"marginBottom": "0"},
            ),
            html.Button(
                [html.Span("Confirmar"), icon("arrow-right", 18)],
                id="login-mfa-submit",
                n_clicks=0,
                className="btn btn--primary btn--lg btn--block",
                style={"marginTop": "22px"},
            ),
        ],
        id="login-step-mfa",
        className="hide",
    )

    return auth_screen(
        brand,
        "Entrar",
        f"Acesse o painel de {client}." if client else "Acesse o painel de performance.",
        [password_step, mfa_step, html.Div(id="login-feedback", className="form-feedback", role="alert")],
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


MFA_PENDING = "mfa_pending"
MFA_PENDING_SECONDS = 5 * 60
MFA_MAX_ATTEMPTS = 5


def _destination(user: dict, search: str | None) -> str:
    destination = "/admin" if user["role"] == "superadmin" else "/"
    if search and search.startswith("?next="):
        requested = search.removeprefix("?next=").split("&", 1)[0]
        # O master acaba de entrar sem cliente escolhido: uma tela de cliente
        # pedida pelo `next` não tem o que mostrar, então ele fica na lista.
        if requested in {"/", "/meta-ads", "/google-ads", "/campanhas"} and user["role"] != "superadmin":
            destination = requested
        elif requested.startswith("/tv/") and requested.count("/") == 2:
            # Tela de TV: a própria página confere se a pessoa tem acesso.
            destination = requested
        elif requested.count("/") == 1:
            tenant = get_tenant_by_slug(requested.removeprefix("/"))
            if tenant and (user["role"] == "superadmin" or any(
                item["tenant_id"] == tenant["id"] for item in user.get("memberships") or []
            )):
                destination = requested
    return destination


def _error(message):
    return message, "form-feedback form-feedback--error"


def _setup_block(secret: str, account: str):
    return html.Div(
        [
            html.P("Sua conta pede um código do celular além da senha. Configure uma vez:",
                   className="auth-card__subtitle", style={"marginTop": "0"}),
            setup_steps(secret, account),
        ]
    )


@callback(
    Output("login-feedback", "children"),
    Output("login-feedback", "className"),
    Output("login-redirect", "href"),
    Output("login-step-password", "className"),
    Output("login-step-mfa", "className"),
    Output("login-mfa-setup", "children"),
    Input("login-submit", "n_clicks"),
    Input("login-password", "n_submit"),
    State("login-email", "value"),
    State("login-password", "value"),
    State("login-remember", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def _login(_clicks, _submit, email, password, remember, search):
    keep = (dash.no_update,) * 4
    if not (email or "").strip() or not password:
        return *_error("Informe o usuário e a senha."), *keep

    user = authenticate(email, password)
    if not user:
        return *_error("Usuário ou senha inválidos."), *keep

    remember_me = "on" in (remember or [])
    destination = _destination(user, search)
    state = get_mfa(user["id"])
    # Aparelho lembrado depois de um código certo: entra só com a senha.
    trusted = state["enabled"] and mfa.is_trusted(
        request.cookies.get(mfa.trust_cookie_name(user["id"])), user["id"], state["secret"],
        current_app.config["SECRET_KEY"],
    )
    if trusted or (not state["enabled"] and not state["required"]):
        sign_in(user, remember=remember_me)
        return ("Tudo certo. Abrindo o painel...", "form-feedback form-feedback--success", destination,
                dash.no_update, dash.no_update, dash.no_update)

    # Senha certa, mas ainda falta o código. Nada de sessão de usuário até lá:
    # só um "pendente" com prazo, guardado no cookie assinado.
    pending = {"user_id": user["id"], "remember": remember_me, "next": destination,
               "at": time.time(), "attempts": 0}
    setup = None
    if not state["enabled"]:
        # O admin exigiu MFA e a pessoa ainda não cadastrou: cadastra agora.
        pending["new_secret"] = mfa.new_secret()
        setup = _setup_block(pending["new_secret"], user["email"])
    session[MFA_PENDING] = pending
    return None, "form-feedback", dash.no_update, "hide", None, setup


@callback(
    Output("login-feedback", "children", allow_duplicate=True),
    Output("login-feedback", "className", allow_duplicate=True),
    Output("login-redirect", "href", allow_duplicate=True),
    Input("login-mfa-submit", "n_clicks"),
    Input("login-mfa-code", "n_submit"),
    State("login-mfa-code", "value"),
    State("login-mfa-trust", "value"),
    prevent_initial_call=True,
)
def _login_mfa(clicks, submits, code, trust):
    if not (clicks or submits):
        raise PreventUpdate
    pending = session.get(MFA_PENDING)
    if not pending or time.time() - pending.get("at", 0) > MFA_PENDING_SECONDS:
        session.pop(MFA_PENDING, None)
        return *_error("O tempo para digitar o código acabou. Entre com a senha de novo."), "/login"
    if pending.get("attempts", 0) >= MFA_MAX_ATTEMPTS:
        session.pop(MFA_PENDING, None)
        return *_error("Muitas tentativas. Entre com a senha de novo."), "/login"

    state = get_mfa(pending["user_id"])
    enrolling = bool(pending.get("new_secret"))
    secret = pending["new_secret"] if enrolling else state["secret"]
    step = mfa.verify(secret, code, last_step=None if enrolling else state["last_step"])
    if step is None:
        pending["attempts"] = pending.get("attempts", 0) + 1
        session[MFA_PENDING] = pending
        return *_error("Código incorreto. Confira o app e tente de novo."), dash.no_update

    if enrolling:
        enable_mfa(pending["user_id"], pending["new_secret"])
    mark_mfa_step(pending["user_id"], step)
    if "on" in (trust or []):
        ctx.response.set_cookie(
            mfa.trust_cookie_name(pending["user_id"]),
            mfa.trust_token(pending["user_id"], secret, current_app.config["SECRET_KEY"]),
            max_age=mfa.TRUST_DAYS * 86400,
            httponly=True,
            samesite="Lax",
            secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
        )
    user = get_user(pending["user_id"])
    session.pop(MFA_PENDING, None)
    if not user:
        return *_error("Acesso não encontrado."), "/login"
    sign_in(user, remember=pending.get("remember", False))
    return "Tudo certo. Abrindo o painel...", "form-feedback form-feedback--success", pending.get("next") or "/"
