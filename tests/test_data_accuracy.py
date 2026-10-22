"""
Números iguais aos do Gerenciador.

Cada teste aqui fixa uma causa REAL de divergência que já apareceu em
produção — não um detalhe de implementação.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, session

from core import auth, data, storage
from core.integrations import MetaAdsClient
from core.sync import _base_row


class MetaInsightsSplitTests(unittest.TestCase):
    """
    Pedir `actions` junto com `spend` na quebra diária faz a Meta zerar gasto
    e impressões em algumas contas. Entrega e ações vêm em consultas
    separadas e são juntadas por dia e entidade.
    """

    def setUp(self):
        self.client = MetaAdsClient()
        self.calls: list[dict] = []

        def fake_all(_path, params, max_pages=20):
            self.calls.append(params)
            fields = params["fields"].split(",")
            if "spend" in fields:
                return [
                    {"ad_id": "1", "spend": "10.5", "impressions": "100", "date_start": "2026-10-01"},
                    {"ad_id": "2", "spend": "4", "impressions": "50", "date_start": "2026-10-01"},
                ]
            return [
                {"ad_id": "1", "date_start": "2026-10-01",
                 "actions": [{"action_type": "lead", "value": "3"}]},
                # conversão atribuída a um dia sem entrega
                {"ad_id": "1", "date_start": "2026-10-02", "date_stop": "2026-10-02",
                 "actions": [{"action_type": "lead", "value": "1"}]},
            ]

        self.client._all = fake_all

    def test_delivery_and_actions_never_share_a_request(self):
        self.client.insights("act_1", start="2026-10-01", end="2026-10-02", level="ad", time_increment=1)
        self.assertEqual(len(self.calls), 2)
        for params in self.calls:
            fields = params["fields"].split(",")
            self.assertFalse("spend" in fields and "actions" in fields)
            self.assertNotIn("cost_per_action_type", fields)

    def test_rows_are_merged_by_day_and_entity(self):
        rows = self.client.insights("act_1", start="2026-10-01", end="2026-10-02", level="ad", time_increment=1)
        by_key = {(row["date_start"], row["ad_id"]): row for row in rows}

        self.assertEqual(by_key[("2026-10-01", "1")]["spend"], "10.5")
        self.assertEqual(by_key[("2026-10-01", "1")]["actions"][0]["value"], "3")
        self.assertNotIn("actions", by_key[("2026-10-01", "2")])
        # o lead atrasado não some por não ter entrega no dia
        self.assertEqual(by_key[("2026-10-02", "1")]["actions"][0]["value"], "1")
        self.assertEqual(sum(float(row.get("spend", 0)) for row in rows), 14.5)


class PeriodWindowTests(unittest.TestCase):
    """"Últimos 30 dias" no Gerenciador termina ontem; aqui também."""

    def _range(self, period_id: str, today: str) -> dict:
        data.clear_cache()
        return data._dataset(period_id, 0, None, None, today)["range"]

    def test_rolling_windows_end_yesterday(self):
        self.assertEqual(self._range("30d", "2026-10-21"), {"start": "2026-09-21", "end": "2026-10-20"})
        self.assertEqual(self._range("7d", "2026-10-21"), {"start": "2026-10-14", "end": "2026-10-20"})
        self.assertEqual(self._range("yesterday", "2026-10-21"), {"start": "2026-10-20", "end": "2026-10-20"})

    def test_today_and_calendar_periods_include_today(self):
        self.assertEqual(self._range("today", "2026-10-21"), {"start": "2026-10-21", "end": "2026-10-21"})
        self.assertEqual(self._range("month", "2026-10-21"), {"start": "2026-10-01", "end": "2026-10-21"})

    def test_previous_period_has_the_same_length(self):
        data.clear_cache()
        dataset = data._dataset("30d", 0, None, None, "2026-10-21")
        self.assertEqual(len(dataset["series"]), 30)
        self.assertEqual(len(dataset["meta"]["series"]), 30)


class MasterLandingTests(unittest.TestCase):
    """O master não cai num cliente que não escolheu (era sempre a Reconlog)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Primeiro Cliente", slug="primeiro", owner_name="Gestor",
            owner_email="gestor@teste.com", password="Senha@Teste1",
        )
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "test-secret"

    def tearDown(self):
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_master_without_choice_has_no_active_tenant(self):
        with self.flask_app.test_request_context("/"):
            session["user_id"] = storage.authenticate("admin", "admin")["id"]
            self.assertIsNone(auth.active_tenant())

    def test_master_choice_is_kept(self):
        with self.flask_app.test_request_context("/"):
            session["user_id"] = storage.authenticate("admin", "admin")["id"]
            auth.select_active_tenant(self.tenant["id"])
            self.assertEqual(auth.active_tenant()["id"], self.tenant["id"])

    def test_client_is_still_pinned_to_own_tenant(self):
        with self.flask_app.test_request_context("/"):
            session["user_id"] = storage.authenticate("gestor@teste.com", "Senha@Teste1")["id"]
            self.assertEqual(auth.active_tenant()["id"], self.tenant["id"])

    def test_fingerprint_changes_only_when_numbers_change(self):
        before = storage.media_fingerprint(self.tenant["id"])
        self.assertEqual(before, storage.media_fingerprint(self.tenant["id"]))
        day = (date.today() - timedelta(days=1)).isoformat()
        row = _base_row(self.tenant["id"], "google", "1", day, "account", "1")
        row.update({"investimento": 12.5, "impressoes": 10, "leads": 1.0})
        storage.replace_media_rows(self.tenant["id"], "google", day, day, [row])
        self.assertNotEqual(before, storage.media_fingerprint(self.tenant["id"]))


