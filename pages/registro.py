"""Cadastro público de uma empresa e seu primeiro gestor."""

from __future__ import annotations

import os

import dash
from dash import Input, Output, State, callback, dcc, html

from core.auth import sign_in
from core.branding import brand_for_request
from core.storage import authenticate, create_tenant
from ui.auth_layout import auth_screen
from ui.icons import icon
from ui.primitives import field, text_input


dash.register_page(__name__, path="/registro", name="Criar conta", title="Criar conta")


def layout(**_query):
    body = [
        field("Empresa", text_input("Nome da empresa", "building-2", id="register-company")),
        field(
            "Identificador",
            text_input("minha-empresa", "link-2", id="register-slug"),
            hint="Endereço curto do painel: letras minúsculas, números e hífens.",
            className="form-space",
        ),
        field("Seu nome", text_input("Nome completo", "user", id="register-name"), className="form-space"),
        field("E-mail", text_input("voce@empresa.com.br", "mail", "email", id="register-email"),
              className="form-space"),
        field("Senha", text_input("Mínimo de 8 caracteres", "lock", "password", id="register-password",
                                  autoComplete="new-password"),
              className="form-space"),
        field("Confirmar senha", text_input("Repita a senha", "lock", "password", id="register-confirm",
                                            autoComplete="new-password"),
              className="form-space"),
        html.Button(
            [html.Span("Criar conta"), icon("arrow-right", 18)],
            id="register-submit",
            n_clicks=0,
            className="btn btn--primary btn--lg btn--block",
            style={"marginTop": "22px"},
        ),
        html.Div(id="register-feedback", className="form-feedback", role="alert"),
    ]
    return auth_screen(
        brand_for_request("/registro"),
        "Criar sua conta",
        "Cadastre a empresa e quem vai administrar o painel.",
        body,
        footer=["Já tem acesso? ", dcc.Link("Entrar", href="/login", className="auth-screen__link")],
        extra=[dcc.Location(id="register-redirect", refresh=True)],
    )


@callback(
    Output("register-feedback", "children"),
    Output("register-feedback", "className"),
    Output("register-redirect", "href"),
    Input("register-submit", "n_clicks"),
    State("register-company", "value"),
    State("register-slug", "value"),
    State("register-name", "value"),
    State("register-email", "value"),
    State("register-password", "value"),
    State("register-confirm", "value"),
    prevent_initial_call=True,
)
def _register(_clicks, company, slug, name, email, password, confirmation):
    if os.getenv("PULSE_ALLOW_PUBLIC_REGISTRATION", "false").lower() != "true":
        return "Cadastro público desativado. Solicite acesso ao administrador.", "form-feedback form-feedback--error", "/login"
    if password != confirmation:
        return "As senhas não coincidem.", "form-feedback form-feedback--error", dash.no_update
    try:
        create_tenant(
            name=company,
            slug=slug,
            owner_name=name,
            owner_email=email,
            password=password,
        )
        user = authenticate(email, password)
        sign_in(user)
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error", dash.no_update
    return "Conta criada. Preparando seu painel...", "form-feedback form-feedback--success", "/"
