"""
Tema completo do cliente: fonte, cores de texto e de fundo, cards, menu
lateral e arredondamento.

O administrador escolhe poucas coisas e o resto é DERIVADO daqui — os quatro
tons de texto, as três linhas, as superfícies afundadas, os realces de hover,
as sombras e o modo claro/escuro. É o que deixa o painel inteiro coerente
com qualquer combinação: escolher um fundo grafite não deixa nenhuma borda
cinza-clara, nenhum texto preto e nenhuma sombra errada para trás.

Duas regras que a escolha NÃO pode quebrar:

* **Legibilidade.** Texto sobre o fundo e sobre os cards precisa de 4,5:1
  (WCAG AA). Combinação abaixo disso é recusada no salvar, com o número.
* **O menu lateral se ajusta sozinho.** A cor do texto dele não é escolhida:
  sai da própria cor do menu, para um menu escuro nunca ficar com texto
  escuro.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# chave -> (rótulo, pilha CSS, família no Google Fonts ou None)
FONTS: dict[str, tuple[str, str, str | None]] = {
    "inter": ("Inter", "'Inter', system-ui, sans-serif", "Inter"),
    "roboto": ("Roboto", "'Roboto', system-ui, sans-serif", "Roboto"),
    "open-sans": ("Open Sans", "'Open Sans', system-ui, sans-serif", "Open Sans"),
    "lato": ("Lato", "'Lato', system-ui, sans-serif", "Lato"),
    "poppins": ("Poppins", "'Poppins', system-ui, sans-serif", "Poppins"),
    "montserrat": ("Montserrat", "'Montserrat', system-ui, sans-serif", "Montserrat"),
    "nunito": ("Nunito", "'Nunito', system-ui, sans-serif", "Nunito"),
    "dm-sans": ("DM Sans", "'DM Sans', system-ui, sans-serif", "DM Sans"),
    "manrope": ("Manrope", "'Manrope', system-ui, sans-serif", "Manrope"),
    "plus-jakarta": ("Plus Jakarta Sans", "'Plus Jakarta Sans', system-ui, sans-serif", "Plus Jakarta Sans"),
    "work-sans": ("Work Sans", "'Work Sans', system-ui, sans-serif", "Work Sans"),
    "outfit": ("Outfit", "'Outfit', system-ui, sans-serif", "Outfit"),
    "sora": ("Sora", "'Sora', system-ui, sans-serif", "Sora"),
    "space-grotesk": ("Space Grotesk", "'Space Grotesk', system-ui, sans-serif", "Space Grotesk"),
    "ibm-plex": ("IBM Plex Sans", "'IBM Plex Sans', system-ui, sans-serif", "IBM Plex Sans"),
    "raleway": ("Raleway", "'Raleway', system-ui, sans-serif", "Raleway"),
    "merriweather": ("Merriweather (serifada)", "'Merriweather', Georgia, serif", "Merriweather"),
    "playfair": ("Playfair Display (serifada)", "'Playfair Display', Georgia, serif", "Playfair Display"),
    "system": ("Fonte do sistema", "system-ui, -apple-system, 'Segoe UI', sans-serif", None),
}

# chave -> (rótulo, card, controle, pequeno) em px
RADII: dict[str, tuple[str, int, int, int]] = {
    "reto": ("Retos", 6, 4, 3),
    "suave": ("Suaves", 18, 10, 8),
    "arredondado": ("Arredondados", 26, 14, 10),
}

DEFAULT_THEME = {
    "font_body": "inter",
    "font_heading": "inter",
    "text_color": "#0B0B0D",
    "background_color": "#FFFFFF",
    "surface_color": "#FFFFFF",
    "sidebar_color": "#FAFAFB",
    "radius": "suave",
}

COLOR_KEYS = ("text_color", "background_color", "surface_color", "sidebar_color")

# Pontos de partida: escolher um preenche os campos, e dali cada cor ainda
# pode ser ajustada. Todos passam na regra de contraste.
PRESETS: dict[str, dict] = {
    "claro": {"label": "Claro", **{key: DEFAULT_THEME[key] for key in COLOR_KEYS}},
    "gelo": {"label": "Gelo", "text_color": "#101828", "background_color": "#F2F4F7",
             "surface_color": "#FFFFFF", "sidebar_color": "#FFFFFF"},
    "areia": {"label": "Areia", "text_color": "#2B2118", "background_color": "#F6F1EA",
              "surface_color": "#FFFDF9", "sidebar_color": "#EFE6DA"},
    "menu-escuro": {"label": "Menu escuro", "text_color": "#0B0B0D", "background_color": "#F5F6F8",
                    "surface_color": "#FFFFFF", "sidebar_color": "#111318"},
    "grafite": {"label": "Grafite", "text_color": "#F1F2F4", "background_color": "#1C1F24",
                "surface_color": "#252931", "sidebar_color": "#16181C"},
    "escuro": {"label": "Escuro", "text_color": "#E8EAED", "background_color": "#0F1115",
               "surface_color": "#171A21", "sidebar_color": "#0B0D11"},
    "azul-noite": {"label": "Azul-noite", "text_color": "#E6EEF9", "background_color": "#0B1526",
                   "surface_color": "#12203A", "sidebar_color": "#08101E"},
}

MIN_TEXT_CONTRAST = 4.5


# --------------------------------------------------------------------------
# Leitura e validação
# --------------------------------------------------------------------------

def parse_theme(raw) -> dict:
    """
    Tema guardado no banco, sempre completo e válido — nunca levanta erro.

    Serve para LER: chave desconhecida some, valor inválido volta ao padrão.
    Um tema corrompido no banco não pode derrubar o painel do cliente.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}

    theme = dict(DEFAULT_THEME)
    for key in COLOR_KEYS:
        value = str(raw.get(key) or "").strip()
        if HEX_COLOR.fullmatch(value):
            theme[key] = value.upper()
    for key in ("font_body", "font_heading"):
        if raw.get(key) in FONTS:
            theme[key] = raw[key]
    if raw.get("radius") in RADII:
        theme["radius"] = raw["radius"]
    return theme


