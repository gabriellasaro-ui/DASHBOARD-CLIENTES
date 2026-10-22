"""
Acessos do cliente (convite, senha, simulação) e whitelabel de cores.

O foco das asserções de cor não é "qual hexadecimal saiu", e sim as
GARANTIAS: a marca chega nos gráficos, nenhuma cor derivada fica ilegível
sobre o branco, e cores de status seguem fixas mesmo com marca verde.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flask import Flask, session

from core import auth, storage
from core.branding import (
    DEFAULT_PRIMARY,
    brand_palette,
    contrast_ratio,
    css_variables,
    favicon_data_uri,
    ordinal_ramp,
    separation,
    style_variables,
)


class TenantAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Cliente Teste",
            slug="cliente-teste",
            owner_name="Gestora Teste",
            owner_email="gestora@teste.com",
            password="Senha@Teste1",
        )

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    # ---- convites -------------------------------------------------------

    def test_invited_person_sets_own_password_and_can_log_in(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com", role="client"
        )
        user = storage.accept_invite(invite["token"], password="OutraSenha1")

        self.assertEqual(user["tenant_id"], self.tenant["id"])
        self.assertEqual(user["role"], "client")
        signed = storage.authenticate("analista@teste.com", "OutraSenha1")
        self.assertIsNotNone(signed)
        self.assertEqual(signed["tenant_name"], "Cliente Teste")

    def test_invite_cannot_be_reused(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com"
        )
        storage.accept_invite(invite["token"], password="OutraSenha1")

        self.assertEqual(storage.get_invite(invite["token"])["state"], "accepted")
        with self.assertRaises(ValueError):
            storage.accept_invite(invite["token"], password="MaisUmaSenha1")

    def test_invite_rejects_short_password_and_existing_email(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com"
        )
        with self.assertRaises(ValueError):
            storage.accept_invite(invite["token"], password="curta")

        with self.assertRaises(ValueError):
            storage.create_invite(
                self.tenant["id"], name="Gestora", email="gestora@teste.com"
            )

    def test_revoked_invite_stops_working(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com"
        )
        storage.revoke_invite(invite["token"])

        self.assertIsNone(storage.get_invite(invite["token"]))
        self.assertEqual(storage.list_pending_invites(self.tenant["id"]), [])

    # ---- responsável ----------------------------------------------------

    def test_owner_email_change_moves_the_login(self):
        users = storage.list_tenant_users(self.tenant["id"])
        owner = users[0]
        self.assertEqual(owner["role"], "client_admin")

        storage.update_user(
            owner["id"], name="Gestora Nova", email="novo@teste.com", role="client_admin"
        )

        self.assertIsNone(storage.authenticate("gestora@teste.com", "Senha@Teste1"))
        self.assertIsNotNone(storage.authenticate("novo@teste.com", "Senha@Teste1"))

    def test_password_reset_replaces_the_old_one(self):
        owner = storage.list_tenant_users(self.tenant["id"])[0]
        storage.set_user_password(owner["id"], "SenhaNova123")

        self.assertIsNone(storage.authenticate("gestora@teste.com", "Senha@Teste1"))
        self.assertIsNotNone(storage.authenticate("gestora@teste.com", "SenhaNova123"))

    def test_last_responsible_cannot_be_removed(self):
        """Um cliente sem responsável ficaria sem ninguém para administrá-lo."""
        owner = storage.list_tenant_users(self.tenant["id"])[0]

        with self.assertRaises(ValueError):
            storage.set_user_active(owner["id"], False)
        with self.assertRaises(ValueError):
            storage.update_user(
                owner["id"], name=owner["name"], email=owner["email"], role="client"
            )

    def test_deactivated_user_cannot_authenticate(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com"
        )
        user = storage.accept_invite(invite["token"], password="OutraSenha1")
        storage.set_user_active(user["id"], False)

        self.assertIsNone(storage.authenticate("analista@teste.com", "OutraSenha1"))

    # ---- exclusão -------------------------------------------------------

    def test_deleting_a_user_removes_the_login(self):
        invite = storage.create_invite(
            self.tenant["id"], name="Analista", email="analista@teste.com"
        )
        user = storage.accept_invite(invite["token"], password="OutraSenha1")

        storage.delete_user(user["id"])

        self.assertIsNone(storage.authenticate("analista@teste.com", "OutraSenha1"))
        self.assertEqual(len(storage.list_tenant_users(self.tenant["id"])), 1)

    def test_last_responsible_cannot_be_deleted(self):
        owner = storage.list_tenant_users(self.tenant["id"])[0]
        with self.assertRaises(ValueError):
            storage.delete_user(owner["id"])

    def test_deleting_a_tenant_takes_users_invites_and_metrics(self):
        storage.create_invite(self.tenant["id"], name="Convidado", email="x@teste.com")
        storage.replace_media_rows(
            self.tenant["id"], "meta", "2026-08-01", "2026-08-01",
            [{
                "tenant_id": self.tenant["id"], "platform": "meta",
                "metric_date": "2026-08-01", "level": "account",
                "entity_id": "act_1", "account_id": "act_1", "name": "conta",
                "status": "active", "campaign_id": None, "campaign_name": None,
                "parent_id": None, "parent_name": None, "investimento": 10.0,
                "receita": 0.0, "impressoes": 100, "cliques": 5, "leads": 1.0,
                "conversoes": 0.0, "alcance": 90, "creative_url": None,
                "creative_quality": None, "quality_score": None, "match_type": None,
                "impression_share": None, "top_impression_share": None,
                "updated_at": "2026-08-01T00:00:00+00:00",
            }],
        )

        removed = storage.delete_tenant(self.tenant["id"])

        self.assertEqual(removed["name"], "Cliente Teste")
        self.assertIsNone(storage.get_tenant(self.tenant["id"]))
        self.assertIsNone(storage.authenticate("gestora@teste.com", "Senha@Teste1"))
        self.assertEqual(storage.list_tenant_users(self.tenant["id"]), [])
        self.assertEqual(storage.list_pending_invites(self.tenant["id"]), [])
        self.assertEqual(
            storage.get_media_rows(self.tenant["id"], "meta", "2026-08-01", "2026-08-01"), []
        )

    def test_deleting_an_unknown_tenant_is_refused(self):
        with self.assertRaises(ValueError):
            storage.delete_tenant(999999)

    # ---- identificador --------------------------------------------------

    def test_slug_can_be_changed_and_blank_keeps_the_current_one(self):
        storage.update_tenant_settings(
            self.tenant["id"], name="Cliente Teste", slug="novo-slug",
            primary_color="#E5001A", secondary_color="#0B0B0D", logo_data=None,
            status="active", meta_ad_account_id=None, google_ads_customer_id=None,
        )
        self.assertEqual(storage.get_tenant_by_slug("novo-slug")["id"], self.tenant["id"])

        storage.update_tenant_settings(
            self.tenant["id"], name="Cliente Teste", slug="",
            primary_color="#E5001A", secondary_color="#0B0B0D", logo_data=None,
            status="active", meta_ad_account_id=None, google_ads_customer_id=None,
        )
        self.assertEqual(storage.get_tenant(self.tenant["id"])["slug"], "novo-slug")


class ImpersonationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Cliente Teste", slug="cliente-teste", owner_name="Gestora",
            owner_email="gestora@teste.com", password="Senha@Teste1",
        )
        self.app = Flask(__name__)
        self.app.secret_key = "teste"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_admin_enters_as_client_and_can_come_back(self):
        admin = storage.authenticate("admin", "admin")
        owner = storage.list_tenant_users(self.tenant["id"])[0]

        with self.app.test_request_context("/"):
            auth.sign_in(admin)
            auth.start_impersonation(owner["id"])

            self.assertEqual(auth.current_user()["email"], "gestora@teste.com")
            self.assertFalse(auth.is_superadmin())
            self.assertEqual(auth.impersonator()["role"], "superadmin")

            auth.stop_impersonation()
            self.assertTrue(auth.is_superadmin())
            self.assertIsNone(auth.impersonator())

    def test_client_cannot_impersonate(self):
        owner_login = storage.authenticate("gestora@teste.com", "Senha@Teste1")
        with self.app.test_request_context("/"):
            auth.sign_in(owner_login)
            with self.assertRaises(PermissionError):
                auth.start_impersonation(owner_login["id"])


class WhitelabelTests(unittest.TestCase):
    """As cores escolhidas precisam chegar a TUDO, e nunca ficar ilegíveis."""

    BRANDS = [
        "#E5001A", "#1D4ED8", "#16A34A", "#FFD400", "#B7F000",
        "#22D3EE", "#7C3AED", "#F97316", "#0B0B0D", "#EC4899",
    ]

    def test_every_derived_series_is_readable_on_white(self):
        for color in self.BRANDS:
            palette = brand_palette(color)
            for hexcolor in palette["series"][:3]:
                with self.subTest(brand=color, series=hexcolor):
                    self.assertGreaterEqual(contrast_ratio(hexcolor), 3.0)

    def test_series_stay_distinguishable_including_colour_blindness(self):
        for color in self.BRANDS:
            series = brand_palette(color)["series"][:3]
            for index, first in enumerate(series):
                for second in series[index + 1:]:
                    with self.subTest(brand=color, pair=(first, second)):
                        self.assertGreaterEqual(separation(first, second), 6.0)

    def test_funnel_ramp_never_disappears_into_the_background(self):
        """Marca clara produzia um último degrau de 1,17:1 — invisível."""
        for color in self.BRANDS:
            ramp = ordinal_ramp(color)
            with self.subTest(brand=color):
                self.assertGreaterEqual(contrast_ratio(ramp[-1]), 2.0)
                lightness = [contrast_ratio(step) for step in ramp]
                self.assertEqual(lightness, sorted(lightness, reverse=True))

    def test_achromatic_brand_keeps_a_neutral_ramp(self):
        """Preto não tem matiz; forçar saturação inventava um funil azul."""
        for step in ordinal_ramp("#0B0B0D"):
            red, green, blue = (int(step[i:i + 2], 16) for i in (1, 3, 5))
            self.assertEqual((red, green), (green, blue))

    def test_brand_reaches_the_css_variables_and_the_favicon(self):
        brand = {"name": "Somaxi", "primary_color": "#7C3AED", "secondary_color": "#123456"}
        variables = style_variables(brand)

        self.assertEqual(variables["--brand"], "#7C3AED")
        self.assertEqual(variables["--series-1"], brand_palette("#7C3AED")["series"][0])
        self.assertIn("--ordinal-1", variables)
        self.assertIn("--brand:#7C3AED", css_variables(brand))
        self.assertTrue(favicon_data_uri(brand).startswith("data:image/svg+xml,"))

    def test_uploaded_logo_becomes_the_favicon(self):
        logo = "data:image/png;base64,AAAA"
        self.assertEqual(favicon_data_uri({"name": "X", "logo_data": logo}), logo)

    def test_status_colours_never_follow_the_brand(self):
        """Marca verde não pode fazer 'caiu 8%' aparecer em verde."""
        from core.theme import STATUS

        self.assertEqual(STATUS["negative"], "#E5001A")
        self.assertEqual(STATUS["positive"], "#16A34A")
        self.assertNotIn("--positive", style_variables({"primary_color": "#16A34A"}))

    def test_missing_colour_falls_back_instead_of_raising(self):
        self.assertEqual(brand_palette(None)["primary"], DEFAULT_PRIMARY)
        self.assertEqual(brand_palette("")["primary"], DEFAULT_PRIMARY)


class AdminScreenBrandTests(unittest.TestCase):
    """
    O painel de clientes é tela da agência.

    O master vê a marca do cliente enquanto inspeciona os dados dele, mas
    abrir /admin com o laranja e o nome do último cliente dava a impressão de
    ainda estar dentro da conta desse cliente.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Cliente Laranja", slug="laranja", owner_name="Gestora",
            owner_email="gestora@teste.com", password="Senha@Teste1",
            primary_color="#FF9320",
        )
        self.app = Flask(__name__)
        self.app.secret_key = "teste"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def _brand_at(self, path: str) -> dict:
        from core.branding import brand_for_request

        admin = storage.authenticate("admin", "admin")
        with self.app.test_request_context(path):
            auth.sign_in(admin)
            auth.select_active_tenant(self.tenant["id"])
            return brand_for_request()

    def test_admin_screen_shows_the_agency(self):
        brand = self._brand_at("/admin")
        self.assertEqual(brand["name"], "V4 Company")
        self.assertEqual(brand["primary_color"], DEFAULT_PRIMARY)

    def test_data_screens_still_show_the_inspected_client(self):
        for path in ("/", "/meta-ads", "/google-ads"):
            with self.subTest(path=path):
                brand = self._brand_at(path)
                self.assertEqual(brand["name"], "Cliente Laranja")
                self.assertEqual(brand["primary_color"], "#FF9320")

    def test_the_screen_path_wins_over_the_endpoint_path(self):
        """
        O layout e as callbacks chegam por `/_dash-layout` e
        `/_dash-update-component`. Resolver a marca por `request.path` nessas
        requisições devolvia sempre a do cliente — era o que mantinha o painel
        de clientes pintado com a cor dele.
        """
        from core.branding import brand_for_request

        admin = storage.authenticate("admin", "admin")
        with self.app.test_request_context("/_dash-update-component"):
            auth.sign_in(admin)
            auth.select_active_tenant(self.tenant["id"])

            self.assertEqual(brand_for_request("/admin")["name"], "V4 Company")
            self.assertEqual(brand_for_request("/")["primary_color"], "#FF9320")
            # Sem a tela informada, o endpoint interno não pode virar /admin
            # por acidente nem responder pelo cliente errado.
            self.assertEqual(brand_for_request()["primary_color"], "#FF9320")

    def test_the_shell_can_swap_brand_without_a_reload(self):
        """Logo e nome têm âncora própria para a callback de navegação trocar."""
        from ui import shell

        master = {"name": "Master", "email": "admin", "role": "superadmin"}
        ids: list[str] = []

        def walk(node):
            node_id = getattr(node, "id", None)
            if isinstance(node_id, str):
                ids.append(node_id)
            children = getattr(node, "children", None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    walk(child)
            elif children is not None:
                walk(children)

        walk(shell.sidebar("/admin", master, {"name": "X", "logo_data": None}))
        self.assertIn("brand-logo", ids)

        agency = shell.brand_logo({"name": "V4 Company", "logo_data": None})
        client = shell.brand_logo({"name": "Cliente Laranja", "logo_data": None})
        self.assertNotEqual(str(agency), str(client))


class NewClientBrandTests(unittest.TestCase):
    """
    Cliente novo entra com a cor dele, sem herdar nada do anterior.

    Nada aqui é sobre um hexadecimal específico: o que precisa valer é que
    TODOS os tokens derivados (hover, tint, série do gráfico, ramp ordinal)
    mudam junto e nenhum sobra do cliente que estava selecionado antes.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.app = Flask(__name__)
        self.app.secret_key = "teste"
        self.laranja = storage.create_tenant(
            name="Cliente Laranja", slug="laranja", owner_name="Responsavel A",
            owner_email="a@teste.com", password="Senha@Teste1", primary_color="#FF9320",
        )
        self.roxo = storage.create_tenant(
            name="Cliente Roxo", slug="roxo", owner_name="Responsavel B",
            owner_email="b@teste.com", password="Senha@Teste1", primary_color="#7C3AED",
        )

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def _tokens(self, tenant_id: int) -> dict:
        from core.branding import brand_for_request

        admin = storage.authenticate("admin", "admin")
        with self.app.test_request_context("/"):
            auth.sign_in(admin)
            auth.select_active_tenant(tenant_id)
            return style_variables(brand_for_request("/"))

    def test_switching_client_repaints_every_derived_token(self):
        laranja = self._tokens(self.laranja["id"])
        roxo = self._tokens(self.roxo["id"])

        self.assertEqual(laranja["--brand"], "#FF9320")
        self.assertEqual(roxo["--brand"], "#7C3AED")

        # Nenhum token derivado pode continuar com o valor do cliente anterior.
        for token in ("--brand-hover", "--brand-active", "--brand-tint",
                      "--brand-ring", "--brand-data", "--series-1", "--ordinal-1"):
            with self.subTest(token=token):
                self.assertNotEqual(laranja[token], roxo[token])

    def test_a_brand_new_client_is_readable_whatever_colour_was_chosen(self):
        """A cor vem do cliente; a legibilidade é responsabilidade nossa."""
        for colour in ("#FFE800", "#FFFFFF", "#111111", "#00D1FF", "#7C3AED"):
            with self.subTest(colour=colour):
                tenant = storage.create_tenant(
                    name=f"Cliente {colour}", slug=f"c{colour.lstrip('#').lower()}",
                    owner_name="Responsavel C", owner_email=f"{colour.lstrip('#')}@teste.com",
                    password="Senha@Teste1", primary_color=colour,
                )
                tokens = self._tokens(tenant["id"])
                palette = brand_palette(colour)
                self.assertGreaterEqual(
                    contrast_ratio(palette["data"], "#FFFFFF"), 3.0,
                    f"{colour}: a cor da série ficaria invisível no fundo branco",
                )
                self.assertGreaterEqual(
                    contrast_ratio(palette["primary"], palette["contrast"]), 4.5,
                    f"{colour}: texto sobre o botão ficaria ilegível",
                )
                self.assertTrue(tokens["--brand"].startswith("#"))


class StylesheetBrandTests(unittest.TestCase):
    """
    O CSS estático é a porta dos fundos do whitelabel.

    Uma cor de marca fixada aqui não passa por `brand_palette` e por isso
    escapa de todas as outras asserções: o avatar continuava vermelho num
    cliente azul, e a tela de login também.
    """

    ASSETS = Path(__file__).resolve().parent.parent / "assets"

    def _rule(self, stylesheet: str, selector: str) -> str:
        css = (self.ASSETS / stylesheet).read_text(encoding="utf-8")
        self.assertIn(selector, css, f"{selector} sumiu de {stylesheet}")
        return css.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]

    def test_avatar_follows_the_brand(self):
        rule = self._rule("20-components.css", ".avatar ")
        self.assertIn("var(--brand)", rule)
        self.assertIn("var(--brand-contrast)", rule)
        self.assertNotIn("#e5001a", rule.lower())

    def test_login_backdrop_follows_the_brand(self):
        rule = self._rule("30-layout.css", ".auth-screen__glow")
        self.assertIn("var(--brand)", rule)
        self.assertNotIn("229, 0, 26", rule)


if __name__ == "__main__":
    unittest.main()
