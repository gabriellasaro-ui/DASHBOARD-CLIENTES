"""
Painel master: lista de clientes e o detalhe de um cliente.

A tela tem DOIS estados, nunca os dois ao mesmo tempo:

* **Lista** — todos os clientes, com um lápis por linha.
* **Detalhe** — abre no lápis (ou em "Novo cliente") e ocupa a tela inteira.

O desenho anterior mantinha três formulários visíveis em paralelo (criar,
editar, acessos) e obrigava a escolher um seletor de cliente separado do que
já estava na tabela — dava para começar a editar o cliente errado. Aqui o
cliente é escolhido uma vez, clicando nele, e tudo que aparece depois é sobre
ele. Formulário só existe quando há um alvo.
"""

from __future__ import annotations

import time

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html

from core.auth import is_superadmin
from core.data import clear_cache
from core.integrations import IntegrationError, google_ads, meta_ads
from core.sync import kickoff_first_sync
from core.storage import (
    ROLE_LABELS,
    create_invite,
    create_tenant,
    delete_tenant,
    delete_user,
    get_tenant,
    list_pending_invites,
    list_tenant_users,
    list_tenants,
    revoke_invite,
    set_user_active,
    set_user_password,
    tenant_stats,
    update_tenant_settings,
)
from ui.icons import icon
from ui.primitives import (
    badge,
    card,
    card_body,
    card_header,
    color_input,
    field,
    form_section,
    text_input,
)
from ui.shell import page_head
from ui.brand_kit import logo_preview as _logo_preview, safe_logo as _safe_logo, toast as _toast
from ui.brand_kit import upload_area as _upload_area
from ui.theme_editor import appearance_section, theme_from_states, theme_states


dash.register_page(__name__, path="/admin", name="Clientes", title="Clientes")


LIST_VIEW = {"mode": "list", "tenant": None}


def _as_view(value) -> dict:
    """
    Normaliza o estado da tela.

    O `dcc.Store` vive no navegador, então o conteúdo chega como entrada
    externa: adulterado ou corrompido, não pode virar erro 500. Qualquer
    coisa fora do formato esperado volta para a lista.
    """
    if not isinstance(value, dict):
        return dict(LIST_VIEW)
    mode = value.get("mode")
    if mode not in ("list", "edit", "new"):
        return dict(LIST_VIEW)
    tenant = value.get("tenant")
    if mode == "edit":
        try:
            tenant = int(tenant)
        except (TypeError, ValueError):
            return dict(LIST_VIEW)
    return {"mode": mode, "tenant": tenant}


# --------------------------------------------------------------------------
# Peças reutilizadas
# --------------------------------------------------------------------------

ACCOUNTS_TTL_SECONDS = 15 * 60

_accounts_cache: dict[str, tuple[float, list]] = {}


def _cached(key: str, loader):
    """
    Lista de contas com validade.

    A carteira de contas da agência muda em dias, não em segundos, mas cada
    abertura do detalhe pedia tudo de novo à Meta e ao Google — 2,5 segundos
    de espera só para montar dois dropdowns, mesmo quando o assunto era
    convidar alguém.
    """
    now = time.time()
    cached = _accounts_cache.get(key)
    if cached and now - cached[0] < ACCOUNTS_TTL_SECONDS:
        return cached[1]
    try:
        value = loader()
    except IntegrationError:
        # Integração fora do ar não derruba a tela; o dropdown fica vazio e
        # o que já estava vinculado continua salvo.
        value = []
    _accounts_cache[key] = (now, value)
    return value


def _account_options():
    meta_options = _cached(
        "meta",
        lambda: [
            {"label": f"{item['name']} · {item['id']}", "value": item["id"]}
            for item in meta_ads.list_ad_accounts()
            if item.get("status") == 1
        ],
    )
    google_options = _cached(
        "google",
        lambda: [
            {"label": f"{item['name']} · {item['id']}", "value": item["id"]}
            for item in google_ads.list_customer_accounts()
            if item.get("status") == "ENABLED"
        ],
    )
    return meta_options, google_options


def _tenant_avatar(tenant: dict, size: str = ""):
    if tenant.get("logo_data"):
        return html.Img(src=tenant["logo_data"], className=f"tenant-logo {size}".strip())
    return html.Span(
        (tenant.get("name") or "?")[:1].upper(),
        className=f"tenant-logo tenant-logo--fallback {size}".strip(),
    )


# --------------------------------------------------------------------------
# Lista
# --------------------------------------------------------------------------