def clean_theme(raw) -> dict:
    """
    Tema vindo do formulário, para GRAVAR: valida e explica o que está errado.

    Cor digitada pela metade é erro aqui (no `parse_theme` ela seria trocada
    em silêncio pelo padrão, e o administrador salvaria algo que não escolheu).
    """
    raw = raw if isinstance(raw, dict) else {}
    labels = {
        "text_color": "cor do texto", "background_color": "cor de fundo",
        "surface_color": "cor dos cards", "sidebar_color": "cor do menu lateral",
    }
    for key in COLOR_KEYS:
        value = str(raw.get(key) or "").strip()
        if value and not HEX_COLOR.fullmatch(value):
            raise ValueError(f"A {labels[key]} precisa estar no formato #RRGGBB.")
    for key in ("font_body", "font_heading"):
        if raw.get(key) and raw[key] not in FONTS:
            raise ValueError("Fonte não disponível.")
    if raw.get("radius") and raw["radius"] not in RADII:
        raise ValueError("Arredondamento inválido.")

    theme = parse_theme(raw)
    problem = contrast_problem(theme)
    if problem:
        raise ValueError(problem)
    return theme


def contrast_problem(theme: dict) -> str | None:
    """Texto pouco legível sobre o fundo ou sobre os cards, com o número."""
    from core.branding import contrast_ratio

    for key, where in (("background_color", "o fundo"), ("surface_color", "os cards")):
        ratio = contrast_ratio(theme["text_color"], theme[key])
        if ratio < MIN_TEXT_CONTRAST:
            return (
                f"O texto fica pouco legível sobre {where}: contraste de "
                f"{ratio:.1f}:1, o mínimo é {MIN_TEXT_CONTRAST:.1f}:1. "
                "Escureça o texto ou clareie o fundo (ou o contrário)."
            )
    return None


def dumps(theme: dict) -> str:
    return json.dumps(parse_theme(theme), sort_keys=True)


# --------------------------------------------------------------------------
# Fontes
# --------------------------------------------------------------------------

def font_stack(key: str) -> str:
    return FONTS.get(key, FONTS["inter"])[1]


def google_fonts_url(theme: dict) -> str | None:
    """Uma folha do Google Fonts com as famílias que o tema usa."""
    families = []
    for key in (theme.get("font_body"), theme.get("font_heading")):
        family = FONTS.get(key or "", (None, None, None))[2]
        if family and family not in families:
            families.append(family)
    if not families:
        return None
    query = "&".join(f"family={quote_plus(family)}:wght@400;500;600;700" for family in families)
    return f"https://fonts.googleapis.com/css2?{query}&display=swap"


def font_options() -> list[dict]:
    return [{"label": label, "value": key} for key, (label, _, _) in FONTS.items()]


