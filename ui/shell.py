"""
Shell da aplicação: sidebar, topbar e os popovers do topo.

O shell é montado uma única vez em `app.py` e permanece entre navegações —
só o miolo troca. Isso mantém a sidebar estável (sem piscar a cada clique) e
deixa o filtro de período e o seletor de métricas acima das páginas, que é
onde eles pertencem: são escolhas do cliente, não da tela.

Detalhe de implementação que vale registrar: todo popover já nasce no HTML,
apenas com a classe `hide`. Abrir e fechar é trocar classe, nunca criar ou
destruir componente — se o elemento não existisse, a callback que escuta o
clique dele não teria como ser acionada. O clique-fora é resolvido por um
"scrim" transparente em tela cheia atrás do menu, sem depender de JavaScript.
"""

from __future__ import annotations

from dash import dcc, html

from core.mock import ACCOUNT, METRIC_LABELS, METRIC_KEYS, PERIODS
from ui.icons import icon
from ui.platforms import platform_mark
from ui.primitives import avatar, badge, button, classes, logo

NAV_MAIN = [
    ("/", "Dashboard", "layout-dashboard"),
    ("/meta-ads", "Meta Ads", "brand-meta"),
    ("/google-ads", "Google Ads", "brand-google"),
]

NAV_WORK = []

# Conta: só para quem pode mudar a aparência da empresa (responsável e
# master). O visualizador não vê o item — a tela existe, mas só diria "não".
NAV_ACCOUNT = [("/aparencia", "Aparência", "palette")]

ALL_NAV = NAV_MAIN + NAV_WORK + NAV_ACCOUNT
PAGE_TITLES = {path: label for path, label, _ in ALL_NAV}


def nav_class(href: str, pathname: str) -> str:
    return classes("nav-item", "nav-item--active" if href == pathname else None)


def brand_logo(brand: dict | None = None):
    """A logo do topo da sidebar, trocável sem refazer o documento."""
    brand = brand or {"name": "V4 Company", "logo_data": None}
    return logo(brand_name=brand.get("name") or "V4 Company", logo_data=brand.get("logo_data"))


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------

def _nav_item(href, label, glyph, pathname, count=None):
    lead = platform_mark(glyph.removeprefix("brand-"), 20) if glyph.startswith("brand-") else icon(glyph, 20)
    return dcc.Link(
        [
            lead,
            html.Span(label, className="nav-item__label"),
            html.Span(count, className="nav-item__badge") if count else None,
        ],
        href=href,
        className=nav_class(href, pathname),
        id={"type": "nav-link", "href": href},
        title=label,
    )