def _stats_strip(stats: dict):
    """
    Os três números num card só.

    Três cards separados para três números ocupavam a largura inteira sem
    dizer mais do que uma linha diz.
    """
    items = [
        ("Clientes", stats["tenants"], "building-2", "ambientes cadastrados"),
        ("Ativos", stats["active"], "badge-check", "com acesso liberado"),
        ("Usuários", stats["users"], "users", "acessos ativos de clientes"),
    ]
    return card(
        html.Div(
            [
                html.Div(
                    [
                        html.Div([icon(glyph, 18), html.Span(title)], className="admin-stat__label"),
                        html.Div(str(value), className="admin-stat__value"),
                        html.Div(detail, className="t-micro"),
                    ],
                    className="admin-stat__item",
                )
                for title, value, glyph, detail in items
            ],
            className="admin-stats",
        ),
        className="admin-stats-card",
    )


def _tenant_row(tenant: dict):
    active = tenant["status"] == "active"
    return html.Tr(
        [
            html.Td(
                html.Div(
                    [
                        _tenant_avatar(tenant),
                        html.Div(
                            [
                                html.Div(tenant["name"], className="td-strong"),
                                html.Div(f"/{tenant['slug']}", className="t-micro"),
                            ]
                        ),
                    ],
                    className="row gap-3",
                )
            ),
            html.Td(tenant.get("owner_email") or "—"),
            html.Td(str(tenant.get("user_count", 0)), className="td-num"),
            html.Td(
                html.Div(
                    [
                        html.Span(style={"background": tenant["primary_color"]}, className="color-dot"),
                        html.Span(tenant["primary_color"], className="tabular"),
                    ],
                    className="row gap-2",
                )
            ),
            html.Td(
                html.Div(
                    [
                        badge("Meta", "positive" if tenant.get("meta_ad_account_id") else "neutral", dot=True),
                        badge("Google", "positive" if tenant.get("google_ads_customer_id") else "neutral", dot=True),
                    ],
                    className="row gap-2",
                )
            ),
            html.Td(
                badge(
                    "Ativo" if active else "Inativo",
                    "positive" if active else "neutral",
                    dot=True,
                )
            ),
            html.Td(
                html.Div(
                    [
                        # O lápis é a porta de entrada da edição: o cliente é
                        # escolhido clicando nele, não num seletor à parte.
                        html.Button(
                            icon("pencil", 17),
                            id={"type": "admin-edit-open", "id": tenant["id"]},
                            n_clicks=0,
                            className="btn btn--outline btn--icon btn--sm",
                            title=f"Editar {tenant['name']}",
                            **{"aria-label": f"Editar {tenant['name']}"},
                        ),
                        html.A(
                            icon("external-link", 17),
                            href=f"/{tenant['slug']}",
                            className="btn btn--ghost btn--icon btn--sm",
                            title="Abrir o painel deste cliente",
                            **{"aria-label": "Abrir painel"},
                        ),
                    ],
                    className="row gap-1",
                    style={"justifyContent": "flex-end"},
                )
            ),
        ]
    )


def _list_view():
    tenants = list_tenants()

    body = (
        [_tenant_row(tenant) for tenant in tenants]
        if tenants
        else [html.Tr(html.Td("Nenhum cliente cadastrado ainda.", colSpan=7,
                              className="admin-table__empty"))]
    )

    return [
        _stats_strip(tenant_stats()),
        card(
            [
                card_header(
                    "Clientes",
                    "Clique no lápis para editar marca, integrações e acessos.",
                    lead_icon="building-2",
                ),
                html.Div(
                    html.Table(
                        [
                            html.Thead(
                                html.Tr(
                                    [
                                        html.Th("Cliente"),
                                        html.Th("Responsável"),
                                        html.Th("Acessos", className="td-num"),
                                        html.Th("Cor"),
                                        html.Th("Integrações"),
                                        html.Th("Status"),
                                        html.Th(""),
                                    ]
                                )
                            ),
                            html.Tbody(body),
                        ],
                        className="table admin-table",
                    ),
                    className="table-scroll",
                ),
            ]
        ),
    ]


# --------------------------------------------------------------------------
# Detalhe
# --------------------------------------------------------------------------

