"""Gemini API: neutral payload-bytes fallback and free-tier handling (invented data, no network)."""

import unittest

import server

FREE_PFX = "generativelanguage.googleapis.com/quota/generate_content_free_tier"
DAY = "2026-10-01"
RATES = {"input": 0.30, "output": 2.50, "cache_read_input": 0.03, "cacheHitRatioPct": 0.0, "source": "TEST"}


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


def tok_series(model: str, value: int, day: str = DAY) -> dict:
    return {
        "metric": {"labels": {"model": model}},
        "points": [{"interval": {"endTime": f"{day}T12:00:00Z"}, "value": {"int64Value": str(value)}}],
    }


def bytes_series(method: str, count: int, mean: float, day: str = DAY) -> dict:
    return {
        "resource": {"labels": {"credential_id": "cred-test", "method": method, "location": "global"}},
        "points": [{
            "interval": {"endTime": f"{day}T12:00:00Z"},
            "value": {"distributionValue": {"count": str(count), "mean": mean}},
        }],
    }


class GeminiBase(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = load_app_namespace()
        self.ns["get_gemini_api_rates"] = lambda m: dict(RATES)
        self.ns["_gemini_api_credit_discount_ratio"] = lambda: 0.0

    def _result(self) -> dict:
        res = self.ns["_init_project_inspection_dict"]({"projectId": "p-test", "name": "p-test"}, {})
        res["geminiApiRequests"] = 1
        return res

    def _process(self, mon_results: dict, calls_map=None) -> dict:
        res = self._result()
        mon = {"gemini_req_b": [], "gemini_resp_b": []}
        mon.update(mon_results)
        self.ns["_process_gemini_api_payload_bytes"](mon, "p-test", "t", "s", "e", True, calls_map or {}, res)
        return res


class TestPayloadFallback(GeminiBase):
    def test_generate_content_neutral_estimate(self) -> None:
        res = self._process({"gemini_req_b": [bytes_series("g.GenerateContent", 2, 2000.0)],
                             "gemini_resp_b": [bytes_series("g.GenerateContent", 2, 4000.0)]})
        self.assertEqual(res["inputTokens"], 1000)    # 4000 B / 4
        self.assertEqual(res["outputTokens"], 2000)   # 8000 B / 4
        self.assertEqual(res["cachedTokens"], 0)
        expected = (1000 * RATES["input"] + 2000 * RATES["output"]) / 1_000_000.0
        self.assertAlmostEqual(res["geminiGrossCostUsd"], expected, places=9)
        self.assertEqual(res["credentialsUsage"]["cred-test"]["costSource"], "GEMINI_API_PAYLOAD_BYTES")

    def test_stream_uses_same_rule(self) -> None:
        res = self._process({"gemini_req_b": [bytes_series("g.StreamGenerateContent", 1, 400.0)],
                             "gemini_resp_b": [bytes_series("g.StreamGenerateContent", 1, 800.0)]})
        self.assertEqual((res["inputTokens"], res["outputTokens"]), (100, 200))
        expected = (100 * RATES["input"] + 200 * RATES["output"]) / 1_000_000.0
        self.assertAlmostEqual(res["geminiGrossCostUsd"], expected, places=9)

    def test_stream_without_response_bytes_uses_per_call_constant(self) -> None:
        res = self._process({"gemini_req_b": [bytes_series("g.StreamGenerateContent", 3, 400.0)]})
        per_call = self.ns["GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL"]
        self.assertEqual(res["outputTokens"], 3 * per_call)
        self.assertEqual(res["inputTokens"], 300)

    def test_calls_only_keeps_estimate_label(self) -> None:
        res = self._process({}, calls_map={("cred-test", "GenerateContent", "global", DAY): 5})
        self.assertEqual(res["credentialsUsage"]["cred-test"]["costSource"], "AI_STUDIO_ESTIMATE")
        self.assertEqual(res["inputTokens"], 5 * self.ns["GEMINI_API_EST_INPUT_TOKENS_PER_CALL"])


class TestFreeTier(GeminiBase):
    def test_free_only_costs_zero_but_keeps_tokens(self) -> None:
        res = self._process({"gemini_free_in_tok_0": [tok_series("gemini-2.5-flash", 1000)],
                             "gemini_out_tok": [tok_series("gemini-2.5-flash", 500)]})
        self.assertEqual((res["inputTokens"], res["outputTokens"]), (1000, 500))
        self.assertEqual(res["geminiGrossCostUsd"], 0.0)
        self.assertEqual(res["geminiCostUsd"], 0.0)
        cu = res["credentialsUsage"]
        self.assertEqual(len(cu), 1)
        c = next(iter(cu.values()))
        self.assertEqual(c["costSource"], "GEMINI_API_FREE_TIER")
        self.assertTrue(c["freeTier"])
        self.assertTrue(res["geminiFreeTierDetected"])
        self.assertFalse(any(k.startswith("_gemini") for k in res))

    def test_paid_only_unchanged(self) -> None:
        res = self._process({"gemini_in_tok": [tok_series("gemini-2.5-flash", 1000)],
                             "gemini_out_tok": [tok_series("gemini-2.5-flash", 500)]})
        expected = (1000 * RATES["input"] + 500 * RATES["output"]) / 1_000_000.0
        self.assertAlmostEqual(res["geminiGrossCostUsd"], expected, places=9)
        c = next(iter(res["credentialsUsage"].values()))
        self.assertEqual(c["costSource"], "GEMINI_API_TOKEN_METRICS")
        self.assertNotIn("freeTier", c)
        self.assertFalse(res["geminiFreeTierDetected"])

    def test_mixed_per_model(self) -> None:
        res = self._process({
            "gemini_in_tok": [tok_series("gemini-2.5-pro", 1000)],
            "gemini_free_in_tok_0": [tok_series("gemini-2.5-flash", 2000), tok_series("gemini-2.5-pro", 700)],
            "gemini_out_tok": [tok_series("gemini-2.5-pro", 100), tok_series("gemini-2.5-flash", 300)],
        })
        # flash: free only -> 0 cost; pro: paid input present -> priced, free input ignored (no regression)
        expected = (1000 * RATES["input"] + 100 * RATES["output"]) / 1_000_000.0
        self.assertAlmostEqual(res["geminiGrossCostUsd"], expected, places=9)
        self.assertEqual(res["inputTokens"], 3000)
        flash = next(v for k, v in res["models"].items() if "flash" in k)
        self.assertTrue(flash["freeTier"])
        pro = next(v for k, v in res["models"].items() if "pro" in k)
        self.assertNotIn("freeTier", pro)


class TestFreeTierDiscovery(GeminiBase):
    def _discover(self, status, descriptors):
        def fake_get(url, token, timeout=12, user_project=None):
            if status == "raise":
                raise RuntimeError("boom")
            return status, {"metricDescriptors": descriptors}
        self.ns["gcp_api_get"] = fake_get
        return self.ns["_discover_gemini_free_tier_metric_types"]("p", "t")

    def test_found_only_matching_types(self) -> None:
        good = f"{FREE_PFX}_input_token_count/usage"
        out = self._discover(200, [
            {"type": good},
            {"type": f"{FREE_PFX}_output_token_count/usage"},
            {"type": "other/metric"},
            {},
        ])
        self.assertEqual(out, [good])

    def test_failure_or_empty_gives_nothing(self) -> None:
        for st, d in ((429, []), (500, [{"type": f"{FREE_PFX}_input_token_count/usage"}]), (200, []), ("raise", [])):
            self.assertEqual(self._discover(st, d), [], st)

    def test_prefetch_adds_specs_and_flag(self) -> None:
        good = f"{FREE_PFX}_input_token_count/usage"
        self.ns["_discover_gemini_tier_suffixes"] = lambda pid, token, result: [""]
        for found, expect in (([good], True), ([], False)):
            self.ns["_discover_gemini_free_tier_metric_types"] = lambda pid, token, f=found: f
            captured = {}
            self.ns["fetch_monitoring_timeseries"] = lambda *a, **k: []
            res = self._result()
            res["geminiApiEnabled"] = True
            self.ns["_prefetch_project_monitoring_metrics"](
                "p", "t", "s", "e", True, 200, set(), set(), res)
            captured.update(res)
            self.assertEqual(captured["geminiFreeTierDetected"], expect)
            self.assertFalse(any(k.startswith("_gemini") for k in captured))


if __name__ == "__main__":
    unittest.main()
