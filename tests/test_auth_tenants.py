from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from flask import Flask, session

from core import auth
from core import data
from core import storage
from core.branding import brand_for_user, style_variables
from core.integrations import MetaAdsClient


class TenantStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def create_client(self):
        return storage.create_tenant(
            name="Cliente Teste",
            slug="cliente-teste",
            owner_name="Gestora Teste",
            owner_email="gestora@teste.com",
            password="Senha@Teste1",
            primary_color="#3366CC",
            secondary_color="#112233",
        )

    def test_admin_is_seeded_and_password_is_checked(self):
        self.assertEqual(
            storage.authenticate("admin", "admin")["role"],
            "superadmin",
        )
        self.assertIsNone(storage.authenticate("admin", "senha-errada"))

    def test_tenant_and_owner_are_created_atomically(self):
        tenant = self.create_client()
        user = storage.authenticate("gestora@teste.com", "Senha@Teste1")

        self.assertEqual(user["tenant_id"], tenant["id"])
        self.assertEqual(user["role"], "client_admin")
        self.assertEqual(storage.get_tenant_by_slug("cliente-teste")["id"], tenant["id"])
        self.assertIsNone(storage.get_tenant_by_slug("slug inválido"))
        self.assertEqual(storage.tenant_stats(), {"tenants": 1, "active": 1, "users": 1})

    def test_duplicate_slug_does_not_leave_an_orphan_user(self):
        self.create_client()
        with self.assertRaises(ValueError):
            storage.create_tenant(
                name="Outro Cliente",
                slug="cliente-teste",
                owner_name="Outro Gestor",
                owner_email="outro@teste.com",
                password="Senha@Teste2",
            )
        self.assertEqual(len(storage.list_tenants()), 1)
        self.assertIsNone(storage.authenticate("outro@teste.com", "Senha@Teste2"))

    def test_inactive_tenant_cannot_authenticate(self):
        tenant = self.create_client()
        storage.update_tenant_branding(
            tenant["id"],
            name=tenant["name"],
            primary_color=tenant["primary_color"],
            secondary_color=tenant["secondary_color"],
            logo_data=None,
            status="inactive",
        )
        self.assertIsNone(storage.authenticate("gestora@teste.com", "Senha@Teste1"))

    def test_light_brand_receives_dark_foreground(self):
        variables = style_variables({"primary_color": "#FFD400", "secondary_color": "#111111"})
        self.assertEqual(variables["--brand-contrast"], "#0B0B0D")

    def test_admin_uses_v4_brand_and_client_keeps_its_tenant_brand(self):
        admin_brand = brand_for_user({"role": "superadmin", "tenant_id": None})
        client_brand = brand_for_user(
            {
                "role": "client_admin", "tenant_id": 7, "tenant_name": "Cliente Azul",
                "logo_data": "data:image/png;base64,YQ==", "primary_color": "#3366CC",
                "secondary_color": "#112233",
            }
        )

        self.assertEqual(admin_brand["name"], "V4 Company")
        self.assertTrue(admin_brand["logo_data"].startswith("data:image/png;base64,"))
        self.assertEqual(client_brand["name"], "Cliente Azul")
        self.assertEqual(client_brand["primary_color"], "#3366CC")

    def test_media_accounts_are_normalized_and_cannot_cross_tenants(self):
        first = storage.create_tenant(
            name="Cliente Mídia", slug="cliente-midia", owner_name="Gestora Mídia",
            owner_email="midia@teste.com", password="Senha@Teste1",
            meta_ad_account_id="123-456", google_ads_customer_id="123-456-7890",
        )
        self.assertEqual(first["meta_ad_account_id"], "act_123456")
        self.assertEqual(first["google_ads_customer_id"], "1234567890")

        with self.assertRaisesRegex(ValueError, "Meta Ads"):
            storage.create_tenant(
                name="Outro Cliente", slug="outro-cliente", owner_name="Outro Gestor",
                owner_email="outro-midia@teste.com", password="Senha@Teste2",
                meta_ad_account_id="act_123456",
            )
        self.assertEqual(len(storage.list_tenants()), 1)

    def test_meta_creative_prefers_original_image_over_small_thumbnail(self):
        url, quality = MetaAdsClient._creative_image_url(
            {
                "thumbnail_url": "https://cdn.example/thumb-64.jpg",
                "object_story_spec": {
                    "video_data": {"image_url": "https://cdn.example/original-1080.jpg"}
                },
            }
        )
        self.assertEqual(url, "https://cdn.example/original-1080.jpg")
        self.assertEqual(quality, "original")

        fallback, fallback_quality = MetaAdsClient._creative_image_url(
            {"thumbnail_url": "https://cdn.example/thumb-64.jpg"}
        )
        self.assertEqual(fallback, "https://cdn.example/thumb-64.jpg")
        self.assertEqual(fallback_quality, "thumbnail")

    def test_meta_ad_rows_keep_hierarchy_for_the_expanded_card(self):
        rows = data._meta_entity_rows(
            [
                {
                    "ad_id": "ad-123",
                    "ad_name": "Criativo Agosto",
                    "campaign_name": "Campanha Principal",
                    "adset_name": "Público Remarketing",
                    "spend": "125.40",
                    "impressions": "10000",
                    "clicks": "250",
                }
            ],
            "ad",
            {"ad-123": "ACTIVE"},
            {"ad-123": {"url": "https://cdn.example/ad.jpg", "quality": "original"}},
        )

        self.assertEqual(rows[0]["id"], "ad-123")
        self.assertEqual(rows[0]["campanha"], "Campanha Principal")
        self.assertEqual(rows[0]["conjunto"], "Público Remarketing")
        self.assertEqual(rows[0]["creative_url"], "https://cdn.example/ad.jpg")

    def test_meta_dashboard_reads_persisted_rows_without_calling_api(self):
        tenant = storage.create_tenant(
            name="Cliente Meta", slug="cliente-meta", owner_name="Gestora Meta",
            owner_email="meta@teste.com", password="Senha@Teste1", meta_ad_account_id="123",
        )
        common = {
            "tenant_id": tenant["id"], "platform": "meta", "metric_date": "2026-08-10",
            "account_id": "act_123", "status": "active", "investimento": 10.0,
            "receita": 0.0, "impressoes": 1000, "cliques": 20, "leads": 2.0,
            "conversoes": 2.0, "alcance": 800, "updated_at": "2026-08-10T12:00:00+00:00",
        }
        storage.replace_media_rows(
            tenant["id"], "meta", "2026-08-10", "2026-08-10",
            [
                {**common, "level": "account", "entity_id": "act_123", "name": "Cliente Meta"},
                {
                    **common, "level": "ad", "entity_id": "ad-1", "name": "Anuncio principal",
                    "campaign_id": "campaign-1", "campaign_name": "Campanha principal",
                    "parent_id": "adset-1", "parent_name": "Conjunto principal",
                },
            ],
        )
        storage.set_media_sync_state(
            tenant["id"], "meta", "success", finished_at="2026-08-10T12:00:00+00:00",
            window_start="2026-08-10", window_end="2026-08-10", rows_synced=2,
        )
        loaded = data._load_meta(
            "act_123", date(2026, 8, 1), date(2026, 8, 11),
            date(2026, 7, 21), date(2026, 7, 31), tenant["id"],
        )

        self.assertEqual(loaded["status"], "connected")
        self.assertEqual(len(loaded["campaigns"]), 1)
        self.assertEqual(len(loaded["adsets"]), 1)
        self.assertEqual(len(loaded["ads"]), 1)
        self.assertEqual(loaded["series"][9]["investimento"], 10.0)

    def test_calendar_periods_use_current_month_and_year(self):
        today = date.today()
        tenant = self.create_client()
        month = data.get_dataset("month", tenant_id=tenant["id"])
        year = data.get_dataset("year", tenant_id=tenant["id"])

        self.assertEqual(month["range"]["start"], today.replace(day=1).isoformat())
        self.assertEqual(year["range"]["start"], today.replace(month=1, day=1).isoformat())

    def test_admin_selects_any_tenant_but_client_is_pinned_to_own(self):
        first = self.create_client()
        second = storage.create_tenant(
            name="Segundo Cliente", slug="segundo-cliente", owner_name="Segundo Gestor",
            owner_email="segundo@teste.com", password="Senha@Teste2",
        )
        flask_app = Flask(__name__)
        flask_app.secret_key = "test-secret"

        with flask_app.test_request_context("/"):
            session["user_id"] = storage.authenticate("admin", "admin")["id"]
            self.assertEqual(auth.select_active_tenant(first["id"])["id"], first["id"])
            self.assertEqual(auth.active_tenant()["id"], first["id"])
            self.assertEqual(auth.select_active_tenant(second["id"])["id"], second["id"])

        with flask_app.test_request_context("/"):
            session["user_id"] = storage.authenticate("gestora@teste.com", "Senha@Teste1")["id"]
            self.assertEqual(auth.active_tenant()["id"], first["id"])
            with self.assertRaises(PermissionError):
                auth.select_active_tenant(second["id"])

    def test_unconfigured_tenant_gets_empty_dataset_not_mock_or_other_tenant_data(self):
        tenant = self.create_client()
        data.clear_cache()
        dataset = data.get_dataset("7d", tenant_id=tenant["id"])

        self.assertEqual(dataset["tenant_id"], tenant["id"])
        self.assertEqual(dataset["connections"]["meta"]["status"], "unconfigured")
        self.assertEqual(dataset["connections"]["google"]["status"], "unconfigured")
        self.assertEqual(dataset["campaigns"], [])
        self.assertEqual(dataset["totals"]["investimento"], 0)


if __name__ == "__main__":
    unittest.main()
