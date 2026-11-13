"""
Verificação em duas etapas por código de 6 dígitos (TOTP, RFC 6238).

É o padrão dos apps autenticadores (Google Authenticator, Microsoft
Authenticator, 1Password, Authy): um segredo compartilhado uma vez pelo QR
code e, a cada 30 segundos, um código derivado dele e da hora.

Implementado aqui em vez de uma biblioteca porque são vinte linhas de HMAC e
o comportamento precisa ser exato: tolerância de um passo para o relógio do
celular adiantado ou atrasado, e o mesmo código recusado na segunda vez.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
ISSUER = "Painel de Performance"


def new_secret() -> str:
    """160 bits em base32, sem o '=' de preenchimento (os apps não querem)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify(secret: str | None, code: str | None, *, last_step: int | None = None,
           now: float | None = None) -> int | None:
    """
    O passo aceito, ou None.

    Aceita o código do passo atual e dos vizinhos (±30 s de relógio torto).
    Recusa passo já usado (`last_step`): quem viu o código por cima do ombro
    não consegue reaproveitá-lo.
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if not secret or len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in (step - 1, step, step + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP_SECONDS}"


def qr_data_uri(secret: str, account: str) -> str:
    """QR code do cadastro como imagem SVG embutida (nada sai do servidor)."""
    import segno

    buffer = io.BytesIO()
    segno.make(provisioning_uri(secret, account), error="m").save(buffer, kind="svg", scale=5, border=2)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def pretty_secret(secret: str) -> str:
    """Segredo em blocos de 4 para digitar à mão quando a câmera não lê o QR."""
    return " ".join(secret[index:index + 4] for index in range(0, len(secret), 4))


# --------------------------------------------------------------------------
# Aparelho lembrado
# --------------------------------------------------------------------------
#
# Depois de um código certo, o aparelho pode ser lembrado por 30 dias: o login
# pede só a senha. É um cookie ASSINADO pelo servidor (não dá para forjar) e
# preso ao cadastro atual do app — resetar o 2FA invalida todos os aparelhos
# lembrados de uma vez.

TRUST_DAYS = 30
TRUST_SALT = "pulse-mfa-trust"


def trust_cookie_name(user_id: int) -> str:
    return f"pulse_mfa_{user_id}"


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()[:16]


def trust_token(user_id: int, secret: str, app_secret: str) -> str:
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(app_secret, salt=TRUST_SALT).dumps({"uid": user_id, "fp": _fingerprint(secret)})


def is_trusted(token: str | None, user_id: int, secret: str | None, app_secret: str) -> bool:
    from itsdangerous import BadSignature, URLSafeTimedSerializer

    if not token or not secret:
        return False
    try:
        data = URLSafeTimedSerializer(app_secret, salt=TRUST_SALT).loads(token, max_age=TRUST_DAYS * 86400)
    except BadSignature:
        return False
    return data.get("uid") == user_id and data.get("fp") == _fingerprint(secret)
