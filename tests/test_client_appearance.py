"""
O cliente personalizando o próprio painel, e as telas de entrada.

Fixa quem pode mudar a aparência (responsável e master, nunca o
visualizador), que a gravação do cliente não alcança dados de cadastro, e que
login e convite enxergam a URL da tela — o layout é montado numa requisição
interna do Dash, e lendo `request.args` o link de convite dava "não encontrado".
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from flask import Flask, session

from core import auth, storage
from core.branding import brand_for_request
from core.tenant_theme import parse_theme

DARK = {"text_color": "#E8EAED", "background_color": "#0F1115", "surface_color": "#171A21",
        "sidebar_color": "#0B0D11"}


def setUpModule():
    # Páginas só podem ser importadas depois de existir uma app com páginas.
    import dash

    dash.Dash(__name__, use_pages=True, pages_folder="")


def _text(component) -> str:
    return json.dumps(component.to_plotly_json(), default=lambda item: item.to_plotly_json(), ensure_ascii=False)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Cliente Teste", slug="cliente-teste", owner_name="Gestora",
            owner_email="gestora@teste.com", password="Senha@Teste1",
        )
        invite = storage.create_invite(self.tenant["id"], name="Analista", email="analista@teste.com", role="client")
        storage.accept_invite(invite["token"], password="OutraSenha1")
        self.owner = storage.authenticate("gestora@teste.com", "Senha@Teste1")
        self.viewer = storage.authenticate("analista@teste.com", "OutraSenha1")
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "test-secret"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_only_owner_and_master_can_edit(self):
        other = storage.create_tenant(name="Outro", slug="outro", owner_name="Outro Gestor",
                                      owner_email="x@teste.com", password="Senha@Teste1")
        master = storage.authenticate("admin", "admin")
        self.assertTrue(auth.can_edit_appearance(self.owner, self.tenant))
        self.assertFalse(auth.can_edit_appearance(self.viewer, self.tenant))
        self.assertFalse(auth.can_edit_appearance(self.owner, other))
        self.assertTrue(auth.can_edit_appearance(master, other))
        self.assertFalse(auth.can_edit_appearance(None, self.tenant))

    def test_client_save_touches_only_appearance(self):
        updated = storage.update_tenant_appearance(
            self.tenant["id"], primary_color="#7C3AED", secondary_color="#111111",
            logo_data=None, theme={**DARK, "font_body": "poppins"},
        )
        self.assertEqual(updated["primary_color"], "#7C3AED")
        self.assertEqual(parse_theme(updated["theme_data"])["font_body"], "poppins")
        self.assertEqual((updated["name"], updated["slug"], updated["status"]),
                         ("Cliente Teste", "cliente-teste", "active"))

    def test_unreadable_client_theme_is_refused(self):
        with self.assertRaises(ValueError):
            storage.update_tenant_appearance(
                self.tenant["id"], primary_color="#7C3AED", secondary_color="#111111", logo_data=None,
                theme={"text_color": "#777777", "background_color": "#808080"},
            )

    def test_menu_shows_appearance_only_to_who_can_edit(self):
        from ui import shell

        brand = {"name": "Cliente Teste", "logo_data": None}
        self.assertIn("/aparencia", _text(shell.sidebar("/", self.owner, brand)))
        self.assertNotIn("/aparencia", _text(shell.sidebar("/", self.viewer, brand)))

    def test_screen_query_reaches_brand_from_internal_dash_requests(self):
        """`?next=/slug` vem no Referer quando quem pergunta é o /_dash-layout."""
        with self.flask_app.test_request_context(
            "/_dash-layout", headers={"Referer": "http://x/login?next=/cliente-teste"}
        ):
            self.assertEqual(brand_for_request("/login")["name"], "Cliente Teste")
        with self.flask_app.test_request_context("/login?next=/cliente-teste"):
            self.assertEqual(brand_for_request("/login")["name"], "Cliente Teste")

    def test_invite_link_opens_the_form(self):
        from pages import convite

        invite = storage.create_invite(self.tenant["id"], name="Nova", email="nova@teste.com", role="client")
        # Requisição interna do Dash: sem `?token=` em request.args.
        with self.flask_app.test_request_context("/_dash-update-component"):
            page = _text(convite.layout(token=invite["token"]))
        self.assertIn("Criar seu acesso", page)
        self.assertIn("Cliente Teste", page)

    def test_viewer_sees_who_can_change(self):
        from pages import aparencia

        with self.flask_app.test_request_context("/aparencia"):
            session["user_id"] = self.viewer["id"]
            page = _text(aparencia.layout())
        self.assertIn("Só o responsável", page)
        self.assertNotIn("client-theme-save", page)

        with self.flask_app.test_request_context("/aparencia"):
            session["user_id"] = self.owner["id"]
            page = _text(aparencia.layout())
        self.assertIn("client-theme-save", page)


if __name__ == "__main__":
    unittest.main()
