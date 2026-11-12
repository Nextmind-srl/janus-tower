"""A5-4 - fasce di quota Gemini API scoperte dai metricDescriptors (dati inventati, nessuna rete)."""

import unittest

import server

PFX = "generativelanguage.googleapis.com/quota/generate_content_paid_tier"
DAY = "2026-10-01"


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


def desc(sfx: str, tail: str = "_input_token_count/usage") -> dict:
    return {"type": f"{PFX}{sfx}{tail}"}


class TestFasceQuota(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = load_app_namespace()
        self.calls = []

    def _discover(self, status, descriptors):
        def fake_get(url, token, timeout=12, user_project=None):
            self.calls.append(url)
            if status == "raise":
                raise RuntimeError("boom")
            return status, {"metricDescriptors": descriptors}
        self.ns["gcp_api_get"] = fake_get
        res = {}
        out = self.ns["_discover_gemini_tier_suffixes"]("p", "t", res)
        return out, res

    def test_extra_tiers_found(self) -> None:
        out, _ = self._discover(200, [desc(""), desc("_2"), desc("_4"), desc("_5")])
        self.assertEqual(out, ["", "_2", "_3", "_4", "_5"])
        self.assertIn("metricDescriptors", self.calls[0])

    def test_failure_or_empty_falls_back(self) -> None:
        for st, d in ((429, []), (500, [desc("_9")]), (200, []), ("raise", [])):
            out, _ = self._discover(st, d)
            self.assertEqual(out, ["", "_2", "_3"], st)

    def test_irrelevant_types_ignored(self) -> None:
        out, _ = self._discover(200, [desc("_4", "_output_token_count/usage"), desc("_x"), {"type": "other/metric"}, {}])
        self.assertEqual(out, ["", "_2", "_3"])

    def test_cap(self) -> None:
        out, _ = self._discover(200, [desc(f"_{i}") for i in range(4, 30)])
        self.assertEqual(len(out), 8)
        self.assertEqual(out[:3], ["", "_2", "_3"])

    def test_one_call_per_scan(self) -> None:
        self._discover(200, [desc("_4")])
        res = {"_geminiTierSfx": ["", "_2", "_3", "_4"]}
        self.assertEqual(self.ns["_discover_gemini_tier_suffixes"]("p", "t", res), ["", "_2", "_3", "_4"])
        self.assertEqual(len(self.calls), 1)

    def test_mon_specs_one_metric_per_spec(self) -> None:
        self.ns["gcp_api_get"] = lambda *a, **k: (200, {"metricDescriptors": [desc("_4")]})
        captured = {}

        def fake_fetch(pid, token, flt, s, e, group_by_fields=None, aligner="ALIGN_SUM"):
            captured[flt] = 1
            return []
        self.ns["fetch_monitoring_timeseries"] = fake_fetch
        result = {"geminiApiEnabled": True, "vertexEnabled": False}
        self.ns["_prefetch_project_monitoring_metrics"]("p", "t", "s", "e", True, 200, set(), set(), result)
        tier = [f for f in captured if "paid_tier" in f]
        self.assertEqual(len(tier), 4)
        self.assertTrue(any("paid_tier_4_input" in f for f in tier))
        self.assertTrue(all(" OR " not in f and "one_of" not in f for f in tier))
        self.assertNotIn("_geminiTierSfx", result)  # temporary helper key never stays in the result
        self.assertEqual(result["geminiQuotaTiers"], ["tier1", "tier2", "tier3", "tier4"])  # diagnostic: tiers actually read
        self.assertEqual(result["geminiQuotaDiscovery"], "ok")
        self.assertNotIn("_geminiTierOk", result)

    def test_consumption_sums_all_tiers(self) -> None:
        def ser(v):
            return [{"metric": {"labels": {"model": "gemini-2.5-flash"}},
                     "points": [{"interval": {"endTime": f"{DAY}T10:00:00Z"}, "value": {"int64Value": str(v)}}]}]
        mon = {"gemini_in_tok": ser(100), "gemini_in_tok_4": ser(10), "gemini_in_tok_5": ser(1),
               "gemini_out_tok": ser(7), "gemini_req_b": [], "gemini_resp_b": []}
        res = self.ns["empty_day_bucket"]()
        res.update({"geminiApiRequests": 1, "credentialsUsage": {}, "dailySeries": {}, "models": {},
                    "geminiRequestBytes": 0, "geminiResponseBytes": 0, "geminiGrossCostUsd": 0.0,
                    "geminiCacheSavingsUsd": 0.0, "geminiCostUsd": 0.0, "estimatedCostUsd": 0.0,
                    "inputTokens": 0, "outputTokens": 0, "cachedTokens": 0, "totalTokens": 0})
        self.ns["_process_gemini_api_payload_bytes"](mon, "p", "t", "s", "e", True, {}, res)
        self.assertEqual(res["inputTokens"], 111)
        self.assertEqual(res["outputTokens"], 7)


if __name__ == "__main__":
    unittest.main()
