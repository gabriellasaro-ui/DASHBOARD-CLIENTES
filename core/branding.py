"""
Converte a identidade do tenant em uma paleta completa.

A regra do whitelabel aqui: a cor que o administrador escolhe governa TUDO —
botão, item ativo, foco, favicon, sparkline, primeira série dos gráficos e a
rampa do funil. Não é só o botão que muda de cor.

Duas coisas que a cor escolhida NÃO pode governar, e o porquê:

* **As três séries de gráfico não viram todas a mesma cor.** Um gráfico com
  três linhas precisa de três matizes distinguíveis; pintar tudo de vermelho
  tornaria o gráfico ilegível. A marca vira a série 1 e as companheiras são
  escolhidas por distância de matiz da marca, para não competirem com ela.
* **Verde/vermelho de status continuam fixos.** Se a marca do cliente é
  verde, "caiu 8%" não pode aparecer em verde.

E uma correção que o produto faz por conta própria: marca de baixo contraste
(amarelo, lima, ciano claro) é ilegível como traço de 2px sobre fundo branco.
Para DADO a cor é escurecida até passar de 3:1; para BOTÃO a original é
mantida, porque ali o texto é branco por cima e o contraste é outro cálculo.
"""

from __future__ import annotations

import base64
import colorsys
from functools import lru_cache
from pathlib import Path

from core.tenant_theme import DEFAULT_THEME, google_fonts_url, parse_theme, theme_tokens


BASE_DIR = Path(__file__).resolve().parent.parent
ADMIN_LOGO_PATH = BASE_DIR / "logo v4.png"


@lru_cache(maxsize=1)
def admin_logo_data() -> str | None:
    if not ADMIN_LOGO_PATH.exists():
        return None
    encoded = base64.b64encode(ADMIN_LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


DEFAULT_PRIMARY = "#E5001A"
DEFAULT_SECONDARY = "#0B0B0D"

DEFAULT_BRAND = {
    "name": "V4 Company",
    "logo_data": None,
    "primary_color": DEFAULT_PRIMARY,
    "secondary_color": DEFAULT_SECONDARY,
    "theme": dict(DEFAULT_THEME),
}


def admin_brand() -> dict:
    return {
        "name": "V4 Company",
        "logo_data": admin_logo_data(),
        "primary_color": DEFAULT_PRIMARY,
        "secondary_color": DEFAULT_SECONDARY,
        "theme": dict(DEFAULT_THEME),
    }


# --------------------------------------------------------------------------
# Conversões de cor
# --------------------------------------------------------------------------

def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        value = DEFAULT_PRIMARY.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02X}" for channel in rgb)


def _to_hls(hex_color: str) -> tuple[float, float, float]:
    red, green, blue = (channel / 255 for channel in _rgb(hex_color))
    return colorsys.rgb_to_hls(red, green, blue)


def _from_hls(hue: float, lightness: float, saturation: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue % 1.0, max(0.0, min(1.0, lightness)),
                                           max(0.0, min(1.0, saturation)))
    return _hex((red * 255, green * 255, blue * 255))


def _relative_luminance(hex_color: str) -> float:
    channels = []
    for value in _rgb(hex_color):
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str = "#FFFFFF") -> float:
    lighter = _relative_luminance(foreground)
    darker = _relative_luminance(background)
    if lighter < darker:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


def readable_ink(hex_color: str) -> str:
    """Preto ou branco por cima da cor — o que tiver mais contraste."""
    return "#0B0B0D" if contrast_ratio("#0B0B0D", hex_color) >= contrast_ratio("#FFFFFF", hex_color) else "#FFFFFF"


def _adjust_lightness(hex_color: str, delta: float) -> str:
    hue, lightness, saturation = _to_hls(hex_color)
    return _from_hls(hue, lightness + delta, saturation)


def ensure_contrast(hex_color: str, minimum: float = 3.0, background: str = "#FFFFFF") -> str:
    """
    Escurece (ou clareia) a cor até passar do contraste mínimo no fundo dado.

    É o que impede um cliente de marca amarela de receber um gráfico
    invisível: o traço fica num tom mais escuro do MESMO matiz, então
    continua sendo a cor da marca, só que legível.
    """
    if contrast_ratio(hex_color, background) >= minimum:
        return hex_color

    hue, lightness, saturation = _to_hls(hex_color)
    background_is_light = _relative_luminance(background) > 0.4
    step = -0.02 if background_is_light else 0.02

    candidate = hex_color
    for _ in range(50):
        lightness += step
        if not 0.0 <= lightness <= 1.0:
            break
        candidate = _from_hls(hue, lightness, max(saturation, 0.35))
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return candidate


