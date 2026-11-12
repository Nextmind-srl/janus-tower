"""Dialogflow CX (token LLM stimati) segue le impostazioni dei servizi gestiti (managedServiceSavingsPct / CacheHitRatio).

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


class TestDialogflowManagedSettings(unittest.TestCase):
    TOKENS = 1_000_000

    def setUp(self) -> None:
        self.ns = load_app_namespace()

    def _run(self, savings_pct: float, hit_pct: float) -> dict:
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
            series = [{
                "resource": {"labels": {"location": "eu"}},
                "metric": {"labels": {"base_model": "gemini-2.5-flash"}},
                "points": [{
                    "value": {"int64Value": str(self.TOKENS)},
                    "interval": {"endTime": "2026-11-01T00:00:00Z"},
                }],
            }]
            result = defaultdict(float, {"models": {}, "dailySeries": {}, "credentialsUsage": {}})
            features = {}
            ns["_process_dialogflow_llm_tokens"](
                {"df_multi": [], "df_loc": series}, "proj-test", "tok", "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z",
                True, {"dialogflow.googleapis.com"}, 200, set(), features, result,
            )
            cred = next(iter(result["credentialsUsage"].values()))
            model = next(iter(result["models"].values()))
            day = result["dailySeries"]["2026-11-01"]
            return {"result": result, "cred": cred, "model": model, "day": day}

    def test_default_savings_zero_keeps_current_cost(self) -> None:
        out = self._run(0.0, 0.0)
        r = out["result"]
        gross = r["otherAiGrossCostUsd"]
        self.assertGreater(gross, 0.0)
        self.assertAlmostEqual(r["otherAiCostUsd"], gross, places=9)
        self.assertAlmostEqual(r["estimatedCostUsd"], gross, places=9)
        self.assertEqual(r["otherAiCacheSavingsUsd"], 0.0)
        self.assertEqual(r["cachedTokens"], 0)
        self.assertAlmostEqual(out["day"]["otherAiCostUsd"], gross, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], gross, places=9)
        self.assertAlmostEqual(out["model"]["costUsd"], gross, places=9)

    def test_full_savings_zeroes_cost_but_keeps_usage(self) -> None:
        base = self._run(0.0, 0.0)["result"]["otherAiGrossCostUsd"]
        out = self._run(100.0, 0.0)
        r = out["result"]
        self.assertAlmostEqual(r["otherAiGrossCostUsd"], base, places=9)
        self.assertAlmostEqual(r["otherAiCacheSavingsUsd"], base, places=9)
        self.assertAlmostEqual(r["otherAiCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(r["estimatedCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["day"]["otherAiCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["day"]["costUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], 0.0, places=9)
        self.assertAlmostEqual(out["model"]["costUsd"], 0.0, places=9)
        self.assertEqual(r["totalTokens"], self.TOKENS)

    def test_half_savings_halves_cost_and_cache_ratio_applies(self) -> None:
        base = self._run(0.0, 0.0)["result"]["otherAiGrossCostUsd"]
        out = self._run(50.0, 40.0)
        r = out["result"]
        self.assertAlmostEqual(r["otherAiCostUsd"], base / 2.0, places=9)
        self.assertAlmostEqual(r["otherAiCacheSavingsUsd"], base / 2.0, places=9)
        self.assertAlmostEqual(out["cred"]["estimatedCostUsd"], base / 2.0, places=9)
        self.assertEqual(r["cachedTokens"], int(round(self.TOKENS * 0.82 * 0.40)))


if __name__ == "__main__":
    unittest.main()