def _identity_card(tenant: dict | None, meta_options, google_options):
    creating = tenant is None
    prefix = "admin-new" if creating else "admin-edit"

    return card(
        [
            card_header(
                "Dados do cliente" if not creating else "Novo cliente",
                "Nome, endereço, identidade visual e contas de mídia."
                if not creating
                else "Crie o ambiente e o primeiro acesso do responsável.",
                lead_icon="building-2",
            ),
            card_body(
                [
                    form_section(
                        "Identificação",
                        html.Div(
                            [
                                field("Nome", text_input("Ex.: Clínica Aurora", "building-2",
                                                         id=f"{prefix}-name",
                                                         value=None if creating else tenant["name"])),
                                field(
                                    "Identificador",
                                    text_input("clinica-aurora", "link-2", id=f"{prefix}-slug",
                                               value=None if creating else tenant["slug"]),
                                    hint="É a URL curta do cliente."
                                    + ("" if creating else " Trocar quebra links já enviados."),
                                ),
                            ],
                            className="form-grid form-grid--2",
                        ),
                        first=True,
                    ),

                    # O acesso do responsável só é definido na criação; depois
                    # ele vive na seção Acessos, com convite e reset de senha.
                    form_section(
                        "Primeiro acesso",
                        [
                            html.Div(
                                [
                                    field("Nome do responsável",
                                          text_input("Nome completo", "user", id="admin-new-owner")),
                                    field("E-mail de acesso",
                                          text_input("gestor@cliente.com", "mail", "email",
                                                     id="admin-new-email")),
                                ],
                                className="form-grid form-grid--2",
                            ),
                            field(
                                "Senha inicial",
                                text_input("Mínimo de 8 caracteres", "lock", "password",
                                           id="admin-new-password"),
                                hint="O responsável pode trocar depois, e você pode redefinir.",
                                className="form-space",
                            ),
                        ],
                        hint="Quem vai administrar o painel deste cliente.",
                    ) if creating else None,

                    form_section(
                        "Identidade visual",
                        [
                            # Empilhadas: cada seletor traz 16 amostras, e lado
                            # a lado elas quebravam em alturas diferentes — era
                            # a origem do desalinhamento.
                            field("Cor principal",
                                  color_input(f"{prefix}-primary",
                                              "#E5001A" if creating else tenant["primary_color"],
                                              group="tenant")),
                            field("Cor de apoio",
                                  color_input(f"{prefix}-secondary",
                                              "#0B0B0D" if creating else tenant["secondary_color"],
                                              group="tenant"),
                                  className="form-space"),
                            html.Div(
                                [
                                    _upload_area(f"{prefix}-logo",
                                                 "Adicionar logo" if creating else "Substituir logo"),
                                    html.Div(
                                        _logo_preview(None if creating else tenant.get("logo_data")),
                                        id=f"{prefix}-logo-preview",
                                    ),
                                ],
                                className="form-space logo-upload",
                            ),
                        ],
                        hint="A cor principal governa botões, gráficos, favicon e a tela de login do cliente.",
                    ),

                    appearance_section(
                        prefix,
                        None if creating else tenant.get("theme_data"),
                        {
                            "name": None if creating else tenant["name"],
                            "logo_data": None if creating else tenant.get("logo_data"),
                            "primary_color": "#E5001A" if creating else tenant["primary_color"],
                            "secondary_color": "#0B0B0D" if creating else tenant["secondary_color"],
                        },
                    ),

                    form_section(
                        "Contas de mídia",
                        html.Div(
                            [
                                field("Meta Ads",
                                      dcc.Dropdown(
                                          id={"type": "account-select", "platform": "meta",
                                              "mode": prefix},
                                          options=meta_options,
                                          value=None if creating else tenant.get("meta_ad_account_id"),
                                          placeholder="Sem conta vinculada", clearable=True,
                                          className="select")),
                                field("Google Ads",
                                      dcc.Dropdown(
                                          id={"type": "account-select", "platform": "google",
                                              "mode": prefix},
                                          options=google_options,
                                          value=None if creating else tenant.get("google_ads_customer_id"),
                                          placeholder="Sem conta vinculada", clearable=True,
                                          className="select")),
                            ],
                            className="form-grid form-grid--2",
                        ),
                        hint="De onde vêm os números deste cliente.",
                    ),

                    form_section(
                        "Status do acesso",
                        dcc.RadioItems(
                            id="admin-edit-status",
                            options=[
                                {"label": "Ativo", "value": "active"},
                                {"label": "Inativo", "value": "inactive"},
                            ],
                            value=tenant["status"] if tenant else "active",
                            className="radio-group",
                            labelClassName="radio-option",
                            inputClassName="radio-option__input",
                        ),
                        hint="Cliente inativo não consegue entrar no painel.",
                    ) if not creating else None,

                    # Ação alinhada à direita, no tamanho normal. Uma barra
                    # vermelha da largura do card virava o elemento mais
                    # pesado da tela, acima do que está sendo configurado.
                    html.Div(
                        [
                            # Excluir fica à ESQUERDA, longe do salvar: são
                            # ações de peso oposto e não podem ser vizinhas.
                            dcc.ConfirmDialogProvider(
                                html.Button(
                                    [icon("trash-2", 17), html.Span("Excluir cliente")],
                                    className="btn btn--danger",
                                ),
                                id="admin-delete-tenant",
                                message=(
                                    f'Excluir "{tenant["name"]}" definitivamente?\n\n'
                                    "Isso apaga os acessos, os convites e todo o histórico de "
                                    "métricas já sincronizado deste cliente. Não há como desfazer.\n\n"
                                    "Para apenas bloquear a entrada, marque o status como Inativo."
                                ),
                            ) if not creating else None,
                            html.Button(
                                [icon("plus" if creating else "check", 18),
                                 html.Span("Criar cliente" if creating else "Salvar alterações")],
                                id="admin-create" if creating else "admin-save",
                                n_clicks=0,
                                className="btn btn--primary",
                            ),
                        ],
                        className="form-actions form-actions--split" if not creating else "form-actions",
                    ),
                ]
            ),
        ]
    )