# --------------------------------------------------------------------------
# Separação perceptual e simulação de daltonismo
# --------------------------------------------------------------------------
#
# Distância de matiz não serve para escolher cores companheiras: rosa e
# verde-azulado ficam a 150° um do outro e mesmo assim colapsam sob
# deuteranopia. A escolha aqui é feita medindo a separação REAL — ΔE em
# OKLab, calculado também sobre as três simulações de daltonismo.

def _linear_channels(hex_color: str) -> tuple[float, float, float]:
    channels = []
    for value in _rgb(hex_color):
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4)
    return tuple(channels)


def _oklab(hex_color: str) -> tuple[float, float, float]:
    red, green, blue = _linear_channels(hex_color)
    long_ = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
    return (
        0.2104542553 * long_ + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long_ - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long_ + 0.7827717662 * medium - 0.8086757660 * short,
    )


# Matrizes de Viénot, Brettel & Mollon para dicromacia.
_CVD_MATRICES = {
    "protan": ((0.0, 2.02344, -2.52581), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "deutan": ((1.0, 0.0, 0.0), (0.494207, 0.0, 1.24827), (0.0, 0.0, 1.0)),
    "tritan": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-0.395913, 0.801109, 0.0)),
}


def simulate_cvd(hex_color: str, kind: str) -> str:
    """Como a cor é vista por quem tem a dicromacia indicada."""
    red, green, blue = _rgb(hex_color)
    long_ = 17.8824 * red + 43.5161 * green + 4.11935 * blue
    medium = 3.45565 * red + 27.1554 * green + 3.86714 * blue
    short = 0.0299566 * red + 0.184309 * green + 1.46709 * blue

    rows = _CVD_MATRICES[kind]
    lms = [sum(coefficient * channel for coefficient, channel in zip(row, (long_, medium, short)))
           for row in rows]

    out_red = 0.0809444479 * lms[0] - 0.130504409 * lms[1] + 0.116721066 * lms[2]
    out_green = -0.0102485335 * lms[0] + 0.0540193266 * lms[1] - 0.113614708 * lms[2]
    out_blue = -0.000365296938 * lms[0] - 0.00412161469 * lms[1] + 0.693511405 * lms[2]
    return _hex((out_red, out_green, out_blue))


def _delta_e(first: str, second: str) -> float:
    lightness_a, a_a, b_a = _oklab(first)
    lightness_b, a_b, b_b = _oklab(second)
    return 100 * ((lightness_a - lightness_b) ** 2 + (a_a - a_b) ** 2 + (b_a - b_b) ** 2) ** 0.5


def separation(first: str, second: str) -> float:
    """
    Pior separação entre duas cores considerando visão normal e as três
    dicromacias. É o número que decide se um par pode conviver num gráfico.
    """
    scores = [_delta_e(first, second)]
    scores += [
        _delta_e(simulate_cvd(first, kind), simulate_cvd(second, kind))
        for kind in _CVD_MATRICES
    ]
    return min(scores)


# --------------------------------------------------------------------------
# Paleta de séries
# --------------------------------------------------------------------------

# Candidatas companheiras, todas legíveis sobre branco. A escolha entre elas
# é por separação medida, nunca por posição no círculo cromático.
CHROMA_FLOOR = 0.10

_COMPANION_POOL = [
    "#2A78D6",  # azul
    "#EB6834",  # laranja
    "#1BAF7A",  # verde-azulado
    "#7C4DD6",  # violeta
    "#B45309",  # âmbar escuro
    "#C23E8E",  # magenta
    "#0891B2",  # ciano-petróleo
    "#4D7C0F",  # oliva
    "#9333EA",  # púrpura
    "#B91C1C",  # tijolo
]

NEUTRAL_SERIES = "#4B5563"
FALLBACK_PRIMARY_SERIES = "#2A78D6"


