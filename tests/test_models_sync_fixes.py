"""Models config: displayName from model ID, clearManualOverride restores previous rates (invented data, no network)."""

import json
import os
import tempfile
import unittest

import server

RATE_KEYS = ("input", "output", "thinking", "cache_read_input",
             "regional_input", "regional_output", "regional_thinking", "regional_cache_read_input")


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


def make_entry(mid: str, **extra) -> dict:
    e = {
        "modelId": mid, "displayName": mid, "publisher": "google", "status": "active",
        "input": 1.0, "output": 4.0, "thinking": 4.0, "cache_read_input": 0.1,
        "regional_input": 1.1, "regional_output": 4.4, "regional_thinking": 4.4, "regional_cache_read_input": 0.11,
        "source": "GCP_BILLING_API:C7E2-9256-1C43", "lastSkuIdGlobal": "sku-g", "lastSkuIdRegional": "sku-r",
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }
    e.update(extra)
    return e


class TestModelsSyncFixes(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = load_app_namespace()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "models_pricing_config.json")
        self.ns["DATA_DIR"] = self.tmp.name
        self.ns["MODELS_PRICING_FILE"] = self.path
        self.ns["_MODELS_PRICING_MEM_CACHE"].update({"mtime": 0.0, "data": None})

    def _seed(self, models: dict) -> None:
        cfg = self.ns["_build_default_models_pricing_config"]()
        cfg["models"] = models
        cfg["modelListFromApi"] = True
        self.ns["save_models_pricing_config"](cfg)

    def _update(self, models: dict) -> dict:
        ok, err, cfg = self.ns["validate_and_apply_models_pricing_update"]({"models": models})
        self.assertTrue(ok, err)
        return cfg["models"]

    def _rates(self, entry: dict) -> dict:
        return {k: entry[k] for k in RATE_KEYS}

    def test_override_then_clear_restores_rates(self) -> None:
        self._seed({"fake-model-a": make_entry("fake-model-a")})
        orig = self._rates(make_entry("fake-model-a"))
        m = self._update({"fake-model-a": {"input": 9.0, "output": 20.0}})["fake-model-a"]
        self.assertEqual(m["input"], 9.0)
        self.assertEqual(m["source"], "MANUAL")
        m = self._update({"fake-model-a": {"clearManualOverride": True}})["fake-model-a"]
        self.assertEqual(self._rates(m), orig)
        self.assertNotIn("manualOverride", m)
        self.assertNotIn("preOverrideRates", m)

    def test_double_override_then_clear_restores_originals(self) -> None:
        self._seed({"fake-model-a": make_entry("fake-model-a")})
        orig = self._rates(make_entry("fake-model-a"))
        self._update({"fake-model-a": {"input": 9.0}})
        self._update({"fake-model-a": {"input": 7.0, "output": 15.0}})
        m = self._update({"fake-model-a": {"clearManualOverride": True}})["fake-model-a"]
        self.assertEqual(self._rates(m), orig)

    def test_clear_does_not_revert_prices_refreshed_after_the_override(self) -> None:
        self._seed({"fake-model-a": make_entry("fake-model-a")})
        self._update({"fake-model-a": {"input": 9.0}})  # override only the input rate
        cfg = self.ns["load_models_pricing_config"]()
        cfg["models"]["fake-model-a"]["output"] = 5.5  # a later catalog sync refreshed another rate
        self.ns["save_models_pricing_config"](cfg)
        m = self._update({"fake-model-a": {"clearManualOverride": True}})["fake-model-a"]
        self.assertEqual(m["input"], 1.0)  # restored
        self.assertEqual(m["output"], 5.5)  # NOT reverted to the stale 4.0

    def test_old_override_without_snapshot_is_not_snapshotted_as_original(self) -> None:
        legacy = make_entry("fake-model-a", input=9.0, manualOverride={"input": 9.0}, source="MANUAL")
        self._seed({"fake-model-a": legacy})
        self._update({"fake-model-a": {"output": 12.0}})
        m = self.ns["load_models_pricing_config"]()["models"]["fake-model-a"]
        self.assertNotIn("input", m.get("preOverrideRates", {}))  # 9.0 is a manual value, not an original
        self.assertIn("output", m["preOverrideRates"])

    def test_clear_without_snapshot_keeps_old_behaviour(self) -> None:
        self._seed({"fake-model-a": make_entry("fake-model-a", input=9.0, manualOverride={"input": 9.0}, source="MANUAL")})
        m = self._update({"fake-model-a": {"clearManualOverride": True}})["fake-model-a"]
        self.assertEqual(m["input"], 9.0)
        self.assertNotIn("manualOverride", m)

    @staticmethod
    def _fake_gcp(google_models: list):
        def fake(url, token, timeout=20, user_project=None):
            if "/publishers/google/models" in url:
                return 200, {"publisherModels": google_models}
            if "/publishers/anthropic/models" in url:
                return 200, {"publisherModels": []}
            return 200, {}
        return fake

    def test_sync_sets_display_name_to_id_and_fixes_numeric(self) -> None:
        self._seed({
            "fake-model-old": make_entry("fake-model-old", displayName="20251001"),
            "fake-model-hand": make_entry("fake-model-hand", displayName="My Fast Model"),
        })
        self.ns["gcp_api_get"] = self._fake_gcp([
            {"name": "publishers/google/models/fake-model-new@001", "versionId": "001"},
            {"name": "publishers/google/models/fake-model-old@001", "versionId": "001"},
            {"name": "publishers/google/models/fake-model-hand@001", "versionId": "001"},
        ])
        models = self.ns["sync_models_and_pricing_from_gcp_api"]("fake-token")["models"]
        self.assertEqual(models["fake-model-new"]["displayName"], "fake-model-new")
        self.assertEqual(models["fake-model-old"]["displayName"], "fake-model-old")
        self.assertEqual(models["fake-model-hand"]["displayName"], "My Fast Model")

    def test_sync_keeps_snapshot_and_file_valid(self) -> None:
        self._seed({"fake-model-a": make_entry("fake-model-a")})
        orig = self._rates(make_entry("fake-model-a"))
        self._update({"fake-model-a": {"input": 9.0}})
        self.ns["gcp_api_get"] = self._fake_gcp([{"name": "publishers/google/models/fake-model-a@001"}])
        models = self.ns["sync_models_and_pricing_from_gcp_api"]("fake-token")["models"]
        self.assertEqual(models["fake-model-a"]["input"], 9.0)
        self.assertIn("preOverrideRates", models["fake-model-a"])
        with open(self.path, encoding="utf-8") as f:
            json.load(f)
        m = self._update({"fake-model-a": {"clearManualOverride": True}})["fake-model-a"]
        self.assertEqual(self._rates(m), orig)


if __name__ == "__main__":
    unittest.main()
