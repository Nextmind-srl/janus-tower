"""A5 - qualita' dell'attribuzione token Gemini API per credenziale (dati inventati, nessuna rete)."""

import os
import unittest

import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = "2026-10-01"
METHOD = "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent"


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


def dist_series(cred: str, count: int, mean: float) -> dict:
    return {
        "resource": {"labels": {"credential_id": cred, "method": METHOD, "location": "global"}},
        "points": [{"interval": {"endTime": f"{DAY}T10:00:00Z"}, "value": {"distributionValue": {"count": count, "mean": mean}}}],
    }


def tok_series(model: str, value: int) -> dict:
    return {
        "metric": {"labels": {"model": model}},
        "points": [{"interval": {"endTime": f"{DAY}T10:00:00Z"}, "value": {"int64Value": str(value)}}],
    }


class TestA5Quality(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = load_app_namespace()

    def _result(self) -> dict:
        r = self.ns["empty_day_bucket"]()
        r.update({
            "geminiApiRequests": 10, "credentialsUsage": {}, "dailySeries": {}, "models": {},
            "geminiRequestBytes": 0, "geminiResponseBytes": 0, "geminiGrossCostUsd": 0.0,
            "geminiCacheSavingsUsd": 0.0, "geminiCostUsd": 0.0, "estimatedCostUsd": 0.0,
            "inputTokens": 0, "outputTokens": 0, "cachedTokens": 0, "totalTokens": 0,
        })
        return r

    def _run(self, req_series, resp_series, in_tok=None, out_tok=None, calls=None) -> dict:
        mon = {"gemini_req_b": req_series, "gemini_resp_b": resp_series}
        if in_tok is not None:
            mon["gemini_in_tok"] = [tok_series("gemini-2.5-flash", in_tok)]
        if out_tok is not None:
            mon["gemini_out_tok"] = [tok_series("gemini-2.5-flash", out_tok)]
        res = self._result()
        self.ns["_process_gemini_api_payload_bytes"](mon, "p", "t", "s", "e", True, calls or {}, res)
        return res

    def test_full_bytes_weight_by_bytes(self) -> None:
        # A: 100 byte, B: 300 byte; call opposte (A molte, B poche): conta solo il peso in byte
        calls = {("A", "GenerateContent", "global", DAY): 90, ("B", "GenerateContent", "global", DAY): 10}
        res = self._run([dist_series("A", 1, 100), dist_series("B", 1, 300)], [], in_tok=1000, out_tok=400, calls=calls)
        self.assertEqual(res["credentialsUsage"]["A"]["inputTokens"], 250)
        self.assertEqual(res["credentialsUsage"]["B"]["inputTokens"], 750)
        self.assertNotIn("tokensEstimatedFromBytes", res["credentialsUsage"]["A"])

    def test_partial_bytes_fall_back_to_calls_for_all(self) -> None:
        # A ha byte, B no: niente unita' miste, chiamate per tutte (A 30, B 10 -> 75% / 25%)
        calls = {("A", "GenerateContent", "global", DAY): 30, ("B", "GenerateContent", "global", DAY): 10}
        res = self._run([dist_series("A", 1, 100)], [], in_tok=1000, out_tok=0, calls=calls)
        self.assertEqual(res["credentialsUsage"]["A"]["inputTokens"], 750)
        self.assertEqual(res["credentialsUsage"]["B"]["inputTokens"], 250)

    def test_unattributed_has_readable_name_and_keeps_id(self) -> None:
        res = self._run([], [], in_tok=500, out_tok=100)
        cred = res["credentialsUsage"]["gemini-api:unattributed"]
        self.assertEqual(cred["credentialId"], "gemini-api:unattributed")
        self.assertIn("not attributable", cred["resolvedName"])
        self.assertNotIn("gemini-api:", cred["resolvedName"])

    def test_bytes_estimate_flag(self) -> None:
        # Nessuna metrica token: ripiego sui byte -> indicatore su credenziale, giorno e modello
        res = self._run([dist_series("A", 2, 4000)], [dist_series("A", 2, 8000)])
        cred = res["credentialsUsage"]["A"]
        self.assertTrue(cred["tokensEstimatedFromBytes"])
        self.assertTrue(cred["dailySeries"][DAY]["tokensEstimatedFromBytes"])
        self.assertTrue(next(iter(res["models"].values()))["tokensEstimatedFromBytes"])

    def test_exact_metrics_not_flagged(self) -> None:
        res = self._run([dist_series("A", 1, 100)], [], in_tok=100, out_tok=50)
        self.assertNotIn("tokensEstimatedFromBytes", res["credentialsUsage"]["A"])
        for m in res["models"].values():
            self.assertNotIn("tokensEstimatedFromBytes", m)


class TestA5Frontend(unittest.TestCase):
    def test_badge_present_in_assembled_html(self) -> None:
        html = server.assemble_frontend_html(ROOT, write_to_disk=False)
        self.assertIn("tokensEstimatedFromBytes", html)
        self.assertIn("estimated from bytes", html)


if __name__ == "__main__":
    unittest.main()


class TestEstimatedFlagFollowsWindow(unittest.TestCase):
    def test_flag_is_recomputed_from_remaining_days(self) -> None:
        ns = load_app_namespace()
        day = {"requests": 1, "inferenceRequests": 1, "tokens": 10, "inputTokens": 8, "outputTokens": 2, "costUsd": 1.0}
        payload = {
            "days": 30, "scannedAt": "2026-10-30T18:00:00Z",
            "projects": [{
                "projectId": "p", "name": "p", "billingEnabled": True, "aiActive": True, "scanDays": 30,
                "totalRequests": 2, "inferenceRequests": 2, "totalTokens": 20, "estimatedCostUsd": 2.0,
                "geminiCostUsd": 2.0, "vertexCostUsd": 0.0, "otherAiCostUsd": 0.0,
                "dailySeries": {"2026-10-05": dict(day), "2026-10-28": dict(day)},
                "models": [{"modelId": "m", "costUsd": 2.0, "tokensEstimatedFromBytes": True, "dailySeries": {
                    "2026-10-05": dict(day, tokensEstimatedFromBytes=True), "2026-10-28": dict(day)}}],
                "credentialsUsage": [{"credentialId": "apikey:k", "estimatedCostUsd": 2.0, "tokensEstimatedFromBytes": True,
                                      "dailySeries": {"2026-10-05": dict(day, tokensEstimatedFromBytes=True), "2026-10-28": dict(day)}}],
            }],
        }
        recent = ns["slice_cached_payload_for_days"](payload, 7, {"activeAccount": None})["projects"][0]
        self.assertNotIn("tokensEstimatedFromBytes", recent["models"][0])
        self.assertNotIn("tokensEstimatedFromBytes", recent["credentialsUsage"][0])
        full = ns["slice_cached_payload_for_days"](payload, 30, {"activeAccount": None})["projects"][0]
        self.assertTrue(full["models"][0]["tokensEstimatedFromBytes"])
        self.assertTrue(full["credentialsUsage"][0]["tokensEstimatedFromBytes"])