def companion_series(primary: str, surface: str = "#FFFFFF") -> list[str]:
    """
    Escolhe as duas cores de apoio maximizando a MENOR separação do trio.

    Testa todos os pares candidatos e fica com o que deixa o par mais fraco
    do conjunto o mais forte possível — inclusive sob daltonismo. É por isso
    que uma marca rosa não recebe verde-azulado de companheira: o par é
    indistinguível para quem tem deuteranopia.
    """
    best_pair: tuple[str, str] | None = None
    best_score = -1.0

    for index, first in enumerate(_COMPANIONS):
        for second in _COMPANIONS[index + 1:]:
            score = min(
                separation(primary, first),
                separation(primary, second),
                separation(first, second),
            )
            if score > best_score:
                best_score, best_pair = score, (first, second)

    first, second = best_pair or (_COMPANIONS[0], _COMPANIONS[2])
    return [ensure_contrast(first, background=surface), ensure_contrast(second, background=surface)]


ACHROMATIC_SATURATION = 0.12


def ordinal_ramp(primary: str, steps: int = 3, surface: str = "#FFFFFF") -> list[str]:
    """
    Rampa de matiz única para o funil, do escuro ao claro.

    Os extremos são definidos por CONTRASTE, não por um valor fixo de
    luminosidade: com base fixa, uma marca amarela produzia um último degrau
    de 1,17:1 — invisível sobre o branco. Aqui o degrau mais claro é
    escurecido até separar do fundo, e o mais escuro até ter peso de leitura.

    Marca sem matiz (preto, cinza) recebe rampa neutra. Forçar saturação num
    tom acinzentado inventaria um matiz que não é do cliente — era o que
    fazia uma marca preta virar um funil azul.
    """
    hue, _, saturation = _to_hls(primary)

    if saturation < ACHROMATIC_SATURATION:
        return [_from_hls(0.0, level, 0.0) for level in (0.20, 0.42, 0.64)][:steps]

    saturation = max(saturation, 0.45)
    darkest = ensure_contrast(_from_hls(hue, 0.30, saturation), 5.0, background=surface)
    lightest = ensure_contrast(_from_hls(hue, 0.66, saturation), 2.2, background=surface)

    low = _to_hls(darkest)[1]
    high = _to_hls(lightest)[1]
    if high <= low:  # matiz muito escuro: abre um intervalo mínimo
        high = min(1.0, low + 0.28)

    span = high - low
    return [
        _from_hls(hue, low + span * index / max(1, steps - 1), saturation)
        for index in range(steps)
    ]


def chroma(hex_color: str) -> float:
    _, green_red, blue_yellow = _oklab(hex_color)
    return (green_red ** 2 + blue_yellow ** 2) ** 0.5


# Candidata sem croma suficiente lê como cinza ao lado das outras e viraria
# uma "quarta série neutra" acidental. O filtro é aplicado na carga do módulo
# para que editar a lista acima nunca reintroduza o problema em silêncio.
_COMPANIONS = [color for color in _COMPANION_POOL if chroma(color) >= CHROMA_FLOOR]


def series_primary(primary: str, surface: str = "#FFFFFF") -> str:
    """
    A cor da marca pronta para virar traço de gráfico.

    Marca acinzentada (preto, grafite, branco) não consegue ser uma cor de
    identidade num gráfico: ao lado de outra série ela lê como "sem cor".
    Nesse caso a primeira série cai para um azul, e o preto segue mandando
    em botão, menu e favicon — que é onde a marca realmente aparece.
    """
    if chroma(primary) < 0.05:
        return ensure_contrast(FALLBACK_PRIMARY_SERIES, background=surface)
    return ensure_contrast(primary, background=surface)


@lru_cache(maxsize=64)
def _computed_palette(primary: str, secondary: str, surface: str = "#FFFFFF") -> dict:
    """
    Cálculo puro e memorizado.

    A busca de companheiras compara todos os pares candidatos sob quatro
    simulações de visão. É barato, mas roda a cada gráfico desenhado — e o
    resultado só depende das duas cores, então cabe em cache.
    """
    data_primary = series_primary(primary, surface)
    companions = companion_series(data_primary, surface)
    red, green, blue = _rgb(primary)

    return {
        "primary": primary,
        "secondary": secondary,
        "hover": _adjust_lightness(primary, -0.07),
        "active": _adjust_lightness(primary, -0.14),
        "tint": f"rgba({red},{green},{blue},.08)",
        "ring": f"rgba({red},{green},{blue},.16)",
        "contrast": readable_ink(primary),
        # Cor da marca já corrigida para servir de traço/barra sobre branco
        "data": data_primary,
        "series": [data_primary, *companions, ensure_contrast(NEUTRAL_SERIES, background=surface)],
        "ordinal": ordinal_ramp(primary, surface=surface),
    }