def _access_rows(users: list[dict]):
    """Uma linha por acesso, com as ações que o master precisa ter à mão."""
    if not users:
        return [html.P("Nenhum acesso cadastrado ainda.", className="t-micro",
                       style={"padding": "14px 20px"})]

    rows = []
    for user in users:
        active = bool(user["active"])
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                [
                                    html.Span(user["name"], className="highlight__name"),
                                    badge(ROLE_LABELS.get(user["role"], user["role"]),
                                          "brand" if user["role"] == "client_admin" else "neutral"),
                                    None if active else badge("Desativado", "warning", dot=True),
                                ],
                                className="row gap-2",
                            ),
                            html.Span(
                                user["email"] + (
                                    f" · também acessa {user['other_tenants']} outro(s) cliente(s)"
                                    if user.get("other_tenants") else ""
                                ),
                                className="highlight__hint",
                            ),
                        ],
                        className="col gap-1 grow",
                        style={"minWidth": "0"},
                    ),
                    html.Div(
                        [
                            # Entrar como alguém troca a sessão no servidor,
                            # então é um link de verdade, não uma callback.
                            html.A(
                                [icon("log-in", 16), html.Span("Entrar como")],
                                href=f"/entrar-como/{user['id']}?cliente={user['tenant_id']}",
                                className="btn btn--outline btn--sm",
                                title=f"Ver o painel como {user['name']}",
                            ) if active else None,
                            html.Button(
                                icon("power", 16),
                                id={"type": "admin-user-toggle", "id": user["id"]},
                                n_clicks=0,
                                className="btn btn--ghost btn--icon btn--sm",
                                title="Desativar acesso" if active else "Reativar acesso",
                                **{"aria-label": "Desativar acesso" if active else "Reativar acesso"},
                            ),
                            # Excluir é diferente de desativar: desativar
                            # suspende o login, excluir apaga a pessoa.
                            dcc.ConfirmDialogProvider(
                                html.Button(
                                    icon("trash-2", 16),
                                    className="btn btn--ghost btn--icon btn--sm btn--icon-danger",
                                    title="Excluir acesso",
                                    **{"aria-label": "Excluir acesso"},
                                ),
                                id={"type": "admin-user-delete", "id": user["id"]},
                                message=(
                                    f"Excluir o acesso de {user['name']} ({user['email']})?\n\n"
                                    "A pessoa perde o login imediatamente. "
                                    "Para apenas suspender, use o botão de desativar."
                                ),
                            ),
                        ],
                        className="row gap-2",
                    ),
                ],
                className="highlight",
                style={"flexDirection": "row", "alignItems": "center", "gap": "14px"},
            )
        )
    return rows


def _invite_rows(invites: list[dict], base_url: str):
    if not invites:
        return []

    rows = [html.Div("Convites pendentes", className="eyebrow",
                     style={"padding": "16px 20px 6px"})]
    for invite in invites:
        link = f"{base_url.rstrip('/')}/convite?token={invite['token']}"
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                [
                                    html.Span(invite["email"], className="highlight__name"),
                                    badge("Expirado", "negative") if invite["expired"]
                                    else badge(ROLE_LABELS.get(invite["role"], invite["role"]), "neutral"),
                                ],
                                className="row gap-2",
                            ),
                            # Sem envio de e-mail, o link É o produto do
                            # convite: fica visível e selecionável.
                            dcc.Input(value=link, readOnly=True, type="text",
                                      className="input input--sm invite-link"),
                        ],
                        className="col gap-2 grow",
                        style={"minWidth": "0"},
                    ),
                    html.Button(
                        icon("trash-2", 16),
                        id={"type": "admin-invite-revoke", "token": invite["token"]},
                        n_clicks=0,
                        className="btn btn--ghost btn--icon btn--sm",
                        title="Revogar convite",
                        **{"aria-label": "Revogar convite"},
                    ),
                ],
                className="highlight",
                style={"flexDirection": "row", "alignItems": "flex-start", "gap": "14px"},
            )
        )
    return rows


