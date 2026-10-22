"""
Tabela de dados: ordenação, busca e paginação.

Uma implementação só atende as oito tabelas do produto (campanhas, conjuntos,
anúncios, grupos, palavras-chave…). Cada tabela é declarada em `TABLE_SPECS`
com suas colunas e sua origem de dados; o resto — cabeçalho clicável, filtro,
rodapé, estados vazios — é o mesmo componente.

O estado de cada tabela mora num `dcc.Store` próprio, então duas tabelas na
mesma tela não disputam ordenação nem página.
"""

from __future__ import annotations

from dash import ALL, MATCH, Input, Output, State, callback, ctx, dcc, html

from core import fmt
from core.data import STATUS_LABEL, get_dataset
from core.theme import entity_color
from ui.icons import icon
from ui.primitives import badge, card, classes, empty_state, status_badge, text_input

NUMERIC_TYPES = {"currency", "currency_cents", "percent", "int", "compact", "decimal"}


# --------------------------------------------------------------------------
# Declaração das colunas
# --------------------------------------------------------------------------

def _col(key, label, kind="int", bar=False, width=None):
    return {"key": key, "label": label, "type": kind, "bar": bar, "width": width}


NAME_COL = {"key": "nome", "label": "Nome", "type": "name", "bar": False, "width": "30%"}
STATUS_COL = {"key": "status", "label": "Status", "type": "status", "bar": False, "width": "104px"}

CAMPAIGN_COLUMNS = [
    NAME_COL,
    STATUS_COL,
    _col("investimento", "Investimento", "currency", bar=True),
    _col("cliques", "Cliques", "compact"),
    _col("ctr", "CTR", "percent"),
    _col("cpc", "CPC", "currency_cents"),
    _col("leads", "Leads", "int"),
    _col("cpl", "CPL", "currency_cents"),
]

PLACEMENT_COLUMNS = [
    NAME_COL,
    STATUS_COL,
    _col("investimento", "Investimento", "currency", bar=True),
    _col("impressoes", "Impressões", "compact"),
    _col("cliques", "Cliques", "compact"),
    _col("ctr", "CTR", "percent"),
    _col("cpc", "CPC", "currency_cents"),
    _col("cpm", "CPM", "currency_cents"),
]

META_AD_COLUMNS = [
    {"key": "creative_url", "label": "Criativo", "type": "creative", "bar": False, "width": "96px"},
    NAME_COL,
    STATUS_COL,
    _col("investimento", "Investimento", "currency", bar=True),
    _col("impressoes", "Impressões", "compact"),
    _col("cliques", "Cliques", "compact"),
    _col("ctr", "CTR", "percent"),
    _col("cpc", "CPC", "currency_cents"),
    _col("cpm", "CPM", "currency_cents"),
]

KEYWORD_COLUMNS = [
    {"key": "nome", "label": "Palavra-chave", "type": "name", "bar": False, "width": "26%"},
    {"key": "correspondencia", "label": "Correspondência", "type": "text", "bar": False, "width": "120px"},
    _col("qs", "QS", "int", width="64px"),
    _col("posicao", "Posição méd.", "decimal"),
    _col("investimento", "Investimento", "currency", bar=True),
    _col("impressoes", "Impressões", "compact"),
    _col("cliques", "Cliques", "compact"),
    _col("ctr", "CTR", "percent"),
    _col("cpc", "CPC", "currency_cents"),
]


def _source(*path):
    """Caminho dentro do dataset — ex.: _source('meta', 'adsets')."""

    def resolve(period_id: str):
        node = get_dataset(period_id)
        for key in path:
            node = node[key]
        return node

    return resolve


