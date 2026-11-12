"""Window slicing scales every monetary field of infraServices rows (invented data, no network)."""

import unittest
from datetime import datetime, timedelta

import server


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


DAYS = [(datetime(2026, 10, 30) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]


def payload() -> dict:
    # Enough inference traffic in every window so the project counts as a real AI workload (infra not excluded)
    daily = {d: {"requests": 100, "inferenceRequests": 100, "tokens": 100000, "totalTokens": 100000,
                 "invocations": 100, "costUsd": 1.0, "otherAiCostUsd": 1.0} for d in DAYS}
    rows = [
        {"service": "svc-a", "costUsd": 30.0, "grossCostUsd": 60.0, "savingsUsd": 30.0,
         "negotiatedSavingsUsd": 15.0, "cudSavingsUsd": 15.0, "unroundedEur": 27.0, "netCostUsd": 30.0,
         "activeDays": 30, "details": "Invented service, 30 days of use (30 days total)"},
        {"service": "svc-b", "costUsd": 0.0, "grossCostUsd": 0.0, "savingsUsd": 0.0,
         "estimateStatus": "not_estimable", "activeDays": 12, "details": "not estimable"},
    ]
    return {
        "days": 30, "scannedAt": "2026-10-30T12:00:00Z",
        "projects": [{"dailySeries": daily, "infraServices": rows}],
    }


class TestSliceInfra(unittest.TestCase):
    def setUp(self) -> None:
        self.fn = load_app_namespace()["slice_cached_payload_for_days"]

    def _rows(self, days):
        p = self.fn(payload(), days, {})["projects"][0]
        return p, {r["service"]: r for r in p["infraServices"]}

    def test_all_fields_scaled(self) -> None:
        p, r = self._rows(7)
        a, k = r["svc-a"], 7 / 30
        for key, orig in (("costUsd", 30.0), ("grossCostUsd", 60.0), ("savingsUsd", 30.0),
                          ("negotiatedSavingsUsd", 15.0), ("cudSavingsUsd", 15.0),
                          ("unroundedEur", 27.0), ("netCostUsd", 30.0)):
            self.assertAlmostEqual(a[key], orig * k, places=3, msg=key)
        self.assertEqual(a["activeDays"], 7)
        self.assertEqual(a["details"], "Invented service, 7 days of use (30 days total)")
        self.assertAlmostEqual(p["infraCostUsd"], 7.0, places=3)
        self.assertAlmostEqual(p["infraGrossCostUsd"], 14.0, places=3)
        self.assertAlmostEqual(p["infraSavingsUsd"], 7.0, places=3)

    def test_legacy_gg_details_still_follow_the_window(self) -> None:
        pl = payload()
        pl["projects"][0]["infraServices"][0]["details"] = "Servizio inventato, 30 gg di uso (30 gg totali)"
        p = self.fn(pl, 7, {})["projects"][0]
        self.assertEqual(p["infraServices"][0]["details"], "Servizio inventato, 7 gg di uso (30 gg totali)")

    def test_not_estimable_row_intact(self) -> None:
        _, r = self._rows(7)
        b = r["svc-b"]
        self.assertEqual(b["costUsd"], 0.0)
        self.assertEqual(b["grossCostUsd"], 0.0)
        self.assertEqual(b["activeDays"], 7)
        self.assertEqual(b["details"], "not estimable")
        self.assertEqual(b["estimateStatus"], "not_estimable")

    def test_same_window_no_change(self) -> None:
        p, r = self._rows(30)
        a = r["svc-a"]
        self.assertEqual(a["costUsd"], 30.0)
        self.assertEqual(a["savingsUsd"], 30.0)
        self.assertEqual(a["unroundedEur"], 27.0)
        self.assertEqual(a["activeDays"], 30)
        self.assertIn("30 days of use", a["details"])
        self.assertAlmostEqual(p["infraCostUsd"], 30.0, places=3)


if __name__ == "__main__":
    unittest.main()
