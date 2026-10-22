import unittest

from ui.tables import _apply_state


class TableFilterTests(unittest.TestCase):
    def setUp(self):
        self.spec = {
            "source": lambda _period: [
                {"nome": "Campanha ativa", "status": "active", "investimento": 10},
                {"nome": "Campanha pausada", "status": "paused", "investimento": 20},
                {"nome": "Outra pausada", "status": "paused", "investimento": 5},
            ],
            "sort": "investimento",
        }

    def test_status_filter_is_applied(self):
        rows, total, page, pages = _apply_state(
            self.spec,
            {
                "period": "7d", "status": "paused", "q": "", "sort": "investimento",
                "dir": "desc", "size": 10, "page": 1,
            },
        )
        self.assertEqual(total, 2)
        self.assertEqual([row["nome"] for row in rows], ["Campanha pausada", "Outra pausada"])
        self.assertEqual((page, pages), (1, 1))

    def test_search_and_status_work_together(self):
        rows, total, _, _ = _apply_state(
            self.spec,
            {
                "period": "30d", "status": "paused", "q": "outra", "sort": "investimento",
                "dir": "desc", "size": 10, "page": 1,
            },
        )
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["nome"], "Outra pausada")


if __name__ == "__main__":
    unittest.main()