def _access_card(tenant: dict):
    return card(
        [
            card_header(
                "Acessos",
                f"Quem entra no painel de {tenant['name']}, e por qual e-mail.",
                lead_icon="users",
            ),
            html.Div(id="admin-access-list"),
            card_body(
                [
                    form_section(
                        "Convidar pessoa",
                        [
                            html.Div(
                                [
                                    field("Nome", text_input("Nome completo", "user",
                                                             id="admin-invite-name")),
                                    field("E-mail", text_input("pessoa@cliente.com", "mail", "email",
                                                               id="admin-invite-email"),
                                          hint="Já tem conta em outro cliente? Ela aceita com a mesma senha."),
                                ],
                                className="form-grid form-grid--2",
                            ),
                            field(
                                "Perfil",
                                dcc.Dropdown(
                                    id="admin-invite-role",
                                    options=[
                                        {"label": "Responsável — administra os acessos", "value": "client_admin"},
                                        {"label": "Visualizador — só consulta o painel", "value": "client"},
                                    ],
                                    value="client",
                                    clearable=False,
                                    className="select",
                                ),
                                className="form-space",
                            ),
                            html.Div(
                                html.Button(
                                    [icon("link-2", 18), html.Span("Gerar convite")],
                                    id="admin-invite-create",
                                    n_clicks=0,
                                    className="btn btn--secondary",
                                ),
                                className="form-actions",
                            ),
                        ],
                        hint=("O convidado escolhe a própria senha pelo link — nenhuma senha "
                              "provisória precisa ser enviada por mensagem."),
                        first=True,
                    ),

                    form_section(
                        "Redefinir senha",
                        [
                            html.Div(
                                [
                                    field(
                                        "Acesso",
                                        dcc.Dropdown(id="admin-reset-user", options=[],
                                                     placeholder="Selecione a pessoa", clearable=True,
                                                     className="select"),
                                    ),
                                    field("Nova senha",
                                          text_input("Mínimo de 8 caracteres", "lock", "password",
                                                     id="admin-reset-password")),
                                ],
                                className="form-grid form-grid--2",
                            ),
                            html.Div(
                                html.Button(
                                    [icon("key-round", 18), html.Span("Definir nova senha")],
                                    id="admin-reset-submit",
                                    n_clicks=0,
                                    className="btn btn--outline",
                                ),
                                className="form-actions",
                            ),
                        ],
                        hint="Use quando alguém perder o acesso e não puder esperar por um convite novo.",
                    ),
                ]
            ),
            html.Div(id="admin-invite-list"),
        ]
    )


def _detail_header(tenant: dict | None):
    return html.Div(
        [
            html.Button(
                [icon("chevron-left", 17), html.Span("Voltar para a lista")],
                id={"type": "admin-nav", "to": "list"},
                n_clicks=0,
                className="btn btn--secondary admin-detail__back",
            ),
            html.Div(
                [
                    _tenant_avatar(tenant, "tenant-logo--lg") if tenant else None,
                    html.Div(
                        [
                            html.Div(tenant["name"] if tenant else "Novo cliente", className="t-page"),
                            html.Div(f"/{tenant['slug']}" if tenant else "Ainda não criado",
                                     className="t-micro"),
                        ]
                    ),
                ],
                className="admin-detail__title",
            ),
        ],
        className="admin-detail__head",
    )


def _current_options(tenant: dict | None, key: str) -> list[dict]:
    """
    Só a conta já vinculada, para o dropdown nascer mostrando o valor certo.

    A lista completa vem depois, por callback: buscá-la aqui deixava a tela
    2,5 segundos em branco antes de aparecer qualquer coisa — inclusive
    quando o motivo de abrir era convidar uma pessoa.
    """
    value = (tenant or {}).get(key)
    return [{"label": value, "value": value}] if value else []


def _detail_view(tenant_id: int | None):
    tenant = get_tenant(int(tenant_id)) if tenant_id else None
    if tenant_id and not tenant:
        return _list_view()

    meta_options = _current_options(tenant, "meta_ad_account_id")
    google_options = _current_options(tenant, "google_ads_customer_id")

    return html.Div(
        [
            _detail_header(tenant),
            _identity_card(tenant, meta_options, google_options),
            _access_card(tenant) if tenant else None,
        ],
        # Na criação existe um card só; sem o modificador ele ficaria com 7/12
        # da tela e o resto vazio.
        className="admin-detail" if tenant else "admin-detail admin-detail--single",
    )


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------

def layout():
    if not is_superadmin():
        return dcc.Location(id="admin-denied", href="/", refresh=True)

    return html.Div(
        [
            dcc.Store(id="admin-view", data=dict(LIST_VIEW)),
            dcc.Store(id="admin-refresh", data=0),
            page_head(
                "Clientes",
                [("Administração", None), ("Clientes", None)],
                "Cada cliente tem o próprio ambiente, marca e acessos.",
                glyph="building-2",
                actions=html.Button(
                    [icon("plus", 18), html.Span("Novo cliente")],
                    id={"type": "admin-nav", "to": "new"},
                    n_clicks=0,
                    className="btn btn--primary btn--sm",
                ),
            ),
            html.Div(id="admin-feedback", className="form-feedback admin-feedback", role="alert"),
            html.Div(id="admin-toast"),
            html.Div(_list_view(), id="admin-content"),
        ],
        className="admin-page",
    )


