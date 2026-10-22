"""
Moldura das telas de entrada: login, convite e cadastro.

Uma coluna só, centralizada: a marca, um cartão com o formulário e uma linha
de ajuda. Sem manifesto, sem números de vitrine, sem botão desativado — quem
chega aqui quer entrar.

A marca é a do cliente quando a tela sabe de quem se trata (`?next=/slug`
vindo da URL curta, ou o token do convite); senão, a da agência. As cores e a
fonte vêm do mesmo tema do painel, então o login de um cliente de tema escuro
já é escuro.
"""

from __future__ import annotations

from dash import html

from core.branding import admin_logo_data


def brand_mark(brand: dict):
    """Logo do cliente; sem logo, a inicial num quadrado da cor da marca."""
    name = brand.get("name") or "V4 Company"
    logo_data = brand.get("logo_data") or (admin_logo_data() if name == "V4 Company" else None)
    if logo_data:
        return html.Img(src=logo_data, alt=name, className="auth-brand__logo")
    return html.Div(
        [html.Span(name[:1].upper(), className="auth-brand__initial"), html.Span(name, className="auth-brand__name")],
        className="auth-brand__fallback",
    )


def auth_screen(brand: dict, title: str, subtitle, body, *, footer=None, extra=None):
    """
    `body` é o conteúdo do cartão abaixo do título; `extra` são componentes
    sem lugar visual (Location, Store) que a página precisa.
    """
    return html.Div(
        [
            *(extra or []),
            html.Div(className="auth-screen__glow"),
            html.Main(
                [
                    html.Div(brand_mark(brand), className="auth-brand"),
                    html.Section(
                        [
                            html.H1(title, className="auth-card__title"),
                            html.P(subtitle, className="auth-card__subtitle") if subtitle else None,
                            html.Div(body, className="auth-card__body"),
                        ],
                        className="auth-card",
                    ),
                    html.P(footer, className="auth-screen__footer") if footer else None,
                ],
                className="auth-screen__column",
            ),
        ],
        className="auth-screen",
    )