def radius_options() -> list[dict]:
    return [{"label": label, "value": key} for key, (label, *_rest) in RADII.items()]


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def mix(first: str, second: str, amount: float) -> str:
    """`amount` de `second` sobre `first` (0 = só first, 1 = só second)."""
    a, b = _rgb(first), _rgb(second)
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b))


def _alpha(hex_color: str, alpha: float) -> str:
    red, green, blue = _rgb(hex_color)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def is_dark(hex_color: str) -> bool:
    from core.branding import _relative_luminance

    return _relative_luminance(hex_color) < 0.22


def _ink_for(background: str, preferred: str) -> str:
    """A cor de texto escolhida, se ela for legível ali; senão preto ou branco."""
    from core.branding import contrast_ratio, readable_ink

    if contrast_ratio(preferred, background) >= MIN_TEXT_CONTRAST:
        return preferred
    return "#F4F5F7" if readable_ink(background) == "#FFFFFF" else "#0B0B0D"


def _ink_scale(ink: str, surface: str, prefix: str) -> dict[str, str]:
    """Os quatro tons de texto e as linhas, todos misturados ao fundo real."""
    return {
        f"--{prefix}ink": ink,
        f"--{prefix}ink-secondary": mix(ink, surface, 0.32),
        f"--{prefix}ink-muted": mix(ink, surface, 0.46),
        f"--{prefix}ink-faint": mix(ink, surface, 0.61),
        f"--{prefix}line": mix(surface, ink, 0.10),
        f"--{prefix}line-soft": mix(surface, ink, 0.065),
        f"--{prefix}line-strong": mix(surface, ink, 0.17),
        f"--{prefix}wash-1": _alpha(ink, 0.03 if not is_dark(surface) else 0.05),
        f"--{prefix}wash-2": _alpha(ink, 0.055 if not is_dark(surface) else 0.085),
        f"--{prefix}wash-3": _alpha(ink, 0.08 if not is_dark(surface) else 0.12),
    }


def theme_tokens(raw) -> dict[str, str]:
    """
    Todas as variáveis CSS do tema, prontas para o elemento raiz.

    Calculadas aqui, e não com `color-mix()` no CSS, porque o tema é aplicado
    no `#app-root` e uma variável derivada declarada no `:root` seria
    resolvida com as cores do `:root` — o menu continuaria cinza-claro num
    tema escuro.
    """
    theme = parse_theme(raw)
    text = theme["text_color"]
    plane = theme["background_color"]
    surface = theme["surface_color"]
    sidebar = theme["sidebar_color"]
    dark = is_dark(surface)
    shadow = "#000000" if dark else text
    sunken = mix(surface, text, 0.035 if not dark else 0.06)
    _, card, control, small = RADII[theme["radius"]]

    tokens = {
        "color-scheme": "dark" if is_dark(plane) else "light",
        "--plane": plane,
        "--surface": surface,
        "--surface-raised": surface if not dark else mix(surface, text, 0.04),
        "--surface-sunken": sunken,
        "--surface-hover": sunken,
        "--surface-tint": sidebar,
        **_ink_scale(text, surface, ""),
        "--grid": mix(surface, text, 0.065),
        "--axis": mix(surface, text, 0.10),
        "--shadow-card": f"0 1px 2px {_alpha(shadow, 0.04 if not dark else 0.30)}, "
                         f"0 1px 3px {_alpha(shadow, 0.03 if not dark else 0.20)}",
        "--shadow-card-hover": f"0 4px 16px -6px {_alpha(shadow, 0.12 if not dark else 0.45)}, "
                               f"0 2px 4px {_alpha(shadow, 0.04 if not dark else 0.25)}",
        "--shadow-pop": f"0 16px 40px -12px {_alpha(shadow, 0.18 if not dark else 0.55)}, "
                        f"0 0 0 1px {_alpha(text, 0.05 if not dark else 0.10)}",
        "--focus-ring": f"0 0 0 3px {_alpha(text, 0.10 if not dark else 0.22)}",
        "--topbar-bg": _alpha(plane, 0.97),
        "--overlay-bg": _alpha(plane, 0.94),
        "--font": font_stack(theme["font_body"]),
        "--font-heading": font_stack(theme["font_heading"]),
        "--r-card": f"{card}px",
        "--r-control": f"{control}px",
        "--r-sm": f"{small}px",
        # Menu lateral: tinta própria, derivada da cor dele.
        "--sidebar-bg": sidebar,
        "--sidebar-raised": mix(sidebar, _ink_for(sidebar, text), 0.06),
        **_ink_scale(_ink_for(sidebar, text), sidebar, "sidebar-"),
    }
    return tokens
