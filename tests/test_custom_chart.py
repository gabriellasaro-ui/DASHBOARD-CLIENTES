"""
Gráfico personalizável e a saída da receita.

O que importa fixar aqui não é o desenho, é a REGRA: unidades diferentes
nunca viram dois eixos, e a receita não voltou por nenhuma porta.
"""

from __future__ import annotations

import unittest

from ui import charts


def _series(days: int = 5) -> list[dict]:
    return [
        {
            "date": f"2026-08-{day + 1:02d}",
            "investimento": 100.0 * (day + 1),
            "leads": 10.0 * (day + 1),
            "cliques": 200 * (day + 1),
            "impressoes": 5000 * (day + 1),
            "alcance": 4000 * (day + 1),
            "cpl": 10.0,
            "cpc": 0.5,
            "cpm": 20.0,
            "ctr": 4.0,
            "receita": 999.0,
        }
        for day in range(days)
    ]


class CustomChartTests(unittest.TestCase):
    def test_same_unit_keeps_absolute_values(self):
        figure = charts.custom_series(_series(), ["investimento", "cpl"], {})
        first = figure["datasets"][0]["data"]
        self.assertEqual(first[0], 100.0)
        self.assertEqual(first[-1], 500.0)

    def test_mixed_units_are_indexed_to_100(self):
        """Dois eixos fariam curvas parecerem se cruzar sem se cruzarem."""
        figure = charts.custom_series(_series(), ["investimento", "ctr"], {})
        for dataset in figure["datasets"]:
            self.assertEqual(dataset["data"][0], 100.0)

    def test_tooltip_always_shows_the_real_value(self):
        figure = charts.custom_series(_series(), ["investimento", "ctr"], {})
        investment = figure["datasets"][0]
        self.assertIn("100", investment["display"][0])
        self.assertNotEqual(investment["display"][-1], investment["display"][0])

    def test_chosen_colours_are_applied(self):
        figure = charts.custom_series(
            _series(), ["investimento", "leads"],
            {"investimento": "#123456", "leads": "#ABCDEF"},
        )
        self.assertEqual(figure["datasets"][0]["color"], "#123456")
        self.assertEqual(figure["datasets"][1]["color"], "#ABCDEF")

    def test_unknown_metric_is_ignored_and_empty_falls_back(self):
        """A configuração vem do navegador: chave inválida não pode quebrar."""
        figure = charts.custom_series(_series(), ["inexistente"], {})
        self.assertEqual(len(figure["datasets"]), len(charts.DEFAULT_PLOT))

        figure = charts.custom_series(_series(), [], {})
        self.assertEqual(len(figure["datasets"]), len(charts.DEFAULT_PLOT))

    def test_zero_series_does_not_divide_by_zero(self):
        flat = [{**row, "investimento": 0.0} for row in _series()]
        figure = charts.custom_series(flat, ["investimento", "ctr"], {})
        self.assertTrue(all(value == value for value in figure["datasets"][0]["data"]))  # sem NaN

    def test_spec_is_plain_json_for_the_browser(self):
        """O Chart.js recebe a especificação pelo atributo `data-chart`."""
        import json

        spec = charts.custom_series(_series(), ["investimento", "leads"], {})
        self.assertEqual(json.loads(json.dumps(spec)), spec)
        node = charts.graph(spec)
        self.assertEqual(json.loads(getattr(node, "data-chart")), spec)

    def test_y_axis_ticks_are_round_and_cover_the_peak(self):
        spec = charts.cost_line(_series(), "investimento", "#123456", "Investimento")
        ticks = spec["y"]["ticks"]
        self.assertEqual(ticks[0], 0)
        self.assertGreaterEqual(ticks[-1], 500.0)
        self.assertEqual(len(ticks), len(spec["y"]["labels"]))

    def test_all_zero_series_still_gets_an_axis(self):
        flat = [{**row, "leads": 0.0} for row in _series()]
        self.assertEqual(charts.daily_bars(flat, "leads", "#123456", "Leads")["y"]["ticks"], [0.0, 1.0])

    def test_donut_center_shows_the_total(self):
        spec = charts.channel_donut([
            {"key": "meta", "nome": "Meta Ads", "valor": 300.0},
            {"key": "google", "nome": "Google Ads", "valor": 700.0},
        ])
        self.assertEqual(spec["kind"], "doughnut")
        self.assertEqual(spec["datasets"][0]["data"], [300.0, 700.0])
        self.assertIn("70", spec["datasets"][0]["display"][1])

    def test_revenue_is_not_offered_as_a_metric(self):
        self.assertNotIn("receita", charts.PLOTTABLE)
        self.assertNotIn("receita_acumulada", charts.PLOTTABLE)