def brand_palette(primary: str | None, secondary: str | None = None, surface: str | None = None) -> dict:
    """
    Tudo que a interface precisa saber sobre a cor de um cliente.

    `surface` é a cor dos cards: é sobre ela que as séries dos gráficos
    precisam de contraste. Num tema escuro, "corrigir" escurecendo deixaria
    a linha invisível — ali a cor é clareada.
    """
    palette = _computed_palette(
        (primary or DEFAULT_PRIMARY).upper(),
        (secondary or DEFAULT_SECONDARY).upper(),
        (surface or "#FFFFFF").upper(),
    )
    # Cópia rasa com as listas duplicadas: o cache guarda um objeto só e
    # quem consome não pode alterá-lo sem afetar todos os outros pedidos.
    return {**palette, "series": list(palette["series"]), "ordinal": list(palette["ordinal"])}


def brand_for_user(user: dict | None) -> dict:
    if user and user.get("role") == "superadmin":
        return admin_brand()
    if not user or not user.get("tenant_id"):
        return dict(DEFAULT_BRAND)
    return {
        "name": user.get("tenant_name") or "V4 Company",
        "logo_data": user.get("logo_data"),
        "primary_color": user.get("primary_color") or DEFAULT_PRIMARY,
        "secondary_color": user.get("secondary_color") or DEFAULT_SECONDARY,
        "theme": parse_theme(user.get("theme_data")),
    }


def brand_for_tenant(tenant: dict | None) -> dict:
    """Marca a partir do registro do cliente — usada antes do login."""
    if not tenant:
        return dict(DEFAULT_BRAND)
    return {
        "name": tenant.get("name") or "V4 Company",
        "logo_data": tenant.get("logo_data"),
        "primary_color": tenant.get("primary_color") or DEFAULT_PRIMARY,
        "secondary_color": tenant.get("secondary_color") or DEFAULT_SECONDARY,
        "theme": parse_theme(tenant.get("theme_data")),
    }


def _screen_args() -> dict:
    """
    Parâmetros da URL da TELA (`?next=`, `?token=`), não da requisição.

    O documento chega com eles em `request.args`, mas o layout servido e as
    callbacks vêm por `/_dash-*`, sem parâmetro nenhum — a URL da tela está no
    `Referer`. Lendo só `request.args`, o corpo do login de um cliente saía
    com a marca padrão, mesmo com o `<head>` certo.
    """
    from urllib.parse import parse_qs, urlparse

    from flask import request

    if not request.path.startswith("/_dash") or not request.referrer:
        return dict(request.args)
    query = parse_qs(urlparse(request.referrer).query)
    return {key: values[0] for key, values in query.items() if values}