TABLE_SPECS = {
    "campanhas": {
        "columns": CAMPAIGN_COLUMNS,
        "source": _source("campaigns"),
        "sort": "investimento",
        "placeholder": "Buscar campanha…",
        "empty": "Nenhuma campanha corresponde à busca",
    },
    "meta-campanhas": {
        "columns": CAMPAIGN_COLUMNS,
        "source": _source("meta", "campaigns"),
        "sort": "investimento",
        "placeholder": "Buscar campanha…",
        "empty": "Nenhuma campanha corresponde à busca",
    },
    "meta-conjuntos": {
        "columns": PLACEMENT_COLUMNS,
        "source": _source("meta", "adsets"),
        "sort": "investimento",
        "placeholder": "Buscar conjunto…",
        "empty": "Nenhum conjunto corresponde à busca",
    },
    "meta-anuncios": {
        "columns": META_AD_COLUMNS,
        "source": _source("meta", "ads"),
        "sort": "investimento",
        "placeholder": "Buscar anúncio…",
        "empty": "Nenhum anúncio corresponde à busca",
    },
    "google-campanhas": {
        "columns": CAMPAIGN_COLUMNS,
        "source": _source("google", "campaigns"),
        "sort": "investimento",
        "placeholder": "Buscar campanha…",
        "empty": "Nenhuma campanha corresponde à busca",
    },
    "google-grupos": {
        "columns": PLACEMENT_COLUMNS,
        "source": _source("google", "groups"),
        "sort": "investimento",
        "placeholder": "Buscar grupo de anúncios…",
        "empty": "Nenhum grupo corresponde à busca",
    },
    "google-keywords": {
        "columns": KEYWORD_COLUMNS,
        "source": _source("google", "keywords"),
        "sort": "investimento",
        "placeholder": "Buscar palavra-chave…",
        "empty": "Nenhuma palavra-chave corresponde à busca",
    },
    "google-anuncios": {
        "columns": PLACEMENT_COLUMNS,
        "source": _source("google", "ads"),
        "sort": "investimento",
        "placeholder": "Buscar anúncio…",
        "empty": "Nenhum anúncio corresponde à busca",
    },
}


# --------------------------------------------------------------------------
# Células
# --------------------------------------------------------------------------

def _name_cell(row: dict):
    channel = row.get("canal")
    return html.Td(
        html.Div(
            [
                html.Span(
                    className="channel-dot",
                    style={"background": entity_color(channel)},
                )
                if channel
                else None,
                html.Span(row["nome"], className="td-name__text", title=row["nome"]),
            ],
            className="td-name",
        )
    )


def _creative_cell(row: dict):
    url = row.get("creative_url")
    if not url:
        return html.Td(html.Span("Sem imagem", className="creative-thumb__empty"))
    quality = row.get("creative_quality")
    title = "Ampliar criativo e ver métricas" if quality != "thumbnail" else "Ampliar imagem e ver métricas"
    return html.Td(
        html.Button(
            html.Img(
                src=url,
                alt=f"Criativo do anúncio {row.get('nome', '')}",
                className="creative-thumb__image",
            ),
            id={"type": "ad-preview-open", "ad_id": row.get("id")},
            n_clicks=0,
            className="creative-thumb",
            title=title,
            **{"aria-label": f"Ampliar anúncio {row.get('nome', '')}"},
        ),
        className="creative-cell",
    )


def _value_cell(column: dict, row: dict, peak: float):
    value = row.get(column["key"])
    text = fmt.by_type(column["type"], value)

    if column.get("bar") and peak:
        share = max(4, min(100, (value / peak) * 100))
        return html.Td(
            html.Div(
                [
                    html.Span(text, className="td-strong"),
                    html.Span(
                        html.Span(
                            className="cell-bar__fill",
                            style={"width": f"{share:.0f}%"},
                        ),
                        className="cell-bar__track",
                    ),
                ],
                className="cell-bar",
            ),
            className="td-num",
        )

    strong = column["key"] == "investimento"
    return html.Td(text, className=classes("td-num", "td-strong" if strong else None))


def _row(columns, row, peaks):
    cells = []
    for column in columns:
        kind = column["type"]
        if kind == "name":
            cells.append(_name_cell(row))
        elif kind == "creative":
            cells.append(_creative_cell(row))
        elif kind == "status":
            cells.append(html.Td(status_badge(row["status"], STATUS_LABEL)))
        elif kind == "text":
            cells.append(html.Td(badge(row[column["key"]], "neutral")))
        else:
            cells.append(_value_cell(column, row, peaks.get(column["key"], 0)))
    return html.Tr(cells)


# --------------------------------------------------------------------------
# Cabeçalho, corpo e rodapé
# --------------------------------------------------------------------------

def _head(tid: str, columns, sort_key: str, direction: str):
    cells = []
    for column in columns:
        numeric = column["type"] in NUMERIC_TYPES
        active = column["key"] == sort_key
        arrow = "chevron-up" if (active and direction == "asc") else "chevron-down"

        cells.append(
            html.Th(
                html.Button(
                    [
                        html.Span(column["label"]),
                        icon(arrow, 12, className="th-btn__arrow"),
                    ],
                    id={"type": "tbl-sort", "tid": tid, "col": column["key"]},
                    n_clicks=0,
                    className=classes(
                        "th-btn",
                        "th-btn--num" if numeric else None,
                        "th-btn--active" if active else None,
                    ),
                ),
                style={"width": column["width"]} if column.get("width") else None,
            )
        )
    return html.Tr(cells)


CHANNEL_NAMES = {"meta": "meta ads facebook instagram", "google": "google ads search"}


