"""Um mesmo e-mail com acesso a vários clientes, com papel próprio em cada um."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flask import Flask, session

from core import auth, storage


class MultiTenantUserTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.a = storage.create_tenant(name="Cliente A", slug="cliente-a", owner_name="Ana Gestora",
                                       owner_email="ana@teste.com", password="Senha@Teste1")
        self.b = storage.create_tenant(name="Cliente B", slug="cliente-b", owner_name="Bia Gestora",
                                       owner_email="bia@teste.com", password="Senha@Teste1")
        invite = storage.create_invite(self.b["id"], name="Ana", email="ana@teste.com", role="client")
        self.ana = storage.accept_invite(invite["token"], password="Senha@Teste1")
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "test-secret"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_existing_account_joins_with_its_own_password(self):
        tenants = {item["tenant_id"]: item["role"] for item in storage.list_user_tenants(self.ana["id"])}
        self.assertEqual(tenants, {self.a["id"]: "client_admin", self.b["id"]: "client"})

    def test_wrong_password_does_not_join(self):
        c = storage.create_tenant(name="Cliente C", slug="cliente-c", owner_name="Caio Gestor",
                                  owner_email="caio@teste.com", password="Senha@Teste1")
        invite = storage.create_invite(c["id"], name="Ana", email="ana@teste.com")
        self.assertTrue(storage.get_invite(invite["token"])["has_account"])
        with self.assertRaises(ValueError):
            storage.accept_invite(invite["token"], password="errada123")
        self.assertFalse(storage.user_has_tenant(self.ana["id"], c["id"]))

    def test_role_is_per_client(self):
        self.assertEqual(storage.get_user(self.ana["id"], self.a["id"])["role"], "client_admin")
        self.assertEqual(storage.get_user(self.ana["id"], self.b["id"])["role"], "client")

    def test_switching_only_to_own_clients_and_remembering_last(self):
        c = storage.create_tenant(name="Cliente C", slug="cliente-c", owner_name="Caio Gestor",
                                  owner_email="caio@teste.com", password="Senha@Teste1")
        with self.flask_app.test_request_context("/"):
            auth.sign_in(storage.authenticate("ana@teste.com", "Senha@Teste1"))
            auth.select_active_tenant(self.a["id"])
            self.assertEqual(auth.active_tenant()["id"], self.a["id"])
            with self.assertRaises(PermissionError):
                auth.select_active_tenant(c["id"])
        self.assertEqual(storage.authenticate("ana@teste.com", "Senha@Teste1")["tenant_id"], self.a["id"])

    def test_removing_one_client_keeps_the_others(self):
        removed = storage.delete_user(self.ana["id"], tenant_id=self.b["id"])
        self.assertFalse(removed["account_deleted"])
        user = storage.authenticate("ana@teste.com", "Senha@Teste1")
        self.assertEqual(user["tenant_id"], self.a["id"])

    def test_suspended_in_one_client_still_enters_the_other(self):
        storage.set_user_active(self.ana["id"], False, tenant_id=self.b["id"])
        self.assertEqual([t["tenant_id"] for t in storage.list_user_tenants(self.ana["id"])], [self.a["id"]])
        self.assertIsNotNone(storage.authenticate("ana@teste.com", "Senha@Teste1"))

    def test_deleting_a_client_keeps_people_who_have_others(self):
        storage.delete_tenant(self.b["id"])
        self.assertIsNotNone(storage.authenticate("ana@teste.com", "Senha@Teste1"))
        self.assertIsNone(storage.authenticate("bia@teste.com", "Senha@Teste1"))

    def test_new_client_can_reuse_existing_owner(self):
        c = storage.create_tenant(name="Cliente C", slug="cliente-c", owner_name="Ana",
                                  owner_email="ana@teste.com", password=None)
        self.assertEqual(c["owner_email"], "ana@teste.com")
        self.assertTrue(storage.user_has_tenant(self.ana["id"], c["id"]))

    def test_cannot_invite_who_already_has_this_client(self):
        with self.assertRaises(ValueError):
            storage.create_invite(self.a["id"], name="Ana", email="ana@teste.com")

    def test_session_falls_back_when_client_access_is_removed(self):
        with self.flask_app.test_request_context("/"):
            session["user_id"] = self.ana["id"]
            session["active_tenant_id"] = self.b["id"]
            storage.delete_user(self.ana["id"], tenant_id=self.b["id"])
            self.assertEqual(auth.current_user()["tenant_id"], self.a["id"])


if __name__ == "__main__":
    unittest.main()
