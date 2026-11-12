"""Dialogflow CX Session Turns (DetectIntent) segue managedServiceSavingsPct.

Run from the repository root:  python -m unittest discover -s tests -v
"""

from collections import defaultdict
from pathlib import Path
import tempfile
import unittest

import server


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


class TestDialogflowSessionTurns(unittest.TestCase):
    TURNS = 1000
    RATE = 0.012
    DAY = "2026-11-01T00:00:00Z"

    def setUp(self) -> None:
        self.ns = load_app_namespace()

    def _run(self, savings_pct: float, hit_pct: float = 0.0, service: str = "dialogflow.googleapis.com") -> dict:
        ns = self.ns
        with tempfile.TemporaryDirectory() as tmp:
            ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            cfg = ns["load_models_pricing_config"]()
            cfg.setdefault("billingSettings", {}).update(
                {"managedServiceSavingsPct": savings_pct, "managedServiceCacheHitRatioPct": hit_pct}
            )
            ns["save_models_pricing_config"](cfg)
            ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            empty = ns["empty_day_bucket"]
            result = defaultdict(float, {"models": {}, "dailySeries": {}, "credentialsUsage": {}})
            c_entry = defaultdict(float, {"costSource": "NONE"})
            p_day, c_day = empty(), empty()
            ns["_apply_managed_ai_service_point"](
                result, c_entry, p_day, c_day, service,
                "google.cloud.dialogflow.cx.v3.Sessions.DetectIntent", "eu", self.DAY, self.TURNS,
            )
            model = next(iter(result["models"].values()))
            return {"result": result, "cred": c_entry, "p_day": p_day, "c_day": c_day, "model": model}

    def test_zero_savings_keeps_current_cost(self) -> None:
        out = self._run(0.0)
        gross = self.TURNS * self.RATE
        r = out["result"]
        self.assertAlmostEqual(r["otherAiGrossCostUsd"], gross, places=9)
        self.assertAlmostEqual(r["otherAiCostUsd"], gross, places=9)
        self.assertAlmostEqual(r["estimatedCostUsd"], gross, places=9)
        self.assertEqual(r["otherAiCacheSavingsUsd"], 0.0)
        self.assertAlmostEqual(out["p_day"]["costUsd"], gross, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], gross, places=9)
        self.assertAlmostEqual(out["model"]["costUsd"], gross, places=9)

    def test_half_savings_halves_net_keeps_gross(self) -> None:
        gross = self.TURNS * self.RATE
        out = self._run(50.0, 40.0)
        r = out["result"]
        self.assertAlmostEqual(r["otherAiGrossCostUsd"], gross, places=9)
        self.assertAlmostEqual(r["otherAiCacheSavingsUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(r["otherAiCostUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(r["estimatedCostUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(out["p_day"]["otherAiCostUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(out["c_day"]["costUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(out["cred"]["grossCostUsd"], gross, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], gross / 2.0, places=9)
        self.assertAlmostEqual(out["model"]["costUsd"], gross / 2.0, places=9)
        self.assertEqual(r["cachedTokens"], 0)  # nessun token stimato: cache hit solo informativa

    def test_full_savings_zero_net_usage_unchanged(self) -> None:
        gross = self.TURNS * self.RATE
        out = self._run(100.0)
        r = out["result"]
        self.assertAlmostEqual(r["otherAiGrossCostUsd"], gross, places=9)
        self.assertAlmostEqual(r["otherAiCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(r["estimatedCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["p_day"]["costUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], 0.0, places=9)
        self.assertEqual(out["model"]["invocations"], self.TURNS)
        self.assertEqual(out["model"]["dailySeries"][self.DAY]["requests"], self.TURNS)

    def test_ces_service_follows_too(self) -> None:
        gross = self.TURNS * self.RATE
        out = self._run(50.0, service="ces.googleapis.com")
        self.assertAlmostEqual(out["result"]["otherAiCostUsd"], gross / 2.0, places=9)

    def test_no_double_counting_between_project_and_credential(self) -> None:
        out = self._run(25.0)
        net = self.TURNS * self.RATE * 0.75
        self.assertAlmostEqual(out["result"]["estimatedCostUsd"], net, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], net, places=9)
        self.assertAlmostEqual(out["p_day"]["costUsd"], net, places=9)
        self.assertAlmostEqual(out["c_day"]["costUsd"], net, places=9)


if __name__ == "__main__":
    unittest.main()