def sidebar(pathname: str = "/", user: dict | None = None, brand: dict | None = None):
    from core.auth import initials

    brand = brand or {"name": "V4 Company", "logo_data": None}
    user = user or {
        "name": ACCOUNT["gestor"],
        "email": ACCOUNT["email"],
        "role": "client",
    }
    navigation = list(NAV_MAIN)
    work_navigation = list(NAV_WORK)
    account_navigation = list(NAV_ACCOUNT) if user.get("role") in ("client_admin", "superadmin") else []
    if user.get("role") == "superadmin":
        navigation = [("/admin", "Clientes", "building-2"), *NAV_MAIN]

    return html.Aside(
        [
            html.Div(
                [
                    # Id próprio: a marca muda ao entrar e sair de /admin, e a
                    # navegação do Dash não refaz o documento.
                    html.Div(brand_logo(brand), id="brand-logo"),
                    html.Div(
                        [
                            # Chevron em vez do glifo de painel: a seta diz
                            # para que lado o menu vai, o painel não dizia.
                            html.Button(
                                icon("chevron-right", 19),
                                id="sidebar-resize",
                                n_clicks=0,
                                className="btn btn--ghost btn--icon sidebar__resize",
                                **{"aria-label": "Expandir menu", "title": "Expandir menu"},
                            ),
                            html.Button(
                                icon("x", 19),
                                id="drawer-close",
                                n_clicks=0,
                                className="btn btn--ghost btn--icon drawer-toggle",
                                **{"aria-label": "Fechar menu"},
                            ),
                        ],
                        className="sidebar__brand-actions",
                    ),
                ],
                className="sidebar__brand",
            ),
            html.Nav(
                [
                    html.Div("Visão geral", className="sidebar__section", style={"paddingTop": "0"}),
                    *[_nav_item(h, l, g, pathname) for h, l, g in navigation],
                    html.Div("Operação", className="sidebar__section") if work_navigation else None,
                    *[
                        _nav_item(h, l, g, pathname, count="14" if h == "/campanhas" else None)
                        for h, l, g in work_navigation
                    ],
                    html.Div("Conta", className="sidebar__section") if account_navigation else None,
                    *[_nav_item(h, l, g, pathname) for h, l, g in account_navigation],
                ],
                className="sidebar__nav",
            ),
            html.Div(
                [
                    html.Button(
                        [
                            avatar(initials(user.get("name")), "sm"),
                            html.Span(
                                [
                                    html.Span(
                                        user.get("name", "Usuário"),
                                        style={"display": "block", "fontSize": "12px",
                                               "fontWeight": "500", "color": "var(--ink)"},
                                    ),
                                    html.Span(
                                        "Administrador" if user.get("role") == "superadmin" else "Gestor da conta",
                                        className="t-micro",
                                              style={"fontSize": "10px"}),
                                ],
                                className="sidebar__account-text grow truncate",
                            ),
                            icon("chevron-up", 16, style={"color": "var(--ink-faint)"}),
                        ],
                        id="user-trigger",
                        n_clicks=0,
                        className="sidebar__account",
                        title=user.get("name", "Usuário"),
                    ),
                    html.Div(id="user-scrim", n_clicks=0, className="scrim hide"),
                    html.Div(
                        _user_menu_items(user),
                        id="user-menu",
                        className="pop hide",
                        style={"width": "236px", "bottom": "100%", "marginBottom": "8px", "left": "0"},
                    ),
                ],
                className="sidebar__footer",
            ),
        ],
        className="sidebar sidebar--compact",
        id="sidebar",
    )


def _user_menu_items(user: dict | None = None):
    from core.auth import initials

    user = user or {"name": ACCOUNT["gestor"], "email": ACCOUNT["email"]}
    return [
        html.Div(
            [
                avatar(initials(user.get("name")), "md"),
                html.Div(
                    [
                        html.Div(user.get("name", "Usuário"),
                                 style={"fontSize": "13px", "fontWeight": "500", "color": "var(--ink)"}),
                        html.Div(user.get("email", ""), className="t-micro truncate", style={"fontSize": "10px"}),
                    ],
                    className="grow",
                    style={"minWidth": "0"},
                ),
            ],
            className="row gap-3",
            style={"padding": "8px 10px 12px"},
        ),
        html.Div(className="pop__sep"),
        # Âncora comum, NÃO `dcc.Link`: sair é uma rota do Flask, não uma
        # página do Dash. O `dcc.Link` sequestra o clique e só troca a URL no
        # navegador, então `/logout` nunca era executado — a sessão continuava
        # aberta e a tela ficava num 404 em vez de voltar para o login.
        html.A(
            [icon("log-out", 18), html.Span("Sair da conta", className="pop__item-text")],
            href="/logout",
            className="pop__item pop__item--danger",
        ),
    ]


# --------------------------------------------------------------------------
# Filtro de período
# --------------------------------------------------------------------------

def period_control(period_id: str):
    """Dropdown compacto para comportar períodos curtos e calendários longos."""
    return dcc.Dropdown(
        id="period-select",
        options=[{"label": period["label"], "value": period["id"]} for period in PERIODS],
        value=period_id,
        clearable=False,
        searchable=False,
        className="select period-select",
    )


# --------------------------------------------------------------------------
# Seletor de métricas
# --------------------------------------------------------------------------

