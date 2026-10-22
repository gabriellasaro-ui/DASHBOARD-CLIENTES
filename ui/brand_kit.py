"""
Peças da identidade visual usadas no /admin e na tela de aparência do
cliente: upload e prévia da logo, validação do arquivo e o cartão de
confirmação de sucesso.

Ficam fora de `pages/` porque as duas telas precisam se comportar igual — uma
regra de logo diferente em cada uma seria um cliente conseguindo salvar o que
o admin recusa, ou o contrário.
"""

from __future__ import annotations

import base64
import binascii
import uuid

import dash
from dash import Input, Output, State, callback, dcc, html

from ui.icons import icon

MAX_LOGO_BYTES = 1_500_000

# Formulários com campo de logo; cada um tem a própria callback de prévia.
LOGO_FORMS = ("admin-new", "admin-edit", "client-theme")


def upload_area(upload_id: str, label: str):
    return dcc.Upload(
        id=upload_id,
        children=html.Div(
            [
                html.Span(icon("arrow-up", 18), className="upload-zone__icon"),
                html.Div([html.Strong(label), html.Span("PNG, JPG ou WEBP · até 1,5 MB")]),
            ],
            className="upload-zone__content",
        ),
        className="upload-zone",
        accept="image/png,image/jpeg,image/webp",
        multiple=False,
    )


def logo_preview(src: str | None, *, filename: str | None = None, error: str | None = None):
    """
    O que vai virar a logo, visto ANTES de salvar.

    O `dcc.Upload` só guarda o arquivo; sem esta prévia, escolher a imagem
    não mudava nada na tela e a logo só aparecia depois de salvar — dava a
    impressão de que o envio não tinha funcionado.
    """
    if error:
        return html.Div([icon("alert-triangle", 16), html.Span(error)], className="logo-preview logo-preview--error",
                        role="alert")
    if not src:
        return None
    pending = filename is not None
    return html.Div(
        [
            html.Div(html.Img(src=src, alt="Logo"), className="logo-preview__frame"),
            html.Div(
                [
                    html.Strong("Nova logo · salve para aplicar" if pending else "Logo atual"),
                    html.Span(filename or "Exibida na barra lateral, no login e no favicon"),
                ],
                className="logo-preview__text",
            ),
        ],
        className="logo-preview",
    )


def safe_logo(contents: str | None) -> str | None:
    if not contents:
        return None
    allowed = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")
    if not contents.startswith(allowed):
        raise ValueError("Envie a logo em PNG, JPG ou WEBP.")
    try:
        raw = base64.b64decode(contents.split(",", 1)[1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("O arquivo de logo não pôde ser lido.") from exc
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError("A logo deve ter no máximo 1,5 MB.")
    return contents


def toast(message: str):
    """
    Cartão de confirmação no topo da tela, que some sozinho.

    O formulário do cliente é longo: o aviso de sucesso escrito no topo da
    página não era visto por quem clicou em "Salvar" lá embaixo. A `key`
    nova a cada vez remonta o cartão e reinicia a animação — salvar duas
    vezes seguidas mostra a confirmação duas vezes.
    """
    lowered = message.lower()
    title = "Salvo com sucesso" if any(word in lowered for word in ("atualiz", "criado", "salv")) else "Pronto"
    return html.Div(
        [
            html.Span(icon("check", 20), className="toast__icon"),
            html.Div([html.Strong(title), html.Span(message)], className="toast__text"),
        ],
        key=uuid.uuid4().hex,
        className="toast",
        role="status",
        **{"aria-live": "polite"},
    )


def register_logo_preview(prefix: str) -> None:
    """Uma callback por formulário: os formulários nunca estão na tela juntos."""

    @callback(
        Output(f"{prefix}-logo-preview", "children"),
        Input(f"{prefix}-logo", "contents"),
        State(f"{prefix}-logo", "filename"),
        prevent_initial_call=True,
    )
    def _preview(contents, filename):
        if not contents:
            return dash.no_update
        try:
            # A mesma validação do salvar: o erro aparece na hora de escolher
            # o arquivo, não só depois de preencher o resto do formulário.
            safe_logo(contents)
        except ValueError as exc:
            return logo_preview(None, error=str(exc))
        return logo_preview(contents, filename=filename or "imagem enviada")


for _prefix in LOGO_FORMS:
    register_logo_preview(_prefix)