def _searchable(row: dict) -> str:
    """
    Texto que a busca enxerga.

    Inclui o canal e o status por escolha de produto: as campanhas se chamam
    "[GAD] …" e "[MET] …", e ninguém digita "GAD" — digita "google". Buscar
    só pelo nome deixaria o campo parecendo quebrado.
    """
    parts = [
        str(row.get("nome", "")),
        CHANNEL_NAMES.get(row.get("canal"), ""),
        str(row.get("correspondencia", "")),
        STATUS_LABEL.get(row.get("status"), {}).get("label", ""),
    ]
    return " ".join(parts).lower()


def _apply_state(spec: dict, state: dict):
    """Aplica busca, ordenação e recorte de página — nesta ordem."""
    rows = list(spec["source"](state["period"]))

    query = (state.get("q") or "").strip().lower()
    if query:
        rows = [r for r in rows if query in _searchable(r)]

    status = state.get("status", "all")
    if status != "all":
        rows = [r for r in rows if r.get("status") == status]

    sort_key = state.get("sort") or spec["sort"]
    reverse = state.get("dir", "desc") == "desc"
    rows.sort(key=lambda r: (r.get(sort_key) is None, r.get(sort_key)), reverse=reverse)

    size = int(state.get("size", 10))
    total = len(rows)
    page_count = max(1, -(-total // size))
    page = min(max(1, int(state.get("page", 1))), page_count)

    return rows[(page - 1) * size : page * size], total, page, page_count


def _peaks(rows, columns):
    """Máximo por coluna com barra — a barra é relativa à página exibida."""
    return {
        c["key"]: max((r.get(c["key"], 0) or 0) for r in rows) if rows else 0
        for c in columns
        if c.get("bar")
    }


def _body(spec: dict, state: dict):
    rows, total, page, page_count = _apply_state(spec, state)

    if not rows:
        return html.Tbody(
            html.Tr(
                html.Td(
                    empty_state(
                        title=spec["empty"],
                        description="Ajuste a busca ou selecione outro período no filtro acima.",
                        glyph="search-x",
                    ),
                    colSpan=len(spec["columns"]),
                    style={"padding": "0"},
                )
            )
        )

    peaks = _peaks(rows, spec["columns"])
    return html.Tbody([_row(spec["columns"], row, peaks) for row in rows])


def _page_numbers(page: int, page_count: int):
    """1 … 4 5 6 … 12 — no máximo sete posições, sem perder o contexto."""
    if page_count <= 7:
        return list(range(1, page_count + 1))
    if page <= 4:
        return [1, 2, 3, 4, 5, "…", page_count]
    if page >= page_count - 3:
        return [1, "…", *range(page_count - 4, page_count + 1)]
    return [1, "…", page - 1, page, page + 1, "…", page_count]


def _footer(tid: str, spec: dict, state: dict):
    rows, total, page, page_count = _apply_state(spec, state)
    size = int(state.get("size", 10))
    first = 0 if total == 0 else (page - 1) * size + 1
    last = min(page * size, total)

    def arrow(target, glyph, label, disabled):
        return html.Button(
            icon(glyph, 14),
            id={"type": "tbl-page", "tid": tid, "page": target},
            n_clicks=0,
            className=classes("pager__btn", "pager__btn--arrow", "pager__btn--disabled" if disabled else None),
            **{"aria-label": label},
        )

    numbers = []
    for entry in _page_numbers(page, page_count):
        if entry == "…":
            numbers.append(html.Span("…", className="pager__gap"))
        else:
            numbers.append(
                html.Button(
                    str(entry),
                    id={"type": "tbl-page", "tid": tid, "page": entry},
                    n_clicks=0,
                    className=classes("pager__btn", "pager__btn--active" if entry == page else None),
                )
            )

    return [
        html.Div(
            [
                html.Span(
                    f"{fmt.integer(first)}–{fmt.integer(last)} de {fmt.integer(total)}",
                    className="pager__info",
                ),
                html.Span(style={"width": "1px", "height": "12px", "background": "var(--line)"}),
                html.Div(
                    [
                        html.Span("Exibir", className="pager__info"),
                        html.Div(
                            [
                                html.Button(
                                    str(n),
                                    id={"type": "tbl-size", "tid": tid, "value": n},
                                    n_clicks=0,
                                    className=classes(
                                        "segmented__item",
                                        "segmented__item--active" if n == size else None,
                                    ),
                                    style={"height": "24px", "padding": "0 8px"},
                                )
                                for n in (10, 25, 50)
                            ],
                            className="segmented",
                        ),
                    ],
                    className="row gap-2",
                ),
            ],
            className="row gap-3",
        ),
        html.Nav(
            [
                arrow(max(1, page - 1), "chevron-left", "Página anterior", page <= 1),
                *numbers,
                arrow(min(page_count, page + 1), "chevron-right", "Próxima página", page >= page_count),
            ],
            className="pager__nav",
            **{"aria-label": "Paginação"},
        ),
    ]


# --------------------------------------------------------------------------
# Componente público
# --------------------------------------------------------------------------

def data_table(tid: str, period_id: str, title: str, subtitle: str = None, actions=None):
    spec = TABLE_SPECS[tid]
    state = {
        "period": period_id, "sort": spec["sort"], "dir": "desc",
        "page": 1, "size": 10, "q": "", "status": "all",
    }

    return card(
        [
            dcc.Store(id={"type": "tbl-state", "tid": tid}, data=state),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(title, className="card__title"),
                            html.P(subtitle, className="card__subtitle") if subtitle else None,
                        ],
                        className="card__title-wrap",
                    ),
                    html.Div(
                        [
                            dcc.Dropdown(
                                id={"type": "tbl-status", "tid": tid},
                                options=[
                                    {"label": "Todos os status", "value": "all"},
                                    {"label": "Ativos", "value": "active"},
                                    {"label": "Pausados", "value": "paused"},
                                    {"label": "Encerrados", "value": "ended"},
                                ],
                                value="all",
                                clearable=False,
                                searchable=False,
                                className="select table-status-filter",
                            ),
                            text_input(
                                placeholder=spec["placeholder"],
                                lead_icon="search",
                                id={"type": "tbl-q", "tid": tid},
                                value="",
                                className="input--sm",
                                style={"width": "220px"},
                            ),
                            actions,
                        ],
                        className="row gap-2",
                    ),
                ],
                className="table-toolbar",
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            _head(tid, spec["columns"], state["sort"], state["dir"]),
                            id={"type": "tbl-head", "tid": tid},
                        ),
                        html.Tbody(id={"type": "tbl-body", "tid": tid}, children=_body(spec, state).children),
                    ],
                    className="table",
                ),
                className="table-scroll",
            ),
            html.Div(_footer(tid, spec, state), id={"type": "tbl-foot", "tid": tid}, className="pager"),
        ]
    )


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------