def metric_menu_items(selected: list[str]):
    """
    Lista de checkboxes em duas colunas. Usa um `dcc.Checklist` único em vez
    de um checkbox por linha para o estado chegar inteiro na callback — e a
    ordem exibida segue sempre METRIC_KEYS, não a ordem de clique.
    """
    return [
        html.Div(
            [
                html.Span("Métricas exibidas", className="pop__label", style={"padding": "4px 6px"}),
                html.Span(
                    f"{len(selected)} de {len(METRIC_KEYS)}",
                    className="t-micro tabular",
                    style={"paddingRight": "6px"},
                ),
            ],
            className="row-between",
        ),
        dcc.Checklist(
            options=[{"label": METRIC_LABELS[key], "value": key} for key in METRIC_KEYS],
            value=[key for key in METRIC_KEYS if key in selected],
            id="metric-checklist",
            className="metric-pick",
            labelClassName="checkbox",
            inputClassName="checkbox__box",
        ),
        html.Div(
            [
                html.Button("Limpar", id="metric-none", n_clicks=0, className="btn btn--ghost btn--sm"),
                html.Button("Selecionar todas", id="metric-all", n_clicks=0,
                            className="btn btn--secondary btn--sm"),
            ],
            className="pop__foot",
        ),
    ]


# --------------------------------------------------------------------------
# Topbar
# --------------------------------------------------------------------------

def account_options(user: dict | None, tenant: dict | None) -> list[dict]:
    from core.auth import is_superadmin
    from core.storage import list_tenants

    if is_superadmin(user):
        items = [
            {"id": item["id"], "nome": item["name"], "plano": "Cliente"}
            for item in list_tenants()
            if item.get("status") == "active"
        ]
        return sorted(items, key=lambda item: item["id"] != (tenant or {}).get("id"))
    if tenant:
        return [{"id": tenant["id"], "nome": tenant["name"], "plano": "Cliente"}]
    return []


def _account_menu_items(accounts: list[dict], active_id=None):
    return [
        html.Div("Trocar de conta", className="pop__label"),
        *[
            html.Button(
                [
                    avatar("".join(w[0] for w in acc["nome"].split()[:2]).upper(), "sm"),
                    html.Span(
                        [
                            html.Span(acc["nome"], className="truncate"),
                            html.Span(f'Plano {acc["plano"]}', className="pop__item-desc"),
                        ],
                        className="pop__item-text",
                    ),
                    icon("check", 16, className="pop__check") if acc["id"] == active_id else None,
                ],
                id={"type": "account-opt", "id": acc["id"]},
                n_clicks=0,
                className=classes("pop__item", "pop__item--selected" if acc["id"] == active_id else None),
            )
            for acc in accounts
        ],
    ]


