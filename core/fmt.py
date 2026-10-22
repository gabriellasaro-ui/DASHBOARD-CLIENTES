"""
Formatação pt-BR centralizada.

Nada na interface formata número na mão — KPI, tabela, eixo e tooltip passam
por aqui. É o que garante que "R$ 148.320" apareça igual em todo lugar.

Implementado sem `locale` de propósito: o módulo `locale` depende de o SO ter
pt_BR instalado, o que quebra em container e no Windows sem o pacote de idioma.
"""

from __future__ import annotations

from datetime import date, datetime

MESES = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]

MESES_LONGOS = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _group(value: float, decimals: int) -> str:
    """Agrupa milhar com '.' e usa ',' como separador decimal."""
    negative = value < 0
    text = f"{abs(value):,.{decimals}f}"
    # en-US -> pt-BR: troca via marcador temporário para não sobrescrever
    text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" + text) if negative else text


def dec(value: float | None, decimals: int = 2) -> str:
    """4,32"""
    return _group(value or 0, decimals)


def integer(value: float | None) -> str:
    """148.320"""
    return _group(round(value or 0), 0)


def brl(value: float | None, decimals: int = 0) -> str:
    """R$ 148.320"""
    return f"R$ {_group(value or 0, decimals)}"


def brl_cents(value: float | None) -> str:
    """R$ 12,84 — para CPC, CPM, ticket médio."""
    return brl(value, 2)


def pct(value: float | None, decimals: int = 2) -> str:
    """3,84%"""
    return f"{_group(value or 0, decimals)}%"


def compact(value: float | None) -> str:
    """12,9 mil · 4,2 mi — para valores grandes em eixo e KPI."""
    n = value or 0
    magnitude = abs(n)
    if magnitude >= 1_000_000:
        return f"{_group(n / 1_000_000, 1)} mi"
    if magnitude >= 1_000:
        return f"{_group(n / 1_000, 0 if magnitude >= 10_000 else 1)} mil"
    return integer(n)


def brl_compact(value: float | None) -> str:
    """R$ 12,9 mil — versão monetária compacta, usada nos eixos Y."""
    n = value or 0
    magnitude = abs(n)
    if magnitude >= 1_000_000:
        return f"R$ {_group(n / 1_000_000, 1)} mi"
    if magnitude >= 1_000:
        return f"R$ {_group(n / 1_000, 0 if magnitude >= 10_000 else 1)} mil"
    return brl(n)


def delta(value: float | None, decimals: int = 1) -> str:
    """+12,4% · −8,1% (menos tipográfico, não hífen)."""
    n = value or 0
    sign = "+" if n > 0 else ("−" if n < 0 else "")
    return f"{sign}{_group(abs(n), decimals)}%"


def short_date(value) -> str:
    """06 ago"""
    d = _as_date(value)
    return f"{d.day:02d} {MESES[d.month - 1]}"


def long_date(value) -> str:
    """06 ago 2026"""
    d = _as_date(value)
    return f"{d.day:02d} {MESES[d.month - 1]} {d.year}"


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


# Despacho por tipo declarado na métrica — a definição da métrica diz como
# ela deve ser lida, então o componente não precisa saber de formatação.
FORMATTERS = {
    "currency": brl,
    "currency_cents": brl_cents,
    "percent": pct,
    "decimal": dec,
    "compact": compact,
    "int": integer,
}


def by_type(kind: str, value) -> str:
    return FORMATTERS.get(kind, integer)(value)