class RevenueRemovalTests(unittest.TestCase):
    def test_revenue_is_not_a_dashboard_metric(self):
        from core.data import METRICS

        self.assertNotIn("receita", [key for key, *_ in METRICS])

    def test_no_table_column_shows_revenue(self):
        from ui.tables import TABLE_SPECS

        for name, spec in TABLE_SPECS.items():
            with self.subTest(table=name):
                labels = [column["label"] for column in spec["columns"]]
                self.assertNotIn("Receita", labels)
                self.assertNotIn("receita", [column["key"] for column in spec["columns"]])

    def test_revenue_is_still_ingested_for_internal_use(self):
        """Sai da interface, mas continua vindo da plataforma."""
        from core.data import _blank_row

        self.assertIn("receita", _blank_row("2026-08-01"))


class CallbackIsolationTests(unittest.TestCase):
    """
    Ids de componente não podem cruzar telas.

    Uma callback do dashboard que escutasse `{"type": "color-value", ...}`
    genérico ficava elegível no /admin — que também usa `color_input` — e
    quebrava com "A nonexistent object was used in an Input", procurando o
    `chart-trigger`, que só existe no dashboard.
    """

    @staticmethod
    def _ids(component) -> list[dict]:
        """Todos os ids em dicionário dentro de um componente."""
        found = []

        def walk(node):
            if isinstance(node, dict):
                if "type" in node and "group" in node:
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        import json

        from dash._utils import to_json

        walk(json.loads(to_json(component)))
        return found

    def test_colour_fields_declare_the_group_that_isolates_them(self):
        from ui.primitives import color_input

        chart = self._ids(color_input("leads", "#123456", group="chart"))
        tenant = self._ids(color_input("admin-edit-primary", "#123456", group="tenant"))

        self.assertTrue(chart, "nenhum id em dicionário encontrado")
        self.assertTrue(all(item["group"] == "chart" for item in chart))
        self.assertTrue(all(item["group"] == "tenant" for item in tenant))

    def test_dashboard_only_listens_to_its_own_colour_group(self):
        # Lê o arquivo direto: importar a página exige o app instanciado,
        # e o que precisa ser verificado aqui é a declaração da callback.
        from pathlib import Path

        declaration = (
            Path(__file__).resolve().parent.parent / "pages" / "dashboard.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"group": "chart"', declaration)
        # Escutar sem o grupo é o que casava com os campos do /admin.
        self.assertNotIn('Input({"type": "color-value", "for": ALL}', declaration)


class PartialUpdateTests(unittest.TestCase):
    """
    Cada controle troca só o pedaço que lhe cabe.

    Quando a seleção de métricas e a configuração do gráfico eram `Input` da
    callback que devolve `page-dashboard.children`, marcar uma métrica ou
    mexer numa cor repintava KPIs, curvas, funil, rosca e tabela de uma vez —
    a tela inteira piscava e parecia um recarregamento.
    """

    @staticmethod
    def _declaration(name: str) -> str:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent / "pages" / "dashboard.py"
        ).read_text(encoding="utf-8")
        return source.split(f"def {name}", 1)[0].rsplit("@callback", 1)[1]

    def test_metric_picker_does_not_rebuild_the_page(self):
        page = self._declaration("_reload")
        self.assertIn('State("metrics-store", "data")', page)
        self.assertNotIn('Input("metrics-store", "data")', page)
        self.assertNotIn('Input("chart-store", "data")', page)

    def test_metric_picker_updates_only_the_kpi_band(self):
        band = self._declaration("_reload_kpis")
        self.assertIn('Output("kpi-band", "children")', band)
        self.assertIn('Input("metrics-store", "data")', band)
        self.assertNotIn("page-dashboard", band)

    def test_chart_menu_only_writes_to_the_chart(self):
        chart = self._declaration("_chart_settings")
        for target in ('Output("chart-figure", "children")', 'Output("chart-legend", "children")'):
            self.assertIn(target, chart)
        self.assertNotIn("page-dashboard", chart)


