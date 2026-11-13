"""
Tela de TV: `/tv/<código>`.

Feita para ficar aberta numa TV, sem ninguém mexer:

* **O cliente vem do endereço**, não da sessão. Várias TVs com o mesmo login
  mostram cada uma a sua tela; atualizar a página (ou a TV religar) volta
  para a mesma tela. Antes o cliente vinha do cookie e todas as TVs
  acabavam no mesmo.
* **Cabe na tela, sem rolagem.** A tela é dividida entre os blocos
  escolhidos (ver /layout): os indicadores numa faixa e os gráficos numa
  grade que ocupa o resto, em qualquer resolução. Letra e gráficos crescem
  com a largura da TV (CSS em `vw`, `--chart-scale` no Chart.js).
* **Atualiza sozinha** a cada 5 minutos, sem tela de carregamento por cima.

Exige login com acesso ao cliente da tela (ou o master).
"""

from __future__ import annotations

from datetime import datetime

import dash
from dash import Input, Output, State, callback, dcc, html

from core import fmt, layouts
from core.auth import current_user, is_superadmin
from core.branding import brand_for_tenant
from core.data import get_dataset, get_period
from core.storage import get_tenant, get_tv_screen
from ui import widgets
from ui.auth_layout import brand_mark
from ui.icons import icon

dash.register_page(__name__, path_template="/tv/<screen_id>", name="TV", title="TV")

REFRESH_MS = 5 * 60 * 1000

# Quantas colunas x linhas para N gráficos: o mais perto de "quadrado" que
# ainda deixa cada gráfico largo o bastante para ler de longe.
GRID = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 5: (3, 2), 6: (3, 2), 7: (4, 2), 8: (4, 2)}


def _screen_for(screen_id: str | None):
    """(tela, cliente) se a pessoa logada pode ver a tela; senão (None, motivo)."""
    screen = get_tv_screen(screen_id)
    if not screen:
        return None, "Esta tela não existe mais. Gere um novo link em Layout > Telas de TV."
    tenant = get_tenant(screen["tenant_id"])
    if not tenant or tenant.get("status") != "active":
        return None, "O cliente desta tela está inativo."
    user = current_user()
    allowed = is_superadmin(user) or any(
        item["tenant_id"] == tenant["id"] for item in (user or {}).get("memberships") or []
    )
    if not allowed:
        return None, "Seu acesso não inclui o cliente desta tela."
    return (screen, tenant), None


def _notice(message: str):
    return html.Div(
        [icon("monitor", 40), html.H1("Tela indisponível"), html.P(message)],
        className="tv-notice",
    )


def _body(screen_id: str | None):
    found, problem = _screen_for(screen_id)
    if problem:
        return _notice(problem)
    screen, tenant = found
    config = layouts.clean_tv(screen["config"])
    period = get_period(config["period"])
    data = get_dataset(config["period"], tenant_id=tenant["id"])

    by_key = {metric["key"]: metric for metric in data["kpis"]}
    kpis = [by_key[key] for key in config["kpis"] if key in by_key] if "kpis" in config["widgets"] else []
    charts = [key for key in config["widgets"] if key != "kpis"]
    cols, rows = GRID.get(len(charts), (4, 2))

    return [
        html.Header(
            [
                html.Div(brand_mark(brand_for_tenant(tenant)), className="tv__brand"),
                html.Div(
                    [
                        html.H1(tenant["name"], className="tv__title"),
                        html.Span(
                            f'{screen["name"]} · {period["label"]} · '
                            f'{fmt.long_date(data["range"]["start"])} a {fmt.long_date(data["range"]["end"])} · '
                            f'variações comparadas com {period["compare"]}',
                            className="tv__subtitle",
                        ),
                    ],
                    className="tv__heading",
                ),
                html.Span([icon("refresh-cw", 14), f'Atualizado às {datetime.now():%H:%M}'], className="tv__updated"),
            ],
            className="tv__head",
        ),
        html.Div(
            [widgets.tv_kpi(metric) for metric in kpis],
            className="tv__kpis",
            style={"--tv-kpis": str(len(kpis))},
        ) if kpis else None,
        html.Div(
            [widgets.tv_card(key, data, rows) for key in charts],
            className="tv__grid",
            style={"--tv-cols": str(cols), "--tv-rows": str(rows)},
        ) if charts else None,
    ]


def layout(screen_id: str | None = None, **_query):
    return html.Div(
        [
            dcc.Store(id="tv-screen-id", data=screen_id),
            dcc.Interval(id="tv-tick", interval=REFRESH_MS, n_intervals=0),
            html.Div(_body(screen_id), id="tv-body", className="tv"),
        ],
        className="tv-page",
    )


@callback(
    Output("tv-body", "children"),
    Input("tv-tick", "n_intervals"),
    State("tv-screen-id", "data"),
    prevent_initial_call=True,
)
def _refresh(_tick, screen_id):
    # Fora dos alvos da tela de carregamento (app.py): a TV troca os números
    # sem piscar nada por cima.
    return _body(screen_id)