def topbar(
    pathname: str,
    period_id: str,
    date_range: dict,
    selected_metrics: list[str],
    user: dict | None = None,
    brand: dict | None = None,
    accounts: list[dict] | None = None,
):
    from core import fmt

    user = user or {"role": "client"}
    brand = brand or {"name": ACCOUNT["cliente"]}
    is_admin = user.get("role") == "superadmin"
    accounts = accounts or []
    from core.auth import active_tenant

    # O primeiro da lista NÃO é o ativo quando o master ainda não escolheu.
    active_id = (active_tenant(user) or {}).get("id")

    return html.Header(
        [
            html.Button(
                icon("panel-left-open", 20),
                id="drawer-open",
                n_clicks=0,
                className="btn btn--outline btn--icon drawer-toggle",
                **{"aria-label": "Abrir menu"},
            ),

            html.Div(
                [
                    html.Div(
                        [
                            html.Span(brand["name"] if accounts else "Administração", id="topbar-client"),
                            badge("MASTER" if is_admin else ACCOUNT["plano"], "brand"),
                        ],
                        className="topbar__client",
                    ),
                    html.Div(
                        [
                            html.Span("Clientes" if pathname == "/admin" else PAGE_TITLES.get(pathname, "Dashboard"),
                                      id="topbar-page", className="t-micro"),
                            html.Span("·", className="t-micro"),
                            html.Span(
                                f'{fmt.long_date(date_range["start"])} – {fmt.long_date(date_range["end"])}',
                                id="topbar-range",
                                className="t-micro tabular",
                            ),
                        ],
                        className="row gap-2",
                        style={"marginTop": "2px"},
                    ),
                ],
                className="topbar__identity",
            ),

            html.Div(
                [
                    # ---- Troca de conta ----------------------------------
                    html.Div(
                        [
                            html.Button(
                                [icon("building-2", 18), icon("chevron-down", 16, className="trigger__chevron")],
                                id="account-trigger",
                                n_clicks=0,
                                className="btn btn--outline",
                                style={"padding": "0 10px", "gap": "4px"},
                                **{"aria-label": "Trocar de conta", "title": "Trocar de conta"},
                            ),
                            html.Div(id="account-scrim", n_clicks=0, className="scrim hide"),
                            html.Div(
                                _account_menu_items(accounts, active_id),
                                id="account-menu",
                                className="pop pop--left hide",
                                style={"width": "260px"},
                            ),
                        ],
                        className=classes("pop-anchor", None if is_admin and accounts else "hide"),
                    ),

                    html.Span(className="topbar__sep"),

                    # ---- Seletor de métricas (só faz sentido no dashboard)
                    html.Div(
                        [
                            html.Button(
                                [
                                    icon("sliders-horizontal", 18),
                                    html.Span("Métricas"),
                                    icon("chevron-down", 16, className="trigger__chevron"),
                                ],
                                id="metric-trigger",
                                n_clicks=0,
                                className="trigger",
                            ),
                            html.Div(id="metric-scrim", n_clicks=0, className="scrim hide"),
                            html.Div(
                                metric_menu_items(selected_metrics),
                                id="metric-menu",
                                className="pop pop--right hide",
                                style={"width": "340px"},
                            ),
                        ],
                        className=classes("pop-anchor"),
                        id="metric-anchor",
                    ),

                    # ---- Filtro de período -------------------------------
                    html.Div(period_control(period_id)),

                    button(
                        None,
                        variant="outline",
                        size="icon",
                        lead_icon="refresh-cw",
                        id="refresh-btn",
                        n_clicks=0,
                        className="",
                        **{"aria-label": "Atualizar dados", "title": "Atualizar dados"},
                    ),
                ],
                className="topbar__actions",
            ),
        ],
        className="topbar",
    )


# --------------------------------------------------------------------------
# Carregamento
# --------------------------------------------------------------------------

LOADING_TITLE = "Carregando"
LOADING_DETAIL = "Só um instante"


def loading_screen():
    """
    A MESMA tela de carregamento em todo lugar: entrada, troca de página,
    troca de período e "Atualizar".

    Não cita plataforma nenhuma de propósito — trocar de aba ou abrir o admin
    não consulta Meta nem Google, e a mensagem antiga dizia que sim. O anel
    usa `--brand`, então acompanha a cor do cliente sem refazer o componente.
    `boot_screen_html` em `app.py` desenha a versão estática, antes do React.
    """
    return html.Div(
        [
            html.Div(className="loading-screen__spinner"),
            html.Strong(LOADING_TITLE),
            html.Span(LOADING_DETAIL),
        ],
        className="loading-screen",
        role="status",
        **{"aria-live": "polite"},
    )


def select_client_state():
    """O master abriu uma tela de cliente sem ter escolhido um cliente."""
    from ui.primitives import card, empty_state

    return card(
        empty_state(
            title="Escolha um cliente",
            description=(
                "Selecione um cliente na lista para ver o painel dele. "
                "Nenhum cliente é aberto automaticamente."
            ),
            action=html.A("Ver clientes", href="/admin", className="btn btn--primary btn--sm"),
            glyph="building-2",
        ),
        className="anim-up",
    )


# --------------------------------------------------------------------------
# Cabeçalho de página
# --------------------------------------------------------------------------

def page_head(title, crumbs, description=None, actions=None, glyph=None):
    from ui.primitives import breadcrumb

    return html.Div(
        [
            html.Div(
                [
                    breadcrumb(crumbs),
                    html.Div(
                        [
                            platform_mark(glyph.removeprefix("brand-"), 22)
                            if glyph and glyph.startswith("brand-")
                            else (icon(glyph, 22) if glyph else None),
                            html.H1(title, className="t-page"),
                        ],
                        className="page-head__title",
                        style={"marginTop": "8px"},
                    ),
                    html.P(description, className="t-micro", style={"marginTop": "6px"})
                    if description
                    else None,
                ]
            ),
            html.Div(actions, className="row gap-2") if actions else None,
        ],
        className="page-head",
    )
