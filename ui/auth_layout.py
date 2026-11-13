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

from core import mfa
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


def setup_steps(secret: str, account: str):
    """
    Cadastro do app, em passos — o mesmo no login e na tela de Segurança.

    No iPhone a câmera abre o app Senhas, que já guarda códigos de
    verificação: é um caminho válido, não um erro. A chave em texto fica
    escondida: só serve para quem não consegue ler o QR, e à vista ela
    parecia mais uma senha a decorar.
    """
    return html.Div(
        [
            html.Ol(
                [
                    html.Li(["Abra o ", html.Strong("Google Authenticator"), " (ou outro app autenticador), "
                             "toque em \"+\" > \"Ler código QR\" e aponte para o QR abaixo. Pela câmera comum o "
                             "iPhone guarda o código no app Senhas, o que também funciona."]),
                    html.Li("Digite abaixo os 6 números que aparecerem. Eles mudam a cada 30 segundos."),
                ],
                className="mfa-steps",
            ),
            html.Img(src=mfa.qr_data_uri(secret, account), alt="QR code do autenticador", className="mfa-qr"),
            html.Details(
                [
                    html.Summary("Não consegue ler o QR code?"),
                    html.P(["No app, escolha \"inserir chave manualmente\" e digite esta chave "
                            "(é a mesma coisa que o QR, em texto):"], className="mfa-key"),
                    html.Code(mfa.pretty_secret(secret), className="mfa-key__code"),
                ],
                className="mfa-manual",
            ),
        ],
        className="mfa-setup",
    )