def brand_for_request(pathname: str | None = None) -> dict:
    """
    Marca a aplicar nesta requisição, inclusive SEM sessão.

    Quem já está logado usa a marca da própria conta. Quem ainda não entrou
    pode estar chegando por um caminho que identifica o cliente:

    * `/login?next=/somaxi` — é o redirecionamento que o próprio app emite
      quando alguém abre a URL curta do cliente sem sessão;
    * `/convite?token=…` — o convite sabe de qual cliente é.

    Sem nenhuma dessas pistas, cai na marca padrão. É o que faz a tela de
    login aparecer com a identidade do cliente em vez da nossa.

    `pathname` é a tela que o usuário está vendo. Precisa ser passado de fora
    quando quem pergunta não é a requisição do documento: o layout servido e
    as callbacks chegam por `/_dash-layout` e `/_dash-update-component`, então
    `request.path` ali não diz nada sobre a tela — foi o que fazia o painel de
    clientes continuar pintado com a marca do último cliente.
    """
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return dict(DEFAULT_BRAND)

        from core.auth import active_tenant, current_user, is_superadmin

        if pathname is None:
            pathname = request.path
        pathname = (pathname or "/").split("?")[0].rstrip("/") or "/"

        user = current_user()
        if user:
            if is_superadmin(user):
                # O painel de clientes é tela DA AGÊNCIA, não de um cliente:
                # abrir /admin com a marca do último cliente inspecionado dava
                # a impressão de estar dentro da conta dele.
                if pathname == "/admin":
                    return admin_brand()
                tenant = active_tenant(user)
                # Nas telas de dados o master enxerga a marca do cliente que
                # está inspecionando; sem cliente selecionado, a da agência.
                return brand_for_tenant(tenant) if tenant else admin_brand()
            return brand_for_user(user)

        from core.storage import get_invite, get_tenant_by_slug

        args = _screen_args()
        token = args.get("token")
        if token:
            invite = get_invite(token)
            if invite:
                return brand_for_tenant(invite)

        candidate = args.get("c") or args.get("next") or ""
        slug = candidate.strip("/").split("/")[0].split("?")[0]
        if slug:
            tenant = get_tenant_by_slug(slug)
            if tenant:
                return brand_for_tenant(tenant)
    except Exception:
        # Identidade visual nunca pode derrubar a página.
        pass

    return dict(DEFAULT_BRAND)


# --------------------------------------------------------------------------
# Saída para a interface
# --------------------------------------------------------------------------

def brand_tokens(brand: dict) -> dict[str, str]:
    """
    Todas as variáveis da marca e do tema, como CSS (`color-scheme` com hífen).

    Tema primeiro, marca depois: a cor de ação nunca é sobrescrita pelo tema.
    """
    theme = parse_theme(brand.get("theme"))
    palette = brand_palette(brand.get("primary_color"), brand.get("secondary_color"), theme["surface_color"])
    series = palette["series"]
    ordinal = palette["ordinal"]
    return {
        **theme_tokens(theme),
        "--brand": palette["primary"],
        "--brand-hover": palette["hover"],
        "--brand-active": palette["active"],
        "--brand-tint": palette["tint"],
        "--brand-ring": palette["ring"],
        "--brand-contrast": palette["contrast"],
        "--brand-data": palette["data"],
        "--tenant-accent": palette["secondary"],
        "--series-1": series[0],
        "--series-2": series[1],
        "--series-3": series[2],
        "--series-4": series[3],
        "--ordinal-1": ordinal[0],
        "--ordinal-2": ordinal[1],
        "--ordinal-3": ordinal[2],
    }


def style_variables(brand: dict) -> dict[str, str]:
    """Tokens inline para o elemento raiz — o React quer `colorScheme`."""
    tokens = brand_tokens(brand)
    tokens["colorScheme"] = tokens.pop("color-scheme")
    return tokens


def brand_font_url(brand: dict) -> str | None:
    """Folha do Google Fonts com as fontes do tema desta marca."""
    return google_fonts_url(parse_theme(brand.get("theme")))


def css_variables(brand: dict) -> str:
    """
    Mesmos tokens como texto CSS, para irem no <head>.

    Vai no documento e não só no elemento raiz porque o `<style>` é aplicado
    antes da primeira pintura: sem isso a tela aparece por um instante com o
    vermelho padrão e só depois vira a cor do cliente.
    """
    declarations = "".join(f"{name}:{value};" for name, value in brand_tokens(brand).items())
    return f":root{{{declarations}}}"


def favicon_data_uri(brand: dict) -> str:
    """
    Favicon do cliente: o logo quando existir, senão um quadrado com a
    inicial na cor da marca. Gerado em memória, sem arquivo no disco.
    """
    logo = brand.get("logo_data")
    if logo and logo.startswith("data:image"):
        return logo

    palette = brand_palette(brand.get("primary_color"), brand.get("secondary_color"))
    letter = (brand.get("name") or "P").strip()[:1].upper()
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
        f"<rect width='32' height='32' rx='8' fill='{palette['primary']}'/>"
        f"<text x='16' y='22' font-family='Inter,system-ui,sans-serif' font-size='18' "
        f"font-weight='700' fill='{palette['contrast']}' text-anchor='middle'>{letter}</text>"
        "</svg>"
    )
    from urllib.parse import quote

    return f"data:image/svg+xml,{quote(svg, safe='')}"