@callback(
    Output({"type": "tbl-state", "tid": MATCH}, "data"),
    Input({"type": "tbl-sort", "tid": MATCH, "col": ALL}, "n_clicks"),
    Input({"type": "tbl-q", "tid": MATCH}, "value"),
    Input({"type": "tbl-status", "tid": MATCH}, "value"),
    Input({"type": "tbl-page", "tid": MATCH, "page": ALL}, "n_clicks"),
    Input({"type": "tbl-size", "tid": MATCH, "value": ALL}, "n_clicks"),
    State({"type": "tbl-state", "tid": MATCH}, "data"),
    prevent_initial_call=True,
)
def _update_state(_sorts, query, status, _pages, _sizes, state):
    """
    Traduz a interação em novo estado. É a única callback que escreve no store
    da tabela — assim não existe caminho em que ordenação e página se
    sobrescrevam mutuamente.
    """
    state = dict(state or {})
    trigger = ctx.triggered_id
    kind = trigger.get("type") if isinstance(trigger, dict) else None

    if kind == "tbl-sort":
        column = trigger["col"]
        if state.get("sort") == column:
            # segundo clique na mesma coluna inverte; não existe terceira ordem
            state["dir"] = "asc" if state.get("dir") == "desc" else "desc"
        else:
            state["sort"] = column
            state["dir"] = "desc"
        state["page"] = 1

    elif kind == "tbl-page":
        state["page"] = trigger["page"]

    elif kind == "tbl-size":
        state["size"] = int(trigger["value"])
        state["page"] = 1

    elif kind == "tbl-q":
        state["q"] = query or ""
        state["page"] = 1  # busca nova sempre volta para a primeira página

    elif kind == "tbl-status":
        state["status"] = status or "all"
        state["page"] = 1

    return state


@callback(
    Output({"type": "tbl-head", "tid": MATCH}, "children"),
    Output({"type": "tbl-body", "tid": MATCH}, "children"),
    Output({"type": "tbl-foot", "tid": MATCH}, "children"),
    Input({"type": "tbl-state", "tid": MATCH}, "data"),
    prevent_initial_call=True,
)
def _render(state):
    tid = ctx.triggered_id["tid"]
    spec = TABLE_SPECS[tid]
    return (
        _head(tid, spec["columns"], state.get("sort"), state.get("dir", "desc")),
        _body(spec, state).children,
        _footer(tid, spec, state),
    )
