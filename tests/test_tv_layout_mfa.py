"""
Telas de TV, escolha de blocos, verificação em duas etapas e a sessão.

O que se fixa: cada TV mostra o cliente DO ENDEREÇO (não o da sessão), só
para quem tem acesso; configuração velha não derruba a tela; o código do
app é exigido, não se reaproveita e o cadastro só vale confirmado; e a
sessão não é regravada à toa (era o que fazia o painel "voltar sozinho"
para outro cliente).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from flask import Flask, session

from core import auth, layouts, mfa, storage
from core.branding import brand_for_request, tv_tenant


def setUpModule():
    import dash

    dash.Dash(__name__, use_pages=True, pages_folder="")


def _text(component) -> str:
    return json.dumps(component, default=lambda item: item.to_plotly_json(), ensure_ascii=False)


class LayoutRulesTests(unittest.TestCase):
    def test_dashboard_falls_back_and_keeps_catalog_order(self):
        self.assertEqual(layouts.clean_dashboard(None)["widgets"], layouts.DASHBOARD_DEFAULT)
        self.assertEqual(layouts.clean_dashboard({"widgets": ["funil", "kpis", "sumiu"]})["widgets"],
                         ["kpis", "funil"])

    def test_tv_limits_and_drops_what_does_not_fit_a_tv(self):
        config = layouts.clean_tv({"widgets": list(layouts.WIDGETS), "kpis": list(layouts.METRIC_LABELS),
                                   "period": "inventado"})
        self.assertNotIn("campanhas", config["widgets"])
        self.assertLessEqual(len([key for key in config["widgets"] if key != "kpis"]), layouts.TV_MAX_CHARTS)
        self.assertLessEqual(len(config["kpis"]), layouts.TV_MAX_KPIS)
        self.assertEqual(config["period"], "30d")

    def test_broken_tv_config_still_renders_defaults(self):
        self.assertEqual(layouts.clean_tv("{json quebrado")["widgets"], layouts.TV_DEFAULT_WIDGETS)


class ChampionTests(unittest.TestCase):
    """O criativo campeão: mais leads; sem nenhum lead, mais cliques — e a tela diz qual."""

    def test_most_leads_wins_and_cpl_breaks_ties(self):
        from ui.widgets import pick_champion

        ads = [
            {"nome": "A", "leads": 5, "cpl": 40, "investimento": 200, "cliques": 90},
            {"nome": "B", "leads": 5, "cpl": 30, "investimento": 150, "cliques": 10},
            {"nome": "C", "leads": 1, "cpl": 99, "investimento": 99, "cliques": 500},
        ]
        best, reason, runners = pick_champion(ads)
        self.assertEqual(best["nome"], "B")
        self.assertIn("leads", reason)
        self.assertEqual([ad["nome"] for ad in runners], ["A", "C"])

    def test_without_leads_clicks_win_and_reason_says_so(self):
        from ui.widgets import pick_champion

        best, reason, _ = pick_champion([
            {"nome": "A", "leads": 0, "investimento": 10, "cliques": 3, "ctr": 1},
            {"nome": "B", "leads": 0, "investimento": 10, "cliques": 9, "ctr": 1},
        ])
        self.assertEqual(best["nome"], "B")
        self.assertIn("nenhum anúncio gerou lead", reason)

    def test_no_delivery_means_no_champion(self):
        from ui.widgets import pick_champion

        self.assertEqual(pick_champion([{"nome": "A", "investimento": 0, "impressoes": 0}]), (None, None, []))


class TotpTests(unittest.TestCase):
    def test_rfc6238_vector(self):
        import base64

        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(mfa._code(secret, 59 // 30), "287082")

    def test_accepts_clock_skew_and_refuses_replay(self):
        secret = mfa.new_secret()
        now = 1_800_000_000
        code = mfa._code(secret, mfa.current_step(now) - 1)
        step = mfa.verify(secret, code, now=now)
        self.assertIsNotNone(step)
        self.assertIsNone(mfa.verify(secret, code, last_step=step, now=now))
        self.assertIsNone(mfa.verify(secret, "123", now=now))


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.a = storage.create_tenant(name="Cliente A", slug="cliente-a", owner_name="Ana Gestora",
                                       owner_email="ana@teste.com", password="Senha@Teste1")
        self.b = storage.create_tenant(name="Cliente B", slug="cliente-b", owner_name="Bia Gestora",
                                       owner_email="bia@teste.com", password="Senha@Teste1")
        self.ana = storage.authenticate("ana@teste.com", "Senha@Teste1")
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "test-secret"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()


class TvScreenTests(DbTestCase):
    def test_screen_ids_are_random_and_editable(self):
        screen = storage.save_tv_screen(self.a["id"], name="Recepção", config={"widgets": ["kpis", "funil"]})
        self.assertGreaterEqual(len(screen["id"]), 10)
        edited = storage.save_tv_screen(self.a["id"], name="Recepção 2", screen_id=screen["id"],
                                        config={"widgets": ["canais"]})
        self.assertEqual(edited["name"], "Recepção 2")
        with self.assertRaises(ValueError):
            storage.save_tv_screen(self.b["id"], name="Alheia", screen_id=screen["id"], config={})

    def test_tv_brand_follows_the_screen_not_the_session(self):
        screen = storage.save_tv_screen(self.b["id"], name="TV", config={})
        with self.flask_app.test_request_context(
            "/_dash-update-component", headers={"Referer": f"http://x/tv/{screen['id']}"}
        ):
            session["user_id"] = self.ana["id"]
            session["active_tenant_id"] = self.a["id"]
            self.assertEqual(tv_tenant()["id"], self.b["id"])
            self.assertEqual(brand_for_request(f"/tv/{screen['id']}")["name"], "Cliente B")

    def test_screen_only_for_people_with_access(self):
        from pages import tv

        screen = storage.save_tv_screen(self.b["id"], name="TV B", config={"widgets": ["funil"]})
        with self.flask_app.test_request_context("/"):
            session["user_id"] = self.ana["id"]
            self.assertIn("Seu acesso não inclui", _text(tv._body(screen["id"])))
        invite = storage.create_invite(self.b["id"], name="Ana", email="ana@teste.com")
        storage.accept_invite(invite["token"], password="Senha@Teste1")
        with self.flask_app.test_request_context("/"):
            session["user_id"] = self.ana["id"]
            session["active_tenant_id"] = self.a["id"]  # a sessão aponta para OUTRO cliente
            page = _text(tv._body(screen["id"]))
        self.assertIn("Cliente B", page)
        self.assertIn("tv-card--funil", page)
        with self.flask_app.test_request_context("/"):
            self.assertIn("não existe", _text(tv._body("nao-existe")))

    def test_deleting_client_takes_its_screens(self):
        screen = storage.save_tv_screen(self.b["id"], name="TV", config={})
        storage.delete_tenant(self.b["id"])
        self.assertIsNone(storage.get_tv_screen(screen["id"]))


class MfaStorageTests(DbTestCase):
    def test_enable_disable_and_require(self):
        secret = mfa.new_secret()
        storage.enable_mfa(self.ana["id"], secret)
        self.assertTrue(storage.get_mfa(self.ana["id"])["enabled"])
        storage.set_mfa_required(self.ana["id"], True)
        users = {user["email"]: user for user in storage.list_tenant_users(self.a["id"])}
        self.assertEqual((users["ana@teste.com"]["mfa_enabled"], users["ana@teste.com"]["mfa_required"]), (1, 1))
        storage.disable_mfa(self.ana["id"])
        state = storage.get_mfa(self.ana["id"])
        self.assertFalse(state["enabled"])
        self.assertIsNone(state["secret"])
        self.assertTrue(state["required"])

    def test_login_destination_accepts_tv_screens(self):
        from pages import login

        self.assertEqual(login._destination(self.ana, "?next=/tv/abc123"), "/tv/abc123")
        self.assertEqual(login._destination(self.ana, "?next=/tv/a/b"), "/")


class SessionTests(DbTestCase):
    def test_reading_the_user_does_not_rewrite_the_cookie(self):
        """Regravar o cookie em toda resposta desfazia a troca de cliente."""
        with self.flask_app.test_request_context("/"):
            session["user_id"] = self.ana["id"]
            session["active_tenant_id"] = self.a["id"]
            session.modified = False
            auth.current_user()
            self.assertFalse(session.modified)


if __name__ == "__main__":
    unittest.main()
