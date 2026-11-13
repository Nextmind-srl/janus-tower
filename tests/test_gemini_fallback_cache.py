"""Gemini API fallbacks (payload bytes, per-call estimate) apply the implicit cache share and the credit
discount exactly like the token-metric path (invented data, no network)."""

import unittest

from test_gemini_api_fallback import DAY, GeminiBase, bytes_series, tok_series

RATES_CACHE = {"input": 0.30, "output": 2.50, "cache_read_input": 0.03, "cacheHitRatioPct": 40.0, "source": "TEST"}


def expected(in_tok: int, out_tok: int, rates: dict) -> tuple[int, float]:
    cached = int(round(in_tok * rates["cacheHitRatioPct"] / 100.0))
    gross = ((in_tok - cached) * rates["input"] + cached * rates["cache_read_input"] + out_tok * rates["output"]) / 1_000_000.0
    return cached, gross


class TestFallbackCacheShare(GeminiBase):
    def setUp(self) -> None:
        super().setUp()
        self.ns["get_gemini_api_rates"] = lambda m: dict(RATES_CACHE)

    def test_payload_bytes_apply_the_cache_share(self) -> None:
        res = self._process({"gemini_req_b": [bytes_series("g.GenerateContent", 2, 2000.0)],
                             "gemini_resp_b": [bytes_series("g.GenerateContent", 2, 4000.0)]})
        cached, gross = expected(1000, 2000, RATES_CACHE)
        self.assertEqual(res["cachedTokens"], cached)
        self.assertGreater(cached, 0)
        self.assertAlmostEqual(res["geminiGrossCostUsd"], gross, places=9)
        self.assertEqual(res["credentialsUsage"]["cred-test"]["costSource"], "GEMINI_API_PAYLOAD_BYTES")

    def test_per_call_estimate_applies_the_cache_share(self) -> None:
        res = self._process({}, calls_map={("cred-test", "GenerateContent", "global", DAY): 5})
        in_tok = 5 * self.ns["GEMINI_API_EST_INPUT_TOKENS_PER_CALL"]
        out_tok = 5 * self.ns["GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL"]
        cached, gross = expected(in_tok, out_tok, RATES_CACHE)
        self.assertEqual(res["cachedTokens"], cached)
        self.assertAlmostEqual(res["geminiGrossCostUsd"], gross, places=9)
        self.assertEqual(res["credentialsUsage"]["cred-test"]["costSource"], "AI_STUDIO_ESTIMATE")

    def test_same_formula_as_the_token_metric_path(self) -> None:
        by_tokens = self._process({"gemini_in_tok": [tok_series("gemini-2.5-flash", 1000)],
                                   "gemini_out_tok": [tok_series("gemini-2.5-flash", 2000)]},
                                  calls_map={("cred-test", "GenerateContent", "global", DAY): 2})
        by_bytes = self._process({"gemini_req_b": [bytes_series("g.GenerateContent", 2, 2000.0)],
                                  "gemini_resp_b": [bytes_series("g.GenerateContent", 2, 4000.0)]})
        self.assertEqual(by_tokens["cachedTokens"], by_bytes["cachedTokens"])
        self.assertAlmostEqual(by_tokens["geminiGrossCostUsd"], by_bytes["geminiGrossCostUsd"], places=9)

    def test_credit_discount_applies_to_the_per_call_estimate(self) -> None:
        self.ns["_gemini_api_credit_discount_ratio"] = lambda: 0.5
        res = self._process({}, calls_map={("cred-test", "GenerateContent", "global", DAY): 4})
        self.assertAlmostEqual(res["geminiCacheSavingsUsd"], res["geminiGrossCostUsd"] * 0.5, places=9)
        self.assertAlmostEqual(res["geminiCostUsd"], res["geminiGrossCostUsd"] * 0.5, places=9)


if __name__ == "__main__":
    unittest.main()