# --------------------------------------------------------------------------
# Navegação entre lista e detalhe
# --------------------------------------------------------------------------

def _real_click(values) -> bool:
    """
    Botões recriados pela renderização chegam com n_clicks None ou 0.

    Sem esta guarda, redesenhar a lista dispararia a navegação sozinho e a
    tela abriria um cliente que ninguém clicou.
    """
    return any(values or [])


@callback(
    Output("admin-view", "data"),
    Input({"type": "admin-edit-open", "id": ALL}, "n_clicks"),
    Input({"type": "admin-nav", "to": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _navigate(edit_clicks, nav_clicks):
    if not _real_click(list(edit_clicks or []) + list(nav_clicks or [])):
        return dash.no_update

    trigger = ctx.triggered_id
    if not isinstance(trigger, dict):
        return dash.no_update

    if trigger["type"] == "admin-edit-open":
        return {"mode": "edit", "tenant": trigger["id"]}
    if trigger["to"] == "new":
        return {"mode": "new", "tenant": None}
    return dict(LIST_VIEW)


@callback(
    Output("admin-content", "children"),
    Output("admin-feedback", "children", allow_duplicate=True),
    Output("admin-feedback", "className", allow_duplicate=True),
    Input("admin-view", "data"),
    prevent_initial_call=True,
)
def _render_view(view):
    if not is_superadmin():
        return dash.no_update, dash.no_update, dash.no_update

    view = _as_view(view)
    content = _list_view() if view["mode"] == "list" else _detail_view(view["tenant"])
    # Trocar de tela limpa o aviso da tela anterior: "Cliente criado" pairando
    # sobre outro cliente é informação errada.
    return content, "", "form-feedback admin-feedback"


@callback(
    Output("admin-toast", "children"),
    Input("admin-feedback", "children"),
    State("admin-feedback", "className"),
    prevent_initial_call=True,
)
def _confirm_success(message, feedback_class):
    """Todo sucesso do admin (salvar, criar, convidar, excluir) vira o cartão."""
    if not message or "form-feedback--success" not in (feedback_class or ""):
        return None
    return _toast(str(message))


# --------------------------------------------------------------------------
# Criar e salvar
# --------------------------------------------------------------------------

@callback(
    Output("admin-feedback", "children"),
    Output("admin-feedback", "className"),
    Output("admin-view", "data", allow_duplicate=True),
    Input("admin-create", "n_clicks"),
    State("admin-new-name", "value"),
    State("admin-new-slug", "value"),
    State("admin-new-owner", "value"),
    State("admin-new-email", "value"),
    State("admin-new-password", "value"),
    State({"type": "account-select", "platform": "meta", "mode": "admin-new"}, "value"),
    State({"type": "account-select", "platform": "google", "mode": "admin-new"}, "value"),
    # O seletor de cor usa id em dicionário (ver ui.primitives.color_input)
    State({"type": "color-value", "group": "tenant", "for": "admin-new-primary"}, "value"),
    State({"type": "color-value", "group": "tenant", "for": "admin-new-secondary"}, "value"),
    State("admin-new-logo", "contents"),
    *theme_states("admin-new"),
    prevent_initial_call=True,
)
def _create(_clicks, name, slug, owner, email, password, meta, google, primary, secondary, logo, *theme_values):
    if not is_superadmin():
        return "Sessão sem permissão administrativa.", "form-feedback form-feedback--error admin-feedback", dash.no_update
    try:
        created = create_tenant(
            name=name, slug=slug, owner_name=owner, owner_email=email, password=password,
            primary_color=primary, secondary_color=secondary, logo_data=_safe_logo(logo),
            meta_ad_account_id=meta, google_ads_customer_id=google,
            theme=theme_from_states(theme_values),
        )
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error admin-feedback", dash.no_update

    # Busca os dados agora, sem esperar o worker passar.
    kickoff_first_sync(created)
    aviso = (" Os dados das contas estão sendo buscados e aparecem no painel "
             "em alguns minutos." if (meta or google) else "")

    # Abre direto no detalhe do cliente recém-criado: o passo seguinte quase
    # sempre é convidar alguém ou conferir a marca.
    return (
        f"Cliente {created['name']} criado com acesso para {created['owner_email']}.{aviso}",
        "form-feedback form-feedback--success admin-feedback",
        {"mode": "edit", "tenant": created["id"]},
    )


@callback(
    Output("admin-feedback", "children", allow_duplicate=True),
    Output("admin-feedback", "className", allow_duplicate=True),
    Output("admin-refresh", "data", allow_duplicate=True),
    # Depois de salvar, a prévia deixa de dizer "salve para aplicar".
    Output("admin-edit-logo-preview", "children", allow_duplicate=True),
    Input("admin-save", "n_clicks"),
    State("admin-view", "data"),
    State("admin-edit-name", "value"),
    State("admin-edit-slug", "value"),
    State({"type": "account-select", "platform": "meta", "mode": "admin-edit"}, "value"),
    State({"type": "account-select", "platform": "google", "mode": "admin-edit"}, "value"),
    State({"type": "color-value", "group": "tenant", "for": "admin-edit-primary"}, "value"),
    State({"type": "color-value", "group": "tenant", "for": "admin-edit-secondary"}, "value"),
    State("admin-edit-status", "value"),
    State("admin-edit-logo", "contents"),
    State("admin-refresh", "data"),
    *theme_states("admin-edit"),
    prevent_initial_call=True,
)
def _save(_clicks, view, name, slug, meta, google, primary, secondary, status, logo, tick, *theme_values):
    if not is_superadmin():
        return "Sessão sem permissão administrativa.", "form-feedback form-feedback--error admin-feedback", tick, dash.no_update

    tenant_id = _as_view(view)["tenant"]
    if not tenant_id:
        # Sem cliente não há o que salvar, e também não há o que avisar: esse
        # caminho só acontece quando a tela já trocou por baixo (uma exclusão,
        # por exemplo), e o aviso apareceria em vermelho sobre a lista.
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    try:
        current = get_tenant(int(tenant_id))
        updated = update_tenant_settings(
            int(tenant_id),
            name=name,
            slug=slug,
            primary_color=primary,
            secondary_color=secondary,
            # Upload vazio mantém a logo atual em vez de apagá-la.
            logo_data=_safe_logo(logo) if logo else (current or {}).get("logo_data"),
            status=status,
            meta_ad_account_id=meta,
            google_ads_customer_id=google,
            theme=theme_from_states(theme_values),
        )
        clear_cache()
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error admin-feedback", tick, dash.no_update

    # Conta de mídia trocada exige buscar os dados da conta nova; o histórico
    # antigo é de outra conta e não serve.
    contas_mudaram = (
        (current or {}).get("meta_ad_account_id") != updated.get("meta_ad_account_id")
        or (current or {}).get("google_ads_customer_id") != updated.get("google_ads_customer_id")
    )
    if contas_mudaram:
        kickoff_first_sync(updated)

    return (
        f"Cliente {updated['name']} atualizado."
        + (" Buscando os dados da nova conta." if contas_mudaram else ""),
        "form-feedback form-feedback--success admin-feedback",
        (tick or 0) + 1,
        _logo_preview(updated.get("logo_data")),
    )


@callback(
    Output("admin-feedback", "children", allow_duplicate=True),
    Output("admin-feedback", "className", allow_duplicate=True),
    Output("admin-view", "data", allow_duplicate=True),
    Input("admin-delete-tenant", "submit_n_clicks"),
    State("admin-view", "data"),
    prevent_initial_call=True,
)
def _delete_tenant(confirmed, view):
    """Exclusão do cliente, já confirmada pelo diálogo do navegador."""
    if not confirmed:
        return dash.no_update, dash.no_update, dash.no_update
    if not is_superadmin():
        return "Sessão sem permissão administrativa.", "form-feedback form-feedback--error admin-feedback", dash.no_update

    tenant_id = _as_view(view)["tenant"]
    if not tenant_id:
        return dash.no_update, dash.no_update, dash.no_update

    try:
        removed = delete_tenant(int(tenant_id))
        clear_cache()
    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error admin-feedback", dash.no_update

    # O detalhe deixou de existir: volta para a lista, senão a tela ficaria
    # apontando para um cliente que não está mais lá.
    return (
        f"Cliente {removed['name']} excluído.",
        "form-feedback form-feedback--success admin-feedback",
        dict(LIST_VIEW),
    )


@callback(
    Output({"type": "account-select", "platform": ALL, "mode": ALL}, "options"),
    # Dispara no CONTEÚDO renderizado, não na troca de tela: ligada em
    # `admin-view` ela corria junto com a renderização e ia procurar os
    # dropdowns antes de existirem — por isso a carteira não vinha ao criar
    # um cliente. Quando o conteúdo muda, os selects já estão no lugar.
    Input("admin-content", "children"),
    State({"type": "account-select", "platform": ALL, "mode": ALL}, "id"),
    prevent_initial_call=True,
)
def _fill_account_options(_content, ids):
    """
    Traz a carteira de contas DEPOIS que a tela já apareceu.

    Enquanto isso o dropdown mostra a conta já vinculada, então nada some da
    tela durante a espera.
    """
    if not ids or not is_superadmin():
        return [dash.no_update] * len(ids or [])

    meta_options, google_options = _account_options()
    catalogue = {"meta": meta_options, "google": google_options}
    return [catalogue.get(item["platform"], []) for item in ids]


# --------------------------------------------------------------------------
# Acessos
# --------------------------------------------------------------------------

@callback(
    Output("admin-access-list", "children"),
    Output("admin-invite-list", "children"),
    Output("admin-reset-user", "options"),
    Input("admin-view", "data"),
    Input("admin-refresh", "data"),
)
def _load_access(view, _tick):
    """
    Só a região de acessos é redesenhada aqui.

    Se a tela inteira fosse refeita a cada convite gerado, o que estivesse
    digitado no formulário de identidade seria perdido.
    """
    tenant_id = _as_view(view)["tenant"]
    if not is_superadmin() or not tenant_id:
        return [], [], []

    from flask import request

    users = list_tenant_users(int(tenant_id))
    invites = list_pending_invites(int(tenant_id))
    return (
        _access_rows(users),
        _invite_rows(invites, request.host_url),
        [{"label": f"{user['name']} · {user['email']}", "value": user["id"]} for user in users],
    )


@callback(
    Output("admin-feedback", "children", allow_duplicate=True),
    Output("admin-feedback", "className", allow_duplicate=True),
    Output("admin-refresh", "data", allow_duplicate=True),
    Input("admin-invite-create", "n_clicks"),
    Input("admin-reset-submit", "n_clicks"),
    Input({"type": "admin-user-toggle", "id": ALL}, "n_clicks"),
    Input({"type": "admin-invite-revoke", "token": ALL}, "n_clicks"),
    Input({"type": "admin-user-delete", "id": ALL}, "submit_n_clicks"),
    State("admin-view", "data"),
    State("admin-invite-name", "value"),
    State("admin-invite-email", "value"),
    State("admin-invite-role", "value"),
    State("admin-reset-user", "value"),
    State("admin-reset-password", "value"),
    State("admin-refresh", "data"),
    prevent_initial_call=True,
)
def _access_action(
    _invite, _reset, toggles, revokes, deletes, view,
    invite_name, invite_email, invite_role, reset_user, reset_password, tick,
):
    """Todas as ações de acesso num lugar só, para o feedback ser um só."""
    if not is_superadmin():
        return "Sessão sem permissão administrativa.", "form-feedback form-feedback--error admin-feedback", tick

    tenant_id = _as_view(view)["tenant"]
    trigger = ctx.triggered_id
    kind = trigger.get("type") if isinstance(trigger, dict) else trigger

    if kind in ("admin-user-toggle", "admin-invite-revoke", "admin-user-delete") and not _real_click(
        list(toggles or []) + list(revokes or []) + list(deletes or [])
    ):
        return dash.no_update, dash.no_update, dash.no_update

    if not tenant_id:
        # Mesmo caso do salvar: a tela já trocou, o clique perdeu o alvo.
        return dash.no_update, dash.no_update, dash.no_update

    try:
        if kind == "admin-invite-create":
            invite = create_invite(
                int(tenant_id), name=invite_name, email=invite_email,
                role=invite_role or "client",
            )
            message = (f"Convite gerado para {invite['email']}. "
                       "Copie o link abaixo e envie para a pessoa.")

        elif kind == "admin-reset-submit":
            if not reset_user:
                raise ValueError("Selecione de quem é a senha que será redefinida.")
            set_user_password(int(reset_user), reset_password)
            message = "Senha redefinida. Informe a nova senha à pessoa."

        elif kind == "admin-user-toggle":
            users = {user["id"]: user for user in list_tenant_users(int(tenant_id))}
            target = users.get(trigger["id"])
            if not target:
                raise ValueError("Acesso não encontrado.")
            set_user_active(target["id"], not bool(target["active"]), tenant_id=int(tenant_id))
            message = (f"Acesso de {target['name']} "
                       f"{'desativado' if target['active'] else 'reativado'}.")

        elif kind == "admin-user-delete":
            removed = delete_user(trigger["id"], tenant_id=int(tenant_id))
            message = (f"Acesso de {removed['name']} excluído." if removed["account_deleted"]
                       else f"{removed['name']} não acessa mais este cliente; os outros clientes dela seguem iguais.")

        elif kind == "admin-invite-revoke":
            revoke_invite(trigger["token"])
            message = "Convite revogado. O link deixou de funcionar."

        else:
            return dash.no_update, dash.no_update, dash.no_update

    except ValueError as exc:
        return str(exc), "form-feedback form-feedback--error admin-feedback", tick

    return message, "form-feedback form-feedback--success admin-feedback", (tick or 0) + 1