class ServerRouteLinkTests(unittest.TestCase):
    """
    `dcc.Link` só serve para páginas do Dash.

    Num endpoint do Flask ele sequestra o clique e apenas troca a URL no
    navegador: sair da conta não executava `/logout`, a sessão continuava
    aberta e a tela parava num 404 em vez de voltar para o login.
    """

    FLASK_ONLY = ("/logout", "/voltar-admin", "/entrar-como")

    def test_no_dcc_link_points_at_a_flask_route(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        offenders = []

        for path in [*(root / "ui").glob("*.py"), *(root / "pages").glob("*.py"), root / "app.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                if not (isinstance(target, ast.Attribute) and target.attr == "Link"):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "href":
                        continue
                    href = keyword.value
                    texto = href.value if isinstance(href, ast.Constant) else (
                        "".join(
                            part.value for part in getattr(href, "values", [])
                            if isinstance(part, ast.Constant)
                        )
                        if isinstance(href, ast.JoinedStr) else ""
                    )
                    if texto.startswith(self.FLASK_ONLY):
                        offenders.append(f"{path.name}:{node.lineno} -> {texto}")

        self.assertEqual(offenders, [], "use html.A nestes casos:\n" + "\n".join(offenders))


class NoDeliveryStateTests(unittest.TestCase):
    """
    Conta parada não pode parecer integração quebrada.

    A conta do Meta ficou sem veicular desde 07/06 e o painel filtra 7 ou 30
    dias: a tela vinha com KPIs zerados, gráfico reto e abas vazias, e a
    leitura natural disso é "não está puxando os dados".
    """

    @staticmethod
    def _text(component) -> str:
        parts: list[str] = []

        def walk(node):
            if isinstance(node, str):
                parts.append(node)
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    walk(item)
                return
            for attr in ("children", "title", "description"):
                value = getattr(node, attr, None)
                if value is not None:
                    walk(value)

        walk(component)
        return " ".join(parts)

    def test_it_says_when_the_last_delivery_was(self):
        from ui.primitives import no_delivery_state

        text = self._text(no_delivery_state("Meta Ads", "2026-06-07"))
        self.assertIn("Sem veiculação no Meta Ads", text)
        self.assertIn("07 jun 2026", text)

    def test_an_account_that_never_delivered_says_so(self):
        from ui.primitives import no_delivery_state

        text = self._text(no_delivery_state("Google Ads", None))
        self.assertIn("Ainda não há nenhuma veiculação", text)
        # Sem data não pode sobrar um "em None" na frase.
        self.assertNotIn("None", text)

    def test_both_platform_pages_use_it(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        for name in ("meta_ads.py", "google_ads.py"):
            with self.subTest(page=name):
                source = (root / "pages" / name).read_text(encoding="utf-8")
                self.assertIn("no_delivery_state(", source)
                self.assertIn('data.get("last_delivery"', source)


class ImportHygieneTests(unittest.TestCase):
    """
    Biblioteca de componente não pode ser importada dentro de função.

    O Dash bloqueia isso em tempo de callback com
    `ImportedInsideCallbackError`, e o erro só aparece quando alguém clica —
    nenhum teste de render pega. Aqui a verificação é estática.
    """

    COMPONENT_LIBRARIES = (
        "dash_daq", "dash_core_components", "dash_html_components",
        "dash_table", "dash_bootstrap_components",
    )

    def test_no_component_library_is_imported_inside_a_function(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        offenders = []

        for path in list((root / "ui").glob("*.py")) + list((root / "pages").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in ast.walk(node):
                    modules = []
                    if isinstance(inner, ast.Import):
                        modules = [alias.name for alias in inner.names]
                    elif isinstance(inner, ast.ImportFrom):
                        modules = [inner.module or ""]

                    for module in modules:
                        root_module = module.split(".")[0]
                        if root_module in self.COMPONENT_LIBRARIES or module == "dash":
                            offenders.append(
                                f"{path.name}:{inner.lineno} em {node.name}() -> {module}"
                            )

        self.assertEqual(offenders, [], "importe no topo do módulo:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