class MetaReachTests(unittest.TestCase):
    """Alcance é do período inteiro: a Meta não informa por dia e não se soma."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "pulse-test.db"
        storage.init_db()
        self.tenant = storage.create_tenant(
            name="Cliente Meta", slug="cliente-meta", owner_name="Gestor",
            owner_email="meta@teste.com", password="Senha@Teste1", meta_ad_account_id="act_9",
        )
        self.original_totals = data.meta_ads.window_totals
        self.api_calls = 0

        def fake_totals(_account, start, end):
            self.api_calls += 1
            return {"spend": 0.0, "impressions": 0.0, "reach": 4321.0}

        data.meta_ads.window_totals = fake_totals

    def tearDown(self):
        data.meta_ads.window_totals = self.original_totals
        storage.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_reach_comes_from_the_period_and_is_cached(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)
        self.assertEqual(data._meta_period_reach(self.tenant["id"], "act_9", start, end), 4321.0)
        self.assertEqual(data._meta_period_reach(self.tenant["id"], "act_9", start, end), 4321.0)
        self.assertEqual(self.api_calls, 1)

    def test_api_failure_keeps_last_saved_value(self):
        end = date.today()
        storage.set_period_reach(self.tenant["id"], "meta", "act_9", "2026-01-01", end.isoformat(), 900)
        with storage.connection() as db:
            db.execute("UPDATE media_period_reach SET fetched_at = '2000-01-01T00:00:00+00:00'")

        def broken(*_args, **_kwargs):
            raise RuntimeError("fora do ar")

        data.meta_ads.window_totals = broken
        self.assertEqual(data._meta_period_reach(self.tenant["id"], "act_9", date(2026, 1, 1), end), 900.0)

    def test_frequency_is_impressions_over_period_reach(self):
        target = {"impressoes": 0}
        data._apply_reach(target, 400.0, 1000.0)
        self.assertEqual(target["alcance"], 400.0)
        self.assertEqual(target["frequencia"], 2.5)
        data._apply_reach(target, None, 1000.0)
        self.assertEqual((target["alcance"], target["frequencia"]), (0, 0.0))


class MetaDailyCheckTests(unittest.TestCase):
    """Quebra diária que não fecha com o total do período nunca é gravada."""

    def setUp(self):
        from core import sync

        self.sync = sync
        self.originals = (sync.meta_ads.insights, sync.meta_ads.window_totals, sync.time.sleep)
        sync.time.sleep = lambda _seconds: None
        sync.meta_ads.window_totals = lambda *_a, **_k: {"spend": 100.0, "impressions": 1000.0, "reach": 0.0}
        self.responses = []

        def fake_insights(_account, level, **_kwargs):
            good = self.responses[0]
            return [{"spend": "100" if good else "0", "impressions": "1000" if good else "0",
                     "date_start": "2026-10-01", **({"ad_id": "1"} if level == "ad" else {})}]

        sync.meta_ads.insights = fake_insights

    def tearDown(self):
        self.sync.meta_ads.insights, self.sync.meta_ads.window_totals, self.sync.time.sleep = self.originals

    def test_consistent_data_passes(self):
        self.responses = [True]
        account, ads = self.sync._checked_meta_insights("act_1", date(2026, 10, 1), date(2026, 10, 1))
        self.assertEqual(account[0]["spend"], "100")

    def test_zeroed_daily_data_is_refused(self):
        self.responses = [False]
        with self.assertRaises(self.sync.IntegrationError):
            self.sync._checked_meta_insights("act_1", date(2026, 10, 1), date(2026, 10, 1))


if __name__ == "__main__":
    unittest.main()
