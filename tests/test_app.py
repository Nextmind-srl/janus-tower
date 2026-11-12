"""Behavioural tests: frontend assembly, OAuth fail-closed, auth gates, .env loader and local data purge.

Run from the repository root:  python -m unittest discover -s tests -v
"""

import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_app_namespace() -> dict:
    """Loads a fresh, isolated copy of the backend (same mechanism as server.py)."""
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


class TestFrontendAssembly(unittest.TestCase):
    def test_index_html_matches_sources(self) -> None:
        assembled = server.assemble_frontend_html(ROOT, write_to_disk=False)
        with open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), assembled, "index.html is stale: regenerate it from frontend/ (see README)")

    def test_no_svg_markup_assigned_as_plain_text(self) -> None:
        import re
        bad = re.compile(r"\.(textContent|innerText)\s*=\s*[^;\n]*<svg")
        for js in sorted(Path(ROOT, "frontend", "js").glob("*.js")):
            for n, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
                self.assertIsNone(bad.search(line), f"{js.name}:{n} puts SVG markup in a text node (use setSafeHtml)")

    def test_html_rendering_is_sanitized(self) -> None:
        html = server.assemble_frontend_html(ROOT, write_to_disk=False)
        self.assertIn("function jsArg(", html)
        self.assertIn("function sanitizeFragment(", html)
        self.assertNotIn("createContextualFragment", html)


class TestNoEmbeddedOAuthClient(unittest.TestCase):
    def test_config_has_no_builtin_client(self) -> None:
        with open(os.path.join(ROOT, "backend", "config.py"), "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("apps.googleusercontent.com", src)
        self.assertNotIn("b64decode", src)

    def test_no_google_first_party_scope(self) -> None:
        ns = load_app_namespace()
        self.assertNotIn("https://www.googleapis.com/auth/accounts.reauth", ns["OAUTH_SCOPES"])


class TestHttpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = load_app_namespace()
        cls.ns["OAUTH_CONFIGURED"] = False  # independent of any local .env
        cls.ns["MonitorHandler"].log_message = lambda *args, **kwargs: None
        cls.srv = cls.ns["ThreadingHTTPServer"](("127.0.0.1", 0), cls.ns["MonitorHandler"])
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, method: str, path: str, body: str = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            return resp.status, dict(resp.getheaders())
        finally:
            conn.close()

    def test_oauth_start_fails_closed_without_client(self) -> None:
        status, headers = self.request("GET", "/auth/google/start")
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith("/?auth_error="))
        self.assertNotIn("accounts.google.com", headers["Location"])

    def test_oauth_callback_fails_closed_without_client(self) -> None:
        status, headers = self.request("GET", "/oauth2callback?code=abc&state=xyz")
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith("/?auth_error="))

    def test_api_requires_session(self) -> None:
        for path in ("/api/scan?days=7&cached=1", "/api/scan/progress", "/api/projects-sync", "/api/budgets", "/api/models-pricing"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 401)
        for path in (
            "/api/data/purge",
            "/api/projects-sync/toggle",
            "/api/budgets",
            "/api/projects-sync/force-scan",
            "/api/models-pricing/sync",
            "/api/models-pricing/config",
        ):
            with self.subTest(path=path):
                body = '{"projectId": "p"}' if path.endswith("force-scan") else "{}"
                self.assertEqual(self.request("POST", path, body)[0], 401)

    def test_only_index_is_served(self) -> None:
        self.assertEqual(self.request("GET", "/")[0], 200)
        for logo_path in ("/Design/logos/janustower-mark-on-dark.svg", "/Design/logos/favicon.svg", "/Design/logos/janustower-app-icon.svg"):
            with self.subTest(logo_path=logo_path):
                status, headers = self.request("GET", logo_path)
                self.assertEqual(status, 200)
                self.assertIn("image/svg+xml", headers.get("Content-Type", ""))
        for path in ("/server.py", "/backend/config.py", "/data/oauth_tokens.json", "/.env", "/../server.py", "/Design/header.html", "/Design/logos/../header.html"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)


class TestSessionAfterLogin(unittest.TestCase):
    """After the OAuth callback the session lives only in the HttpOnly cookie (no sid in the URL)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ns = load_app_namespace()
        cls.ns["DATA_DIR"] = cls.tmp.name
        cls.ns["TOKENS_FILE"] = os.path.join(cls.tmp.name, "oauth_tokens.json")
        cls.ns["MonitorHandler"].log_message = lambda *args, **kwargs: None
        now = cls.ns["time"].time()
        cls.ns["save_tokens_store"]({"accounts": {"a@x.com": {
            "email": "a@x.com", "access_token": "fake", "refresh_token": None, "expires_at": now + 3000,
            "login_date": cls.ns["get_today_date_str"](), "daily_expires_at": now + 3000,
            "session_id": "SID_NEW", "needs_reauth": False}}})
        cls.srv = cls.ns["ThreadingHTTPServer"](("127.0.0.1", 0), cls.ns["MonitorHandler"])
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cookie = f"{cls.ns['COOKIE_NAME']}=a%40x.com; {cls.ns['SESSION_COOKIE_NAME']}=SID_NEW"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def status(self, headers: dict) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/api/auth/status", headers=headers)
            return json.loads(conn.getresponse().read())["auth"]
        finally:
            conn.close()

    def test_cookie_alone_authenticates(self) -> None:
        auth = self.status({"Cookie": self.cookie})
        self.assertTrue(auth["tokenValid"])
        self.assertEqual(auth["activeAccount"], "a@x.com")

    def test_stale_header_session_is_rejected(self) -> None:
        # Why the frontend drops its stored sid on /?autostart=1: header values win over the cookie.
        auth = self.status({"Cookie": self.cookie, "X-GCP-Account": "a@x.com", "X-GCP-Session-Token": "SID_OLD"})
        self.assertFalse(auth["tokenValid"])


class TestDotEnvLoader(unittest.TestCase):
    KEYS = ("JT_TEST_PLAIN", "JT_TEST_QUOTED", "JT_TEST_EXPORT", "JT_TEST_PRESET")

    def tearDown(self) -> None:
        for k in self.KEYS:
            os.environ.pop(k, None)

    def test_reads_values_without_overriding_real_env(self) -> None:
        ns = load_app_namespace()
        os.environ["JT_TEST_PRESET"] = "from-env"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# comment\nJT_TEST_PLAIN=abc\nJT_TEST_QUOTED=\"a b=c\"\nexport JT_TEST_EXPORT=x\n"
                        "JT_TEST_PRESET=from-file\nnot a pair\n")
            ns["load_dotenv_file"](path)
        self.assertEqual(os.environ["JT_TEST_PLAIN"], "abc")
        self.assertEqual(os.environ["JT_TEST_QUOTED"], "a b=c")
        self.assertEqual(os.environ["JT_TEST_EXPORT"], "x")
        self.assertEqual(os.environ["JT_TEST_PRESET"], "from-env")


class TestPurgeAccountLocalData(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ns = load_app_namespace()
        self.ns["DATA_DIR"] = self.tmp.name
        self.ns["SYNC_REGISTRY_FILE"] = os.path.join(self.tmp.name, "projects_sync_registry.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_cache(self, name: str, owner: str) -> None:
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as f:
            json.dump({"auth": {"activeAccount": owner}, "projects": []}, f)

    def test_purges_only_the_active_account(self) -> None:
        self.write_cache("scan_cache_v9_mario_x_com_30d.json", "mario@x.com")
        self.write_cache("scan_cache_v9_mario_x_com_7d.json", "mario@x.com")
        self.write_cache("scan_cache_v9_mario_x_com_range_2026-10-01_2026-10-07d.json", "mario@x.com")
        self.write_cache("scan_cache_v9_mario_x_com_it_30d.json", "mario@x.com.it")  # similar name, other account
        self.write_cache("scan_cache_v9_mario_x_com_90d.json", "mario.x@com")      # same file prefix, other owner
        with open(os.path.join(self.tmp.name, "budgets_config.json"), "w", encoding="utf-8") as f:
            json.dump({"projects": {}}, f)
        self.ns["save_sync_registry"]({"accounts": {"mario@x.com": {"projects": {}}, "mario@x.com.it": {"projects": {}}}})

        res = self.ns["purge_account_local_data"]("mario@x.com")

        self.assertTrue(res["success"])
        self.assertEqual(res["deletedFiles"], 3)
        self.assertTrue(res["registryEntryRemoved"])
        self.assertEqual(res["skippedOtherAccountFiles"], 1)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), [
            "budgets_config.json",
            "projects_sync_registry.json",
            "scan_cache_v9_mario_x_com_90d.json",
            "scan_cache_v9_mario_x_com_it_30d.json",
        ])
        self.assertEqual(list(self.ns["load_sync_registry"]()["accounts"]), ["mario@x.com.it"])

    def test_refuses_while_this_account_is_scanning(self) -> None:
        self.write_cache("scan_cache_v9_mario_x_com_30d.json", "mario@x.com")
        self.ns["SCAN_PROGRESS"].update({"active": True, "account": "mario@x.com"})
        res = self.ns["purge_account_local_data"]("mario@x.com")
        self.assertFalse(res["success"])
        self.assertTrue(res["scanInProgress"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "scan_cache_v9_mario_x_com_30d.json")))


class FakeResponse:
    def __init__(self, status: int, body: dict = None, headers: dict = None) -> None:
        self.status = status
        self.data = json.dumps(body or {}).encode("utf-8")
        self.headers = headers or {}


class FakePool:
    """Stands in for urllib3.PoolManager: replays scripted responses, then repeats the last one."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls = 0

    def request(self, *args, **kwargs) -> FakeResponse:
        self.calls += 1
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class TestGoogleRateLimits(unittest.TestCase):
    """A 429 from Google means 'try again later', never 'permission denied' or 'no data'."""

    def setUp(self) -> None:
        self.ns = load_app_namespace()
        self.sleeps = []
        self.ns["GCP_RETRY_SLEEP"] = self.sleeps.append

    def use(self, *responses: FakeResponse) -> FakePool:
        pool = FakePool(responses)
        self.ns["HTTP_POOL"] = pool
        return pool

    def test_get_retries_429_and_honours_retry_after(self) -> None:
        pool = self.use(FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, {"ok": 1}))
        self.assertEqual(self.ns["gcp_api_get"]("https://x.googleapis.com/a", "t"), (200, {"ok": 1}))
        self.assertEqual(pool.calls, 2)
        self.assertEqual(self.sleeps, [3.0])

    def test_post_gives_up_after_max_attempts_with_capped_waits(self) -> None:
        pool = self.use(FakeResponse(429, headers={"Retry-After": "30"}))
        status, _ = self.ns["gcp_api_post"]("https://x.googleapis.com/a", "t", {})
        self.assertEqual(status, 429)
        self.assertEqual(pool.calls, self.ns["GCP_MAX_ATTEMPTS"])
        self.assertEqual(self.sleeps, [self.ns["GCP_MAX_RETRY_WAIT_S"]] * (self.ns["GCP_MAX_ATTEMPTS"] - 1))

    def test_iam_check_unknown_on_429_but_denied_on_403(self) -> None:
        self.use(FakeResponse(429))
        self.assertIsNone(self.ns["check_project_iam_permissions"]("p", "t"))
        self.use(FakeResponse(403, {"error": {"code": 403}}))
        self.assertEqual(self.ns["check_project_iam_permissions"]("p", "t"), set())
        self.use(FakeResponse(200, {"permissions": ["monitoring.timeSeries.list"]}))
        self.assertEqual(self.ns["check_project_iam_permissions"]("p", "t"), {"monitoring.timeSeries.list"})

    def test_billing_429_marks_project_not_verified_instead_of_no_billing(self) -> None:
        self.use(FakeResponse(429))
        result = {"billingEnabled": False}
        stop = self.ns["_check_billing_and_enabled_services"]({"name": "p"}, "p", "t", {}, result)[0]
        self.assertTrue(stop)
        self.assertEqual(result["scanStatus"], "ERROR")
        self.assertEqual(result["transientError"], "RATE_LIMITED")
        self.assertFalse(result["skippedNoBilling"])
        # the UI iterates these: they must be lists, as in the other early exits
        self.assertEqual(result["models"], [])
        self.assertEqual(result["credentialsUsage"], [])

    def route_service_list(self, su_status: int) -> None:
        """billing OK, IAM answers (no permissions), enabled-services list returns su_status."""
        def route(method, url, **kwargs):
            if "billingInfo" in url:
                return FakeResponse(200, {"billingEnabled": True, "billingAccountName": "billingAccounts/x"})
            if "serviceusage" in url:
                return FakeResponse(su_status)
            if "testIamPermissions" in url:
                return FakeResponse(200, {"permissions": []})
            return FakeResponse(200, {})
        self.ns["HTTP_POOL"] = type("RoutedPool", (), {"request": staticmethod(route)})()

    def test_service_list_429_is_not_verified_instead_of_ai_active(self) -> None:
        self.route_service_list(429)
        result = {"billingEnabled": False}
        stop = self.ns["_check_billing_and_enabled_services"]({"name": "p"}, "p", "t", {}, result)[0]
        self.assertTrue(stop)
        self.assertEqual(result["scanStatus"], "ERROR")
        self.assertEqual(result["transientError"], "RATE_LIMITED")
        self.assertEqual(result["transientErrorStep"], "serviceusage")
        self.assertNotEqual(result.get("aiActive"), True)

    def test_service_list_real_403_keeps_previous_behaviour(self) -> None:
        self.route_service_list(403)
        result = {"billingEnabled": False}
        stop = self.ns["_check_billing_and_enabled_services"]({"name": "p"}, "p", "t", {}, result)[0]
        self.assertFalse(stop)
        self.assertEqual(result["scanStatus"], "NO_PERMISSIONS_403")
        self.assertNotIn("transientError", result)

    def test_full_inspection_with_persistent_429_returns_ui_safe_shape(self) -> None:
        self.use(FakeResponse(429))
        res = self.ns["inspect_single_project"]({"projectId": "p", "name": "p"}, "t", 30, {}, {}, None, None, None)
        self.assertEqual(res["scanStatus"], "ERROR")
        self.assertIsInstance(res["models"], list)
        self.assertIsInstance(res["credentialsUsage"], list)

    def test_registry_never_auto_excludes_on_rate_limit(self) -> None:
        update = self.ns["update_registry_entry_from_project"]
        limited = {"projectId": "p", "scanStatus": "ERROR", "transientError": "RATE_LIMITED"}
        # new project: included and re-checked next time
        self.assertTrue(update({}, dict(limited), "2026-11-02T00:00:00Z")["scanEnabled"])
        # known project with data: stays included
        reg = {"p": {"projectId": "p", "hasAiData": True, "scanEnabled": True, "scanRule": "AUTO_INCLUDE_HAS_DATA"}}
        self.assertTrue(update(reg, dict(limited), "2026-11-02T00:00:00Z")["scanEnabled"])
        # a real 403 without data is still excluded as before
        denied = {"projectId": "q", "scanStatus": "NO_PERMISSIONS_403", "aiActive": False}
        self.assertFalse(update({}, denied, "2026-11-02T00:00:00Z")["scanEnabled"])

    def test_support_only_api_project_is_skipped_and_excluded_from_smart_scan(self) -> None:
        def route(method, url, **kwargs):
            if "billingInfo" in url:
                return FakeResponse(200, {"billingEnabled": True, "billingAccountName": "billingAccounts/x"})
            if "serviceusage" in url:
                return FakeResponse(200, {
                    "services": [{"config": {"name": "iap.googleapis.com", "title": "Cloud IAP API"}}]
                })
            if "testIamPermissions" in url:
                return FakeResponse(200, {"permissions": ["monitoring.timeSeries.list"]})
            return FakeResponse(200, {})

        self.ns["HTTP_POOL"] = type("RoutedPool", (), {"request": staticmethod(route)})()
        result = {"billingEnabled": False, "enabledAiApis": []}
        stop = self.ns["_check_billing_and_enabled_services"]({"name": "p"}, "p", "t", {}, result)[0]
        self.assertTrue(stop)
        self.assertEqual(result["scanStatus"], "SKIPPED_NO_AI_API")
        self.assertFalse(result["aiActive"])
        self.assertEqual(result["enabledAiApis"], [])
        result["projectId"] = "p"
        self.assertFalse(self.ns["project_has_ai_data"](result))
        entry = self.ns["update_registry_entry_from_project"]({}, result, "2026-11-02T00:00:00Z")
        self.assertFalse(entry["hasAiData"])
        self.assertFalse(entry["scanEnabled"])
        self.assertEqual(entry["scanRule"], "AUTO_EXCLUDE_NO_DATA")

    def test_billing_and_service_429_reuses_verified_prev_proj_metadata(self) -> None:
        self.use(FakeResponse(429))
        prev_proj = {
            "projectId": "p",
            "name": "p",
            "billingEnabled": True,
            "skippedNoBilling": False,
            "billingAccountName": "billingAccounts/x",
            "aiActive": True,
            "scanStatus": "SCANNED",
            "enabledAiApis": [{"service": "aiplatform.googleapis.com", "title": "Vertex AI API"}],
            "permissions": {
                "grantedIamPermissions": ["monitoring.timeSeries.list", "aiplatform.endpoints.list"]
            }
        }
        result = {"billingEnabled": False, "enabledAiApis": []}
        stop, b_status, _, su_status, granted, enabled_services_set, _ = self.ns["_check_billing_and_enabled_services"](
            {"name": "p"}, "p", "t", {}, result, prev_proj=prev_proj
        )
        self.assertFalse(stop)
        self.assertEqual(b_status, 200)
        self.assertEqual(su_status, 200)
        self.assertTrue(result["billingEnabled"])
        self.assertTrue(result["aiActive"])
        self.assertEqual(len(result["enabledAiApis"]), 1)
        self.assertIn("monitoring.timeSeries.list", granted)
        self.assertIn("aiplatform.googleapis.com", enabled_services_set)

    def test_fetch_monitoring_timeseries_concatenates_three_pages(self) -> None:
        calls = []

        def fake_get(url, token, timeout=12, user_project=None):
            calls.append((url, timeout, user_project))
            if "pageToken=p2" in url:
                return 200, {"timeSeries": [{"id": "s2"}], "nextPageToken": "p3"}
            if "pageToken=p3" in url:
                return 200, {"timeSeries": [{"id": "s3"}]}
            return 200, {"timeSeries": [{"id": "s1"}], "nextPageToken": "p2"}

        self.ns["gcp_api_get"] = fake_get
        series = self.ns["fetch_monitoring_timeseries"](
            "demo-project", "tok", 'metric.type="m"', "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"
        )
        self.assertEqual([s["id"] for s in series], ["s1", "s2", "s3"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(t == 22 for _, t, _ in calls))

    def test_fetch_monitoring_timeseries_stops_cleanly_on_second_page_error(self) -> None:
        def fake_get(url, token, timeout=12, user_project=None):
            if "pageToken=p2" in url:
                return 500, {"error": "backend failure"}
            return 200, {"timeSeries": [{"id": "s1"}], "nextPageToken": "p2"}

        self.ns["gcp_api_get"] = fake_get
        series = self.ns["fetch_monitoring_timeseries"](
            "demo-project", "tok", 'metric.type="m"', "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"
        )
        self.assertEqual([s["id"] for s in series], ["s1"])

    def test_get_model_rates_matches_longest_key_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            rates = self.ns["get_model_rates"]("gemini-2.5-flash-lite", "global")
            self.assertAlmostEqual(rates["input"], 0.10, places=4)
            self.assertFalse(rates["isEstimated"])

    def _parse(self, desc: str, ids: list[str], usd_nanos: int = 1000, regions=None):
        sku = {"skuId": "S", "description": desc, "serviceRegions": regions or ["global"],
               "pricingInfo": [{"pricingExpression": {"usageUnit": "count", "usageUnitDescription": "count",
                                "tieredRates": [{"startUsageAmount": 0, "unitPrice": {"units": "0", "nanos": usd_nanos}}]}}]}
        id_map = {m: self.ns["_catalog_id_tokens"](m) for m in ids}
        return self.ns["parse_catalog_sku"](sku, id_map)

    def test_sku_reader_skips_long_context_8b_and_per_character_skus(self) -> None:
        ids = ["gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"]
        for desc in (
            "Gemini 2.5 Pro Text Input (Long) - Predictions",
            "Gemini 2.5 Pro Text Output (Long) - Predictions",
            "Generate content output token count Gemini 2.5 Pro long output text",
            "GenerateContent input token count for Gemini 1.5 Flash 8B when input is up to 128k tokens",
            "GenerateContent input token count for Gemini 1.5 Flash when input is longer than 128k tokens",
            "Gemini 1.5 Flash Text Input - Predictions",
            "Number of tokens of cached content for Gemini 1.5 Flash over a period of time expressed in token hours",
            "Gemini 2.5 Pro Text Input Batch Predictions",
            "Gemini 2.5 Pro Text Input Priority Predictions",
        ):
            self.assertIsNone(self._parse(desc, ids), desc)
        ok = self._parse("Gemini 2.5 Pro Text Input - Predictions", ids)
        self.assertEqual((ok["model"], ok["field"], ok["modality"]), ("gemini-2.5-pro", "input", "text"))
        ok15 = self._parse("GenerateContent input token count for Gemini 1.5 Flash when input is up to 128k tokens", ids)
        self.assertEqual((ok15["model"], ok15["field"]), ("gemini-1.5-flash", "input"))
        # 1.5 SKUs without the word "token" are per-character: skipped on purpose
        self.assertIsNone(self._parse("Gemini 1.5 Pro Text Input - Predictions", ids))
        self.assertIsNotNone(self._parse("GenerateContent input token count for Gemini 1.5 Pro when input is up to 128k tokens", ids))

    def test_sku_reader_assigns_to_the_most_specific_model(self) -> None:
        ids = ["gemini-9-test", "gemini-9-test-lite", "gemini-9-test-image"]
        self.assertEqual(self._parse("Gemini 9 Test Lite Global Text Input - Predictions", ids)["model"], "gemini-9-test-lite")
        self.assertEqual(self._parse("Gemini 9 Test Image Global Image Output - Predictions", ids)["model"], "gemini-9-test-image")
        self.assertEqual(self._parse("Gemini 9 Test Global Text Input - Predictions", ids)["model"], "gemini-9-test")
        # an unknown, more specific model name (Ultra) must not pollute the base model
        self.assertIsNone(self._parse("Gemini 9 Test Ultra Global Text Input - Predictions", ids))

    def test_sku_reader_modalities_thinking_scope_and_gemini_api_wording(self) -> None:
        ids = ["gemini-9-test"]
        p = self._parse("Gemini 9 Test Regional Audio Input - Online Predictions", ids)
        self.assertEqual((p["modality"], p["field"], p["scope"]), ("audio", "input", "regional"))
        self.assertEqual(self._parse("Gemini 9 Test Thinking Text Output - Predictions", ids)["field"], "thinking")
        self.assertEqual(self._parse("Gemini 9 Test Text Input Caching Online", ids)["field"], "cache_read_input")
        self.assertIsNone(self._parse("Gemini 9 Test Text Input Cache Write", ids))
        g = self._parse("Generate content cached input token count gemini 9 test text", ids)
        self.assertEqual((g["model"], g["field"], g["modality"]), ("gemini-9-test", "cache_read_input", "text"))
        self.assertEqual(self._parse("Generate content output token count gemini 9 test text", ids)["field"], "output")

    def test_sku_reader_variant_models_and_version_spellings(self) -> None:
        ids = ["gemini-2.5-flash", "claude-3-5-sonnet", "claude-opus-5-5"]
        # a variant model that is not in the list must not feed the base model's slots
        self.assertIsNone(self._parse("Gemini 2.5 Flash Image Text Input - Predictions", ids))
        self.assertIsNone(self._parse("Gemini 2.5 Flash Native Audio Text Output - Predictions", ids))
        self.assertIsNotNone(self._parse("Gemini 2.5 Flash Image Input - Predictions", ids))  # plain image-input SKU of the base model
        self.assertEqual(self._parse("Claude 3.5 Sonnet Input Tokens", ids)["model"], "claude-3-5-sonnet")
        self.assertEqual(self._parse("Claude Opus 5 5 \u2014 Input Tokens", ids)["model"], "claude-opus-5-5")
        self.assertEqual(self.ns["_catalog_id_tokens"]("claude-3-5-sonnet@20250929"), ["claude", "3.5", "sonnet"])

    def test_sku_reader_skips_live_api_and_reads_partner_regions(self) -> None:
        ids = ["gemini-2.5-flash", "claude-opus-5-5"]
        self.assertIsNone(self._parse("BidiGenerateContent text input token count for Gemini 2.5 Flash 001", ids))
        self.assertIsNone(self._parse("Claude Opus 5 5 \u2014 Input Tokens \u2014 global \u2014 Context Window Size from 200001 to 1000000 Tokens", ids))
        g = self._parse("Claude Opus 5 5 \u2014 Input Tokens \u2014 global \u2014 Context Window Size from 0 to 200000 Tokens", ids)
        e = self._parse("Claude Opus 5 5 \u2014 Input Tokens \u2014 eu \u2014 Context Window Size from 0 to 200000 Tokens", ids)
        self.assertEqual((g["scope"], e["scope"]), ("global", "regional"))

    def test_catalog_conflict_takes_the_highest_price_and_flags_it(self) -> None:
        def mk(desc, nanos):
            return {"skuId": "S", "description": desc, "serviceRegions": ["global"],
                    "pricingInfo": [{"pricingExpression": {"usageUnit": "count", "usageUnitDescription": "count",
                                     "tieredRates": [{"startUsageAmount": 0, "unitPrice": {"units": "0", "nanos": nanos}}]}}]}
        cat = self.ns["build_catalog_rates"]([mk("Gemini 7 Plain Text Input - Predictions", 1000),
                                              mk("Gemini 7 Plain Text Input - Online Predictions", 3000)], [], ["gemini-7-plain"])
        self.assertEqual(cat["gemini-7-plain"]["vertex"]["text"]["input"], 3.0)
        self.assertEqual(cat["gemini-7-plain"]["ambiguous"], ["vertex.text.input"])

    def test_catalog_rates_aliases_pairs_per_unit_and_ambiguity(self) -> None:
        def mk(desc, nanos, regions=None):
            return {"skuId": "S-" + desc[:8], "description": desc, "serviceRegions": regions or ["global"],
                    "pricingInfo": [{"pricingExpression": {"usageUnit": "count", "usageUnitDescription": "count",
                                     "tieredRates": [{"startUsageAmount": 0, "unitPrice": {"units": "0", "nanos": nanos}}]}}]}
        v = [
            mk("Gemini 9 Test Global Text Input - Predictions", 4000),
            mk("Gemini 9 Test Regional Text Input - Predictions", 4400),
            mk("Gemini 9 Test Global Text Output - Predictions", 20000),
            mk("Gemini 9 Test Input Text Caching", 400),
            mk("Gemini 9 Test Global Image Input - Predictions", 8000),
            mk("Gemini 8.0 / 8.1 Pro Text Input - Predictions", 1000),
            mk("Imagen 9 Generation (output)", 40_000_000),
            mk("Gemini 7 Plain Text Input - Predictions", 1000),
            mk("Gemini 7 Plain Text Input - Online Predictions", 3000),
        ]
        g = [mk("Generate content input token count gemini 9 test text", 3000)]
        ids = ["gemini-9-test", "gemini-9-test-preview", "gemini-8.0-pro", "gemini-8.1-pro", "imagen-9", "gemini-7-plain", "gemini-none"]
        cat = self.ns["build_catalog_rates"](v, g, ids)
        t = cat["gemini-9-test"]
        self.assertEqual(t["vertex"]["text"], {"input": 4.0, "regional_input": 4.4, "output": 20.0, "cache_read_input": 0.4})
        self.assertEqual(t["vertex"]["image"], {"input": 8.0})
        self.assertEqual(t["geminiApi"]["text"], {"input": 3.0})
        self.assertEqual(cat["gemini-9-test-preview"], t)  # same name once -preview is dropped: same rates...
        self.assertIsNot(cat["gemini-9-test-preview"], t)  # ...but independent copies
        self.assertEqual(cat["gemini-8.0-pro"]["vertex"]["text"], {"input": 1.0})
        self.assertEqual(cat["gemini-8.1-pro"]["vertex"]["text"], {"input": 1.0})
        self.assertEqual(cat["imagen-9"]["perUnit"], [{"sku": "Imagen 9 Generation (output)", "usd": 0.04, "unit": "count"}])
        self.assertEqual(cat["gemini-7-plain"]["ambiguous"], ["vertex.text.input"])
        self.assertNotIn("gemini-none", cat)

    def test_manual_zero_rate_is_respected(self) -> None:
        rates = self.ns["_select_location_rates"](
            {"input": 1.0, "output": 2.0, "manualOverride": {"input": 0.0, "output": 0.0}}, "global"
        )
        self.assertEqual(rates["input"], 0.0)
        self.assertEqual(rates["output"], 0.0)
        self.assertEqual(rates["thinking"], 0.0)

    def _run_managed_point(self, savings_pct: float, hit_pct: float) -> dict:
        from collections import defaultdict
        ns = self.ns
        ns["estimate_service_call_cost"] = lambda service, method: (0.01, 1000, 500, "managed-model", "TEST")
        with tempfile.TemporaryDirectory() as tmp:
            ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            cfg = ns["load_models_pricing_config"]()
            cfg.setdefault("billingSettings", {}).update(
                {"managedServiceSavingsPct": savings_pct, "managedServiceCacheHitRatioPct": hit_pct}
            )
            ns["save_models_pricing_config"](cfg)
            ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            result = defaultdict(float, {"models": {}})
            c_entry = defaultdict(float, {"costSource": "NONE"})
            p_day, c_day = defaultdict(float), defaultdict(float)
            ns["_apply_managed_ai_service_point"](
                result, c_entry, p_day, c_day,
                "discoveryengine.googleapis.com", "Search", "global", "2026-11-01", 10,
            )
            return {"gross": c_entry["grossCostUsd"], "sav": c_entry["cacheSavingsUsd"],
                    "cost": c_entry["estimatedCostUsd"], "cached": c_entry["cachedTokens"]}

    def test_managed_service_uses_configured_savings(self) -> None:
        zero = self._run_managed_point(0.0, 0.0)
        self.assertAlmostEqual(zero["gross"], 0.10, places=6)
        self.assertEqual(zero["sav"], 0.0)
        self.assertEqual(zero["cached"], 0)
        half = self._run_managed_point(50.0, 40.0)
        self.assertAlmostEqual(half["sav"], 0.05, places=6)
        self.assertAlmostEqual(half["cost"], 0.05, places=6)
        self.assertEqual(half["cached"], int(round(10 * 1000 * 0.40)))

    def test_managed_service_full_savings_zeroes_cost_but_keeps_usage(self) -> None:
        full = self._run_managed_point(100.0, 0.0)
        self.assertAlmostEqual(full["gross"], 0.10, places=6)
        self.assertAlmostEqual(full["sav"], 0.10, places=6)
        self.assertAlmostEqual(full["cost"], 0.0, places=9)
        ok, err, cfg = self.ns["validate_and_apply_models_pricing_update"]({"billingSettings": {"managedServiceSavingsPct": 100}})
        self.assertTrue(ok, err)
        self.assertEqual(cfg["billingSettings"]["managedServiceSavingsPct"], 100.0)

    def test_managed_service_settings_validation_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            validate = self.ns["validate_and_apply_models_pricing_update"]
            for key, bad in (("managedServiceSavingsPct", 101), ("managedServiceSavingsPct", -1),
                             ("managedServiceCacheHitRatioPct", 99), ("managedServiceCacheHitRatioPct", "x")):
                ok, err, _ = validate({"billingSettings": {key: bad}})
                self.assertFalse(ok, f"{key}={bad} must be rejected")
                self.assertTrue(err)
            ok, err, cfg = validate({"billingSettings": {"managedServiceSavingsPct": 50, "managedServiceCacheHitRatioPct": 40}})
            self.assertTrue(ok, err)
            self.assertEqual(cfg["billingSettings"]["managedServiceSavingsPct"], 50.0)

    def _gemini_tmp_cfg(self, tmp: str, models: dict, bs: dict | None = None) -> None:
        self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
        self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
        cfg = self.ns["load_models_pricing_config"]()
        cfg["models"].update(models)
        cfg["billingSettings"].update(bs or {})
        self.ns["save_models_pricing_config"](cfg)
        self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}

    def test_gemini_api_rates_use_catalog_override_and_cache_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._gemini_tmp_cfg(tmp, {"zz-test-model": {
                "modelId": "zz-test-model", "input": 2.0, "output": 8.0, "thinking": 8.0, "cache_read_input": 0.2,
                "geminiApiRates": {"input": 1.0, "output": 4.0, "cache_read_input": 0.1},
                "geminiApiCacheHitRatioPct": 40.0,
            }}, {"geminiApiImplicitCacheHitRatioPct": 70.0})
            r = self.ns["get_gemini_api_rates"]("zz-test-model")
            self.assertEqual((r["input"], r["output"], r["cache_read_input"]), (1.0, 4.0, 0.1))
            self.assertEqual(r["cacheHitRatioPct"], 40.0)
            self.assertEqual(r["source"], "GEMINI_API_CATALOG")
            # a model without per-model ratio falls back to the global Gemini API setting and Vertex rates
            r2 = self.ns["get_gemini_api_rates"]("gemini-2.5-flash")
            self.assertEqual(r2["cacheHitRatioPct"], 70.0)
            self.assertEqual(r2["source"], "VERTEX_RATES")

    def test_gemini_api_cache_ratio_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._gemini_tmp_cfg(tmp, {})
            validate = self.ns["validate_and_apply_models_pricing_update"]
            for bad in (99, -1, "x", float("nan")):
                ok, err, _ = validate({"models": {"gemini-2.5-flash": {"geminiApiCacheHitRatioPct": bad}}})
                self.assertFalse(ok, f"{bad!r} must be rejected")
            ok, err, cfg = validate({"models": {"gemini-2.5-flash": {"geminiApiCacheHitRatioPct": 91}}})
            self.assertTrue(ok, err)
            self.assertEqual(cfg["models"]["gemini-2.5-flash"]["geminiApiCacheHitRatioPct"], 91.0)
            ok, err, cfg = validate({"models": {"gemini-2.5-flash": {"geminiApiCacheHitRatioPct": None}}})
            self.assertTrue(ok, err)
            self.assertNotIn("geminiApiCacheHitRatioPct", cfg["models"]["gemini-2.5-flash"])

    def _run_gemini_payload(self, with_token_metrics: bool) -> dict:
        from collections import defaultdict
        ns = self.ns
        day = "2026-10-10T12:00:00Z"
        iv = {"endTime": day}

        def dist(cnt, mean):
            return {"interval": iv, "value": {"distributionValue": {"count": cnt, "mean": mean}}}

        def ts_labels(**kw):
            return {"resource": {"labels": {"credential_id": "apikey:k1", "method": "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent", "location": "global"}}, **kw}

        mon = {
            "gemini_req_b": [ts_labels(points=[dist(10, 4000.0)])],
            "gemini_resp_b": [ts_labels(points=[dist(10, 1400.0)])],
        }
        if with_token_metrics:
            def int_pt(v):
                return {"interval": iv, "value": {"int64Value": str(v)}}
            mon["gemini_in_tok_3"] = [
                {"metric": {"labels": {"model": "model-a"}}, "points": [int_pt(1_000_000)]},
                {"metric": {"labels": {"model": "model-b"}}, "points": [int_pt(3_000_000)]},
            ]
            mon["gemini_out_tok"] = [
                {"metric": {"labels": {"model": "model-a"}}, "points": [int_pt(100_000)]},
                {"metric": {"labels": {"model": "model-b"}}, "points": [int_pt(200_000)]},
            ]
        result = defaultdict(float, {"credentialsUsage": {}, "dailySeries": {}, "models": {}})
        with tempfile.TemporaryDirectory() as tmp:
            self._gemini_tmp_cfg(tmp, {
                "model-a": {"modelId": "model-a", "input": 1.0, "output": 4.0, "thinking": 4.0, "cache_read_input": 0.1},
                "model-b": {"modelId": "model-b", "input": 2.0, "output": 8.0, "thinking": 8.0, "cache_read_input": 0.2,
                            "geminiApiCacheHitRatioPct": 50.0},
            }, {"geminiApiBillingCreditDiscountPct": 20.0})
            ns["_process_gemini_api_payload_bytes"](
                mon, "p", "t", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", True,
                {("apikey:k1", "GenerateContent", "global", "2026-10-10"): 10}, result,
            )
        return result

    def test_monitoring_queries_use_a_single_metric_type(self) -> None:
        # Cloud Monitoring rejects one_of(...)/OR over several metric.type values (returns no series)
        src = Path(ROOT, "backend", "project_inspector.py").read_text(encoding="utf-8")
        self.assertNotIn("metric.type=one_of(", src)
        self.assertNotIn("metric.type = one_of(", src)
        self.assertIn('gemini_in_tok{tier_sfx}', src)
        self.assertIn('GEMINI_BASE_TIER_SUFFIXES = ("", "_2", "_3")', src)

    def test_gemini_api_uses_exact_token_metrics_per_model(self) -> None:
        result = self._run_gemini_payload(with_token_metrics=True)
        self.assertEqual(set(result["models"]), {"model-a (Gemini API)", "model-b (Gemini API)"})
        a, b = result["models"]["model-a (Gemini API)"], result["models"]["model-b (Gemini API)"]
        self.assertEqual((a["inputTokens"], a["outputTokens"]), (1_000_000, 100_000))
        self.assertEqual((b["inputTokens"], b["outputTokens"]), (3_000_000, 200_000))
        # model-a: no cache -> 1M*1.0 + 0.1M*4.0 = 1.4 gross; model-b: 50% cached ->
        # 1.5M*2.0 + 1.5M*0.2 + 0.2M*8.0 = 4.9 gross; credit discount 20% on both
        self.assertAlmostEqual(a["grossCostUsd"], 1.4, places=6)
        self.assertAlmostEqual(b["grossCostUsd"], 4.9, places=6)
        self.assertAlmostEqual(result["geminiCostUsd"], (1.4 + 4.9) * 0.8, places=6)
        self.assertEqual(b["cachedTokens"], 1_500_000)
        self.assertEqual(result["credentialsUsage"]["apikey:k1"]["costSource"], "GEMINI_API_TOKEN_METRICS")

    def test_gemini_api_falls_back_to_payload_bytes_without_token_metrics(self) -> None:
        result = self._run_gemini_payload(with_token_metrics=False)
        self.assertEqual(list(result["models"]), ["gemini-2.5-flash / pro \u2014 GenerateContent (AI Studio API Key)"])
        self.assertEqual(result["credentialsUsage"]["apikey:k1"]["costSource"], "GEMINI_API_PAYLOAD_BYTES")
        self.assertGreater(result["geminiCostUsd"], 0.0)

    def test_usd_to_eur_rate_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._gemini_tmp_cfg(tmp, {})
            self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.92, places=6)
            validate = self.ns["validate_and_apply_models_pricing_update"]
            for bad in (0.49, 1.51, "abc", None, float("nan")):
                ok, _err, _ = validate({"billingSettings": {"usdToEurRate": bad}})
                self.assertFalse(ok, f"{bad!r} must be rejected")
            ok, err, _ = validate({"billingSettings": {"usdToEurRate": 0.88}})
            self.assertTrue(ok, err)
            self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.88, places=6)
            st = self.ns["get_auth_status_for_browser"](None, [], session_id=None)
            self.assertAlmostEqual(st["usdToEurRate"], 0.88, places=6)

    def test_cache_and_managed_settings_limits_and_ui_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._gemini_tmp_cfg(tmp, {})
            validate = self.ns["validate_and_apply_models_pricing_update"]
            for key, bad in (("geminiApiImplicitCacheHitRatioPct", 99), ("geminiApiImplicitCacheHitRatioPct", -1),
                             ("managedServiceSavingsPct", 101), ("managedServiceCacheHitRatioPct", 99)):
                ok, _err, _ = validate({"billingSettings": {key: bad}})
                self.assertFalse(ok, f"{key}={bad} must be rejected")
            ok, err, cfg = validate({"billingSettings": {
                "geminiApiImplicitCacheHitRatioPct": 86.5, "managedServiceSavingsPct": 10, "managedServiceCacheHitRatioPct": 20}})
            self.assertTrue(ok, err)
            self.assertEqual(cfg["billingSettings"]["geminiApiImplicitCacheHitRatioPct"], 86.5)
        view = Path(ROOT, "frontend", "js", "views_pricing.js").read_text(encoding="utf-8")
        for needle in ("pricing-cfg-gemini-cache", "pricing-cfg-managed-savings", "pricing-cfg-managed-cache",
                       "pricing-ov-gem-cache", "window.savePricingModelGeminiCache"):
            self.assertIn(needle, view)
        start = view.index("function openPricingModelDrawer(")
        end = view.index("function closePricingModelDrawer(")
        drawer = view[start:end]
        for decl in ("const gemCacheOwn", "const gemRates", "const gemCacheDefault"):
            self.assertIn(decl, drawer, f"{decl} must be declared inside openPricingModelDrawer")

    def test_pricing_view_handles_deleted_models_and_catalog_rates(self) -> None:
        view = Path(ROOT, "frontend", "js", "views_pricing.js").read_text(encoding="utf-8")
        html = Path(ROOT, "frontend", "html", "shell_and_views.html").read_text(encoding="utf-8")
        self.assertIn('id="pricing-filter-status"', html)
        for needle in ("_isModelDeleted(", "_renderPricingStatusBadges(", "_renderCatalogRatesSection(",
                       "'Deleted'", "'No catalog price'", "statusFilter === 'DELETED'", "deletedCount"):
            self.assertIn(needle, view)
        # KPI and sidebar count only active models
        kpi = view[view.index("function _computePricingKpiStats("):view.index("function _renderPricingKpiGrid(")]
        self.assertIn("if (_isModelDeleted(m)) return;", kpi)
        side = view[view.index("function _updatePricingSidebarBadge("):view.index("function _renderPricingLoadingSkeleton(")]
        self.assertIn("!_isModelDeleted(m)", side)

    def test_frontend_has_no_hardcoded_eur_rate(self) -> None:
        core = Path(ROOT, "frontend", "js", "core_and_auth.js").read_text(encoding="utf-8")
        self.assertNotIn("0.9192", core)
        self.assertIn("function setUsdToEurRate(", core)

    def test_gemini_api_discount_follows_billing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            ratio = self.ns["_gemini_api_credit_discount_ratio"]
            self.assertEqual(ratio(), 0.0)
            ok, err, _ = self.ns["validate_and_apply_models_pricing_update"](
                {"billingSettings": {"geminiApiBillingCreditDiscountPct": 38}}
            )
            self.assertTrue(ok, err)
            self.assertAlmostEqual(ratio(), 0.38, places=6)

    def test_managed_service_savings_default_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            bs = self.ns["get_billing_settings"]()
            self.assertEqual(bs.get("managedServiceSavingsPct"), 0.0)
            self.assertEqual(bs.get("managedServiceCacheHitRatioPct"), 0.0)

    def test_get_model_rates_applies_regional_rate_to_non_global_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            global_rates = self.ns["get_model_rates"]("gemini-2.5-pro", "global")
            eu_west4_rates = self.ns["get_model_rates"]("gemini-2.5-pro", "europe-west4")
            eu_multi_rates = self.ns["get_model_rates"]("gemini-2.5-pro", "eu")
            self.assertAlmostEqual(global_rates["input"], 1.25, places=4)
            self.assertAlmostEqual(eu_west4_rates["input"], round(global_rates["input"] * 1.10, 4), places=4)
            self.assertAlmostEqual(eu_multi_rates["input"], round(global_rates["input"] * 1.10, 4), places=4)

    def test_process_vertex_tokens_with_zero_discount_and_zero_cache_matches_gross(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            mon_results = {
                "vertex_tok": [
                    {
                        "metric": {"labels": {"type": "input"}},
                        "resource": {"labels": {"model_user_id": "gemini-2.5-pro", "location": "global"}},
                        "points": [
                            {
                                "interval": {"endTime": "2026-10-15T12:00:00Z"},
                                "value": {"int64Value": "1000000"},
                            }
                        ],
                    }
                ],
                "vertex_inv": [],
            }
            result = {
                "vertexEnabled": True,
                "models": {},
                "dailySeries": {},
                "credentialsUsage": {},
                "inputTokens": 0,
                "outputTokens": 0,
                "cachedTokens": 0,
                "thinkingTokens": 0,
                "totalTokens": 0,
                "vertexGrossCostUsd": 0.0,
                "vertexCacheSavingsUsd": 0.0,
                "vertexCostUsd": 0.0,
                "estimatedCostUsd": 0.0,
                "inferenceRequests": 0,
            }
            self.ns["_process_vertex_tokens_and_invocations"](
                mon_results, "demo-project", "tok", "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z",
                True, 200, set(), result
            )
            m = result["models"]["gemini-2.5-pro"]
            self.assertAlmostEqual(m["grossCostUsd"], 1.25, places=4)
            self.assertAlmostEqual(m["costUsd"], 1.25, places=4)
            self.assertAlmostEqual(m["cacheSavingsUsd"], 0.0, places=4)
            self.assertAlmostEqual(result["dailySeries"]["2026-10-15"]["vertexCostUsd"], 1.25, places=4)

    def test_get_model_rates_unknown_model_falls_back_to_default_estimated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ns["MODELS_PRICING_FILE"] = str(Path(tmp) / "models_pricing_config.json")
            self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
            rates = self.ns["get_model_rates"]("modello-inventato-xyz", "global")
            self.assertTrue(rates["isEstimated"])
            self.assertAlmostEqual(rates["input"], 0.50, places=4)

    def test_slice_cached_payload_for_days_uses_exact_credential_sum_not_proportional(self) -> None:
        base_payload = {
            "days": 30,
            "scannedAt": "2026-10-30T18:00:00Z",
            "projects": [
                {
                    "projectId": "demo-project",
                    "name": "Demo Project",
                    "billingEnabled": True,
                    "aiActive": True,
                    "scanDays": 30,
                    "totalRequests": 20,
                    "inferenceRequests": 20,
                    "totalTokens": 20000,
                    "estimatedCostUsd": 10.0,
                    "geminiCostUsd": 10.0,
                    "vertexCostUsd": 0.0,
                    "otherAiCostUsd": 0.0,
                    "dailySeries": {
                        "2026-10-05": {
                            "requests": 10, "inferenceRequests": 10, "tokens": 10000,
                            "inputTokens": 8000, "outputTokens": 2000,
                            "geminiCostUsd": 8.0, "costUsd": 8.0,
                        },
                        "2026-10-28": {
                            "requests": 10, "inferenceRequests": 10, "tokens": 10000,
                            "inputTokens": 8000, "outputTokens": 2000,
                            "geminiCostUsd": 2.0, "costUsd": 2.0,
                        },
                    },
                    "credentialsUsage": [
                        {
                            "credentialId": "apikey:key-1",
                            "requests": 20,
                            "inferenceRequests": 20,
                            "ok200": 20,
                            "ok200Inference": 20,
                            "totalTokens": 20000,
                            "inputTokens": 16000,
                            "outputTokens": 4000,
                            "estimatedCostUsd": 10.0,
                            "grossCostUsd": 10.0,
                            "cacheSavingsUsd": 0.0,
                            "dailySeries": {
                                "2026-10-05": {
                                    "requests": 10, "inferenceRequests": 10, "ok200": 10,
                                    "tokens": 10000, "inputTokens": 8000, "outputTokens": 2000, "costUsd": 8.0,
                                },
                                "2026-10-28": {
                                    "requests": 10, "inferenceRequests": 10, "ok200": 10,
                                    "tokens": 10000, "inputTokens": 8000, "outputTokens": 2000, "costUsd": 2.0,
                                },
                            },
                        }
                    ],
                    "apiKeys": [
                        {
                            "uid": "key-1",
                            "displayName": "Demo Key",
                            "requests": 20,
                            "inferenceRequests": 20,
                            "totalTokens": 20000,
                            "estimatedCostUsd": 10.0,
                        }
                    ],
                    "usersUsage": [
                        {
                            "userEmail": "dev@example.com",
                            "estimatedCostUsd": 10.0,
                            "directCostUsd": 10.0,
                            "oauthCostUsd": 0.0,
                            "vertexOauthCostUsd": 0.0,
                            "apiKeysCostUsd": 10.0,
                            "apiKeysGrossCostUsd": 10.0,
                            "apiKeysCacheSavingsUsd": 0.0,
                            "apiKeysTotalTokens": 20000,
                            "attributedTokens": 20000,
                            "totalInteractions": 20,
                            "apiKeysDetails": [
                                {
                                    "uid": "key-1",
                                    "displayName": "Demo Key",
                                    "calls": 20,
                                    "ok200Calls": 20,
                                    "inputTokens": 16000,
                                    "outputTokens": 4000,
                                    "totalTokens": 20000,
                                    "costUsd": 10.0,
                                    "grossCostUsd": 10.0,
                                    "cacheSavingsUsd": 0.0,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        sliced_7d = self.ns["slice_cached_payload_for_days"](base_payload, 7, {"activeAccount": None})
        u_7d = sliced_7d["projects"][0]["usersUsage"][0]
        # Exact sum on last 7 days (2026-10-24..2026-10-30) is $2.00 (2026-10-28), NOT 10.0 * 7 / 30 ($2.3333)
        self.assertAlmostEqual(u_7d["apiKeysCostUsd"], 2.0, places=4)
        self.assertAlmostEqual(u_7d["estimatedCostUsd"], 2.0, places=4)
        self.assertEqual(u_7d["attributedTokens"], 10000)

        # Monotonicity check: single day (2026-10-30, $0.0) <= 7d ($2.0) <= 30d ($10.0)
        sliced_today = self.ns["slice_cached_payload_for_days"](
            base_payload, 1, {"activeAccount": None}, start_date="2026-10-30", end_date="2026-10-30", preset="single"
        )
        u_today = sliced_today["projects"][0]["usersUsage"][0]
        self.assertLessEqual(u_today["estimatedCostUsd"], u_7d["estimatedCostUsd"])
        self.assertLessEqual(u_7d["estimatedCostUsd"], 10.0)

    def test_reconcile_user_oauth_cost_uses_direct_only_when_pool_is_zero(self):
        orig_rates = self.ns["get_model_rates"]
        self.ns["get_model_rates"] = lambda *args, **kwargs: {
            "input": 5.0,
            "output": 0.0,
            "cache_read_input": 0.0,
        }
        try:
            # Case 1: oauth_pool_cost = 0, direct_oauth = 5.0 -> user gets 5.0
            user_records_zero = {}
            u1 = self.ns["_get_or_create_user_record"](user_records_zero, "user@example.com", "demo-proj")
            u1["totalInteractions"] = 1
            u1["loggedInputTokens"] = 1_000_000
            u1["loggedTotalTokens"] = 1_000_000
            self.ns["_reconcile_user_oauth_and_final_costs"](user_records_zero, {})
            self.assertAlmostEqual(u1["oauthCostUsd"], 5.0, places=4)

            # Case 2: oauth_pool_cost = 3.0, direct_oauth = 5.0 -> user gets 3.0 (not inflated to 5.0)
            user_records_pool = {}
            u2 = self.ns["_get_or_create_user_record"](user_records_pool, "user@example.com", "demo-proj")
            u2["totalInteractions"] = 1
            u2["loggedInputTokens"] = 1_000_000
            u2["loggedTotalTokens"] = 1_000_000
            creds_dict = {
                "oauth:shared-client": {
                    "credentialId": "oauth:shared-client",
                    "authType": "OAUTH_USER_CLIENT",
                    "estimatedCostUsd": 3.0,
                    "totalTokens": 1_000_000,
                    "services": ["discoveryengine.googleapis.com"],
                }
            }
            self.ns["_reconcile_user_oauth_and_final_costs"](user_records_pool, creds_dict)
            self.assertAlmostEqual(u2["oauthCostUsd"], 3.0, places=4)
        finally:
            self.ns["get_model_rates"] = orig_rates

    def test_vertex_oauth_client_owner_attribution_and_no_double_counting(self):
        from datetime import datetime, timezone

        orig_rates = self.ns["get_model_rates"]
        orig_cfg = self.ns["load_models_pricing_config"]
        try:
            self.ns["get_model_rates"] = lambda m=None, location="global": {
                "input": 1.0,
                "output": 2.0,
                "cache_read_input": 0.1,
            }
            self.ns["load_models_pricing_config"] = lambda: {
                "oauthClientOwners": {
                    "100000000001-testclient.apps.googleusercontent.com": {
                        "ownerEmail": "client-test@example.com",
                        "displayName": "Antigravity IDE (Test Client)",
                        "tool": "Antigravity IDE (Vertex AI OAuth)",
                    }
                }
            }

            result = {"projectId": "demo-proj"}
            creds_dict = {
                "oauth2:100000000001-testclient.apps.googleusercontent.com": {
                    "credentialId": "oauth2:100000000001-testclient.apps.googleusercontent.com",
                    "authType": "OAUTH_USER_CLIENT",
                    "displayName": "OAuth Client (100000000001-testclient...)",
                    "services": ["aiplatform.googleapis.com"],
                    "vertexInferenceRequests": 42,
                    "inferenceRequests": 42,
                    "inputTokens": 200_000,
                    "outputTokens": 100_000,
                    "totalTokens": 300_000,
                    "estimatedCostUsd": 12.5,
                    "vertexCostUsd": 12.5,
                    "todayCostUsd": 2.5,
                    "yesterdayCostUsd": 1.5,
                    "modelsUsed": ["gemini-2.5-pro"],
                    "modelCosts": [
                        {
                            "model": "gemini-2.5-pro",
                            "calls": 42,
                            "inputTokens": 200_000,
                            "outputTokens": 100_000,
                            "totalTokens": 300_000,
                            "costUsd": 12.5,
                        }
                    ],
                },
                "oauth2:shared-agentspace-client": {
                    "credentialId": "oauth2:shared-agentspace-client",
                    "authType": "OAUTH_USER_CLIENT",
                    "displayName": "Shared Agentspace OAuth",
                    "services": ["discoveryengine.googleapis.com"],
                    "inferenceRequests": 10,
                    "totalTokens": 50_000,
                    "estimatedCostUsd": 3.0,
                },
            }

            user_records = {}
            as_user = self.ns["_get_or_create_user_record"](user_records, "agentspace-user@example.com", "demo-proj")
            as_user["totalInteractions"] = 10
            as_user["discoveryCount"] = 10
            as_user["loggedInputTokens"] = 50_000
            as_user["loggedTotalTokens"] = 50_000

            end_dt = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
            self.ns["_attribute_oauth_clients_to_user_records"](result, creds_dict, end_dt, "demo-proj", user_records)
            self.ns["_reconcile_user_oauth_and_final_costs"](user_records, creds_dict)

            # Owner receives Vertex OAuth cost/tokens directly
            self.assertIn("client-test@example.com", user_records)
            owner_rec = user_records["client-test@example.com"]
            self.assertEqual(owner_rec["userType"], "INTERNAL_USER")
            self.assertEqual(owner_rec["vertexOauthCalls"], 42)
            self.assertEqual(owner_rec["vertexOauthTokens"], 300_000)
            self.assertAlmostEqual(owner_rec["vertexOauthCostUsd"], 12.5, places=4)
            self.assertAlmostEqual(owner_rec["estimatedCostUsd"], 12.5, places=4)
            self.assertEqual(len(owner_rec["oauthClientsDetails"]), 1)

            # Agentspace user only gets the remaining shared OAuth pool (3.0), not the 12.5 Vertex OAuth cost
            self.assertAlmostEqual(as_user["vertexOauthCostUsd"], 0.0, places=4)
            self.assertAlmostEqual(as_user["oauthCostUsd"], 3.0, places=4)
            self.assertAlmostEqual(as_user["estimatedCostUsd"], 3.0, places=4)

            # Total user cost equals total credential cost (no double counting)
            total_users_cost = sum(u["estimatedCostUsd"] for u in user_records.values())
            total_creds_cost = sum(c["estimatedCostUsd"] for c in creds_dict.values())
            self.assertAlmostEqual(total_users_cost, total_creds_cost, places=4)
        finally:
            self.ns["get_model_rates"] = orig_rates
            self.ns["load_models_pricing_config"] = orig_cfg

    def test_vertex_oauth_unmapped_client_creates_oauth_workload(self):
        from datetime import datetime, timezone

        orig_rates = self.ns["get_model_rates"]
        orig_cfg = self.ns["load_models_pricing_config"]
        try:
            self.ns["get_model_rates"] = lambda m=None, location="global": {
                "input": 1.0,
                "output": 2.0,
                "cache_read_input": 0.1,
            }
            self.ns["load_models_pricing_config"] = lambda: {"oauthClientOwners": {}}

            result = {"projectId": "demo-proj"}
            creds_dict = {
                "oauth2:999888777666-unmappedclient.apps.googleusercontent.com": {
                    "credentialId": "oauth2:999888777666-unmappedclient.apps.googleusercontent.com",
                    "authType": "OAUTH_USER_CLIENT",
                    "services": ["aiplatform.googleapis.com"],
                    "vertexInferenceRequests": 15,
                    "inferenceRequests": 15,
                    "inputTokens": 40_000,
                    "outputTokens": 10_000,
                    "totalTokens": 50_000,
                    "estimatedCostUsd": 4.2,
                    "vertexCostUsd": 4.2,
                    "modelsUsed": ["gemini-2.5-flash"],
                }
            }
            user_records = {}
            end_dt = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
            self.ns["_attribute_oauth_clients_to_user_records"](result, creds_dict, end_dt, "demo-proj", user_records)
            self.ns["_reconcile_user_oauth_and_final_costs"](user_records, creds_dict)

            expected_key = "oauth-workload:999888777666"
            self.assertIn(expected_key, user_records)
            wl_rec = user_records[expected_key]
            self.assertEqual(wl_rec["userType"], "OAUTH_WORKLOAD")
            self.assertEqual(wl_rec["vertexOauthCalls"], 15)
            self.assertEqual(wl_rec["vertexOauthTokens"], 50_000)
            self.assertAlmostEqual(wl_rec["estimatedCostUsd"], 4.2, places=4)
        finally:
            self.ns["get_model_rates"] = orig_rates
            self.ns["load_models_pricing_config"] = orig_cfg


class TestModelsPricingSyncAndEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ns = load_app_namespace()
        self.ns["DATA_DIR"] = self.tmp.name
        self.ns["TOKENS_FILE"] = os.path.join(self.tmp.name, "oauth_tokens.json")
        self.ns["SYNC_REGISTRY_FILE"] = os.path.join(self.tmp.name, "projects_sync_registry.json")
        self.ns["MODELS_PRICING_FILE"] = os.path.join(self.tmp.name, "models_pricing_config.json")
        self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _make_sku(sku_id: str, desc: str, units: int, nanos: int, usage_unit: str, regions: list[str] = None) -> dict:
        return {
            "skuId": sku_id,
            "description": desc,
            "serviceRegions": regions or ["global"],
            "pricingInfo": [
                {
                    "pricingExpression": {
                        "usageUnitDescription": usage_unit,
                        "tieredRates": [
                            {
                                "startUsageAmount": 0,
                                "unitPrice": {"units": str(units), "nanos": nanos},
                            }
                        ],
                    }
                }
            ],
        }

    def test_billing_catalog_pagination_units_and_long_context_skip(self) -> None:
        calls = []

        def fake_get(url, token, timeout=12, user_project=None):
            calls.append((url, user_project))
            if "AEFD-7695-64FA/skus" in url and "pageToken=page2" not in url:
                return 200, {
                    "skus": [
                        # Per 1,000 tokens: $0.00125 per 1k -> $1.25 per 1M
                        self._make_sku(
                            "SKU-PRO-IN-1K",
                            "Gemini 2.5 Pro Text Input Tokens",
                            0,
                            1_250_000,
                            "1,000 tokens",
                            ["global"],
                        ),
                        # Long context >200k must be ignored
                        self._make_sku(
                            "SKU-PRO-LONG",
                            "Gemini 2.5 Pro Long Input Prompts > 200k Tokens",
                            0,
                            9_990_000,
                            "1,000 tokens",
                            ["global"],
                        ),
                    ],
                    "nextPageToken": "page2",
                }
            if "AEFD-7695-64FA/skus" in url and "pageToken=page2" in url:
                return 200, {
                    "skus": [
                        # Per 1,000,000 tokens (1M): $10.00 per 1M
                        self._make_sku(
                            "SKU-PRO-OUT-1M",
                            "Gemini 2.5 Pro Text Output Tokens",
                            10,
                            0,
                            "1,000,000 tokens",
                            ["global"],
                        ),
                        # Regional SKU in europe-west4: $0.0015 per 1k -> $1.50 per 1M
                        self._make_sku(
                            "SKU-PRO-IN-REG",
                            "Gemini 2.5 Pro Text Input Regional",
                            0,
                            1_500_000,
                            "1,000 tokens",
                            ["europe-west4"],
                        ),
                    ]
                }
            if "C7E2-9256-1C43/skus" in url:
                return 200, {"skus": []}
            if "publishers/google/models" in url:
                if user_project is None:
                    return 403, {"error": {"message": "Quota project required"}}
                return 200, {
                    "publisherModels": [
                        {"name": "publishers/google/models/gemini-2.5-flash-002"}
                    ]
                }
            if "publishers/anthropic/models" in url:
                return 200, {"publisherModels": []}
            return 200, {}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("secret-token-xyz", user_project="proj-alpha")

        pro_entry = cfg["models"]["gemini-2.5-pro"]
        # Long-context SKU ($9.99) ignored; page 1 ($1.25) and page 2 ($10.00) applied
        self.assertAlmostEqual(pro_entry["input"], 1.25, places=4)
        self.assertAlmostEqual(pro_entry["output"], 10.0, places=4)
        self.assertAlmostEqual(pro_entry["regional_input"], 1.50, places=4)
        self.assertEqual(pro_entry["lastSkuIdGlobal"], "SKU-PRO-IN-1K")
        self.assertEqual(pro_entry["lastSkuIdRegional"], "SKU-PRO-IN-REG")
        self.assertEqual(pro_entry["source"], "GCP_BILLING_API:AEFD-7695-64FA")

        # Publisher model discovered after 403 retry with user_project="proj-alpha"
        self.assertIn("gemini-2.5-flash-002", cfg["models"])
        self.assertEqual(cfg["models"]["gemini-2.5-flash-002"]["source"], "VERTEX_PUBLISHER_API:google")
        self.assertFalse(cfg["lastApiSync"]["partial"])
        self.assertEqual(cfg["lastApiSync"]["errors"], [])
        # Verify first attempt uses user_project=None and 403 fallback uses user_project="proj-alpha"
        self.assertTrue(any(up == "proj-alpha" and "publishers/google/models" in u for u, up in calls))
        self.assertTrue(all(up in (None, "proj-alpha") for _, up in calls))

    def test_sync_reads_catalog_fx_rate_and_auto_mode_uses_it(self) -> None:
        def fake_get(url, token, timeout=12, user_project=None):
            if "currencyCode=EUR" in url:
                return 200, {"skus": [{"pricingInfo": [{"effectiveTime": "2026-11-04T08:00:00Z", "currencyConversionRate": 0.8981}]}]}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="proj-1")
        self.assertAlmostEqual(cfg["fxRate"]["usdToEur"], 0.8981, places=6)
        self.assertEqual(cfg["fxRate"]["effectiveTime"], "2026-11-04T08:00:00Z")
        self.assertFalse(cfg["lastApiSync"]["errors"])
        # automatic mode (default) uses the catalog rate, manual mode uses the typed value
        self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.8981, places=6)
        ok, err, _ = self.ns["validate_and_apply_models_pricing_update"](
            {"billingSettings": {"usdToEurRateAuto": False, "usdToEurRate": 0.88}}
        )
        self.assertTrue(ok, err)
        self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.88, places=6)
        ok, err, _ = self.ns["validate_and_apply_models_pricing_update"]({"billingSettings": {"usdToEurRateAuto": "yes"}})
        self.assertFalse(ok)

    def test_sync_without_fx_rate_keeps_manual_rate_and_records_error(self) -> None:
        def fake_get(url, token, timeout=12, user_project=None):
            if "currencyCode=EUR" in url:
                return 500, {"error": {"message": "boom"}}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="proj-1")
        self.assertNotIn("fxRate", cfg)
        self.assertTrue(any("EUR rate" in e for e in cfg["lastApiSync"]["errors"]))
        self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.92, places=6)

    def test_previous_fx_rate_survives_a_failed_fx_fetch(self) -> None:
        state = {"fx_ok": True}

        def fake_get(url, token, timeout=12, user_project=None):
            if "currencyCode=EUR" in url:
                if state["fx_ok"]:
                    return 200, {"skus": [{"pricingInfo": [{"effectiveTime": "t1", "currencyConversionRate": 0.9}]}]}
                return 500, {"error": {"message": "boom"}}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")
        state["fx_ok"] = False
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")
        self.assertAlmostEqual(cfg["fxRate"]["usdToEur"], 0.9, places=6)
        self.assertAlmostEqual(self.ns["get_usd_to_eur_rate"](), 0.9, places=6)

    def test_extract_catalog_fx_rate_rejects_identity_and_out_of_range(self) -> None:
        extract = self.ns["extract_catalog_fx_rate"]
        self.assertEqual(extract({"skus": [{"pricingInfo": [{"currencyConversionRate": 1.0}]}]}), None)
        self.assertEqual(extract({"skus": [{"pricingInfo": [{"currencyConversionRate": 9.9}]}]}), None)
        self.assertEqual(extract({"skus": []}), None)
        self.assertEqual(extract({"skus": [{"pricingInfo": [{"currencyConversionRate": 0.9, "effectiveTime": "t"}]}]}), (0.9, "t"))

    def test_publisher_sync_tries_quota_candidates_until_one_answers(self) -> None:
        calls = []

        def fake_get(url, token, timeout=12, user_project=None):
            calls.append((("publishers" in url), user_project))
            if "publishers/google/models" in url:
                if user_project == "proj-b":
                    return 200, {"publisherModels": [{"name": "publishers/google/models/gemini-9-test", "launchStage": "GA"}]}
                return 403, {"error": {"message": "no quota permission"}}
            if "publishers/anthropic/models" in url:
                return 200, {"publisherModels": []}
            return 200, {"skus": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"](
            "tok", user_project="proj-a", quota_candidates=["proj-a", "proj-b", "proj-c"]
        )
        self.assertEqual(cfg["lastApiSync"]["quotaProject"], "proj-b")
        self.assertEqual(cfg["lastApiSync"]["publisherModelsDiscovered"], 1)
        self.assertIn("gemini-9-test", cfg["models"])
        self.assertFalse(cfg["lastApiSync"]["errors"])
        # proj-c is never needed once proj-b answers
        self.assertNotIn(("True", "proj-c"), [(str(a), b) for a, b in calls])

    def test_quota_project_candidates_ranked_by_ai_cost(self) -> None:
        reg = {"accounts": {"me@example.com": {"projects": {
            "p-none": {"scanEnabled": False, "hasAiData": False},
            "p-small": {"scanEnabled": True, "hasAiData": True, "estimatedCostUsd": 5},
            "p-big": {"scanEnabled": True, "hasAiData": True, "estimatedCostUsd": 500},
            "p-quiet": {"scanEnabled": True, "hasAiData": False},
        }}}}
        cands = self.ns["get_quota_project_candidates"]("me@example.com", reg=reg, raw_projects=[{"projectId": "p-raw"}], limit=5)
        self.assertEqual(cands, ["p-big", "p-small", "p-quiet", "p-none", "p-raw"])

    def _seed_models(self, extra: dict) -> None:
        cfg = self.ns["load_models_pricing_config"]()
        cfg["models"].update(extra)
        self.ns["save_models_pricing_config"](cfg)

    @staticmethod
    def _entry(model_id: str, publisher: str, source: str, **extra) -> dict:
        base = {"modelId": model_id, "displayName": model_id, "publisher": publisher, "input": 1.0, "output": 2.0,
                "thinking": 2.0, "cache_read_input": 0.1, "source": source, "lastSkuIdGlobal": "", "lastSkuIdRegional": "",
                "updatedAt": "2026-01-01T00:00:00+00:00"}
        base.update(extra)
        return base

    def _fake_publishers(self, google, anthropic, google_status=200, pages=None):
        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                if google_status != 200:
                    return google_status, {"error": {"message": "nope"}}
                if pages and "pageToken=p2" not in url:
                    return 200, {"publisherModels": [{"name": f"publishers/google/models/{m}"} for m in google[:1]], "nextPageToken": "p2"}
                if pages:
                    return 200, {"publisherModels": [{"name": f"publishers/google/models/{m}"} for m in google[1:]]}
                return 200, {"publisherModels": [{"name": f"publishers/google/models/{m}@default", "launchStage": "GA"} for m in google]}
            if "publishers/anthropic/models" in url:
                return 200, {"publisherModels": [{"name": f"publishers/anthropic/models/{m}"} for m in anthropic]}
            return 200, {"skus": []}
        return fake_get

    def test_model_list_follows_api_deleted_kept_and_non_google_removed(self) -> None:
        self._seed_models({
            "gemini-old": self._entry("gemini-old", "google", "BUILTIN_DEFAULT", manualOverride={"input": 9.0}),
            "veo-3.1": self._entry("veo-3.1", "google", "BUILTIN_DEFAULT"),
            "llama-x": self._entry("llama-x", "partner", "BUILTIN_DEFAULT"),
            "claude-old": self._entry("claude-old", "anthropic", "BUILTIN_DEFAULT"),
            "claude-cat": self._entry("claude-cat", "anthropic", "GCP_BILLING_API:C7E2-9256-1C43"),
            "claude-keep": self._entry("claude-keep", "anthropic", "BUILTIN_DEFAULT", manualOverride={"input": 5.0}),
            "obs-partner": self._entry("obs-partner", "partner", "CLOUD_MONITORING_DISCOVERED"),
        })
        self.ns["gcp_api_get"] = self._fake_publishers(["gemini-new", "gemini-2.5-pro"], ["claude-api"])
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p", extra_model_ids=["obs-partner"])
        m = cfg["models"]
        self.assertEqual(m["gemini-new"]["status"], "active")
        self.assertEqual(m["claude-api"]["status"], "active")
        self.assertEqual(m["claude-api"]["publisher"], "anthropic")
        # Google models the API does not return stay in the list, flagged deleted, with rates and overrides
        self.assertEqual(m["gemini-old"]["status"], "deleted")
        self.assertTrue(m["gemini-old"]["deletedAt"])
        self.assertEqual(m["gemini-old"]["manualOverride"], {"input": 9.0})
        self.assertEqual(m["veo-3.1"]["status"], "deleted")
        # non-Google never returned by a Google service is removed; with a manual override or a catalog/monitoring origin it is kept
        self.assertNotIn("llama-x", m)
        self.assertNotIn("claude-old", m)
        self.assertIn("claude-keep", m)
        self.assertEqual(m["claude-cat"]["status"], "deleted")
        self.assertIn("obs-partner", m)
        self.assertNotIn("status", m["obs-partner"])
        self.assertTrue(cfg["lastApiSync"]["listAuthoritative"])
        self.assertIn("llama-x", cfg["lastApiSync"]["modelsRemoved"])
        # a deleted model that comes back is active again
        self.ns["gcp_api_get"] = self._fake_publishers(["gemini-new", "gemini-old"], ["claude-api"])
        cfg2 = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")
        self.assertEqual(cfg2["models"]["gemini-old"]["status"], "active")
        self.assertNotIn("deletedAt", cfg2["models"]["gemini-old"])
        # removed built-ins are not resurrected by the loader
        self.assertNotIn("llama-x", self.ns["load_models_pricing_config"]()["models"])

    def test_sync_keeps_gemini_api_rates_and_cache_share_of_existing_entries(self) -> None:
        keep = {"geminiApiRates": {"input": 0.5, "output": 3.0}, "geminiApiCacheHitRatioPct": 40.0,
                "manualOverride": {"input": 7.0}}
        self._seed_models({"gemini-kept": self._entry("gemini-kept", "google", "BUILTIN_DEFAULT", **keep),
                           "gemini-gone": self._entry("gemini-gone", "google", "BUILTIN_DEFAULT", **keep)})
        self.ns["gcp_api_get"] = self._fake_publishers(["gemini-kept"], [])
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")
        for mid, status in (("gemini-kept", "active"), ("gemini-gone", "deleted")):
            ent = cfg["models"][mid]
            self.assertEqual(ent["status"], status)
            self.assertEqual(ent["geminiApiRates"], {"input": 0.5, "output": 3.0})
            self.assertEqual(ent["geminiApiCacheHitRatioPct"], 40.0)
            self.assertEqual(ent["manualOverride"], {"input": 7.0})
        # the stored file reloads with the same state
        again = self.ns["load_models_pricing_config"]()["models"]
        self.assertEqual(again["gemini-gone"]["status"], "deleted")
        self.assertEqual(again["gemini-gone"]["geminiApiCacheHitRatioPct"], 40.0)

    def test_non_text_modalities_are_stored_apart_and_do_not_change_text_rates(self) -> None:
        self._seed_models({"gemini-9-test": self._entry("gemini-9-test", "google", "BUILTIN_DEFAULT")})
        v = [self._make_sku("V-IN", "Gemini 9 Test Global Text Input - Online Predictions", 0, 4000, "count"),
             self._make_sku("V-AIN", "Gemini 9 Test Global Audio Input - Online Predictions", 0, 9000, "count"),
             self._make_sku("V-IMG", "Gemini 9 Test Global Image Input - Online Predictions", 0, 5000, "count")]
        cfg = self._sync_with_catalog(v)
        m = cfg["models"]["gemini-9-test"]
        self.assertEqual(m["input"], 4.0)
        self.assertEqual(m["catalog"]["vertex"]["audio"]["input"], 9.0)
        self.assertEqual(m["catalog"]["vertex"]["image"]["input"], 5.0)

    def test_corrupt_pricing_file_is_kept_aside_and_save_is_atomic(self) -> None:
        path = self.ns["MODELS_PRICING_FILE"]
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"models": {"x": ')
        self.ns["_MODELS_PRICING_MEM_CACHE"]["data"] = None
        cfg = self.ns["load_models_pricing_config"]()
        self.assertTrue(cfg["models"])
        leftovers = [n for n in os.listdir(os.path.dirname(path)) if ".corrupt-" in n]
        self.assertEqual(len(leftovers), 1)
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_failed_publisher_call_changes_nothing(self) -> None:
        self._seed_models({"gemini-old": self._entry("gemini-old", "google", "BUILTIN_DEFAULT"),
                           "llama-x": self._entry("llama-x", "partner", "BUILTIN_DEFAULT")})
        self.ns["gcp_api_get"] = self._fake_publishers([], [], google_status=403)
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertFalse(cfg["lastApiSync"]["listAuthoritative"])
        self.assertTrue(cfg["lastApiSync"]["partial"])
        self.assertNotIn("status", cfg["models"]["gemini-old"])
        self.assertIn("llama-x", cfg["models"])
        self.assertNotIn("modelListFromApi", cfg)

    def _sync_with_catalog(self, v_skus, g_skus=None, catalog_status=200):
        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                return 200, {"publisherModels": [{"name": "publishers/google/models/gemini-9-test"},
                                                 {"name": "publishers/google/models/gemini-9-nocat"}]}
            if "publishers/anthropic/models" in url:
                return 200, {"publisherModels": []}
            if "C7E2-9256-1C43/skus" in url:
                return (200, {"skus": v_skus}) if catalog_status == 200 else (catalog_status, {"error": {"message": "x"}})
            if "AEFD-7695-64FA/skus" in url:
                return (200, {"skus": g_skus or []}) if catalog_status == 200 else (catalog_status, {"error": {"message": "x"}})
            return 200, {"skus": []}
        self.ns["gcp_api_get"] = fake_get
        return self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")

    def test_sync_applies_catalog_rates_per_model_without_estimates(self) -> None:
        self._seed_models({"gemini-9-test": self._entry("gemini-9-test", "google", "BUILTIN_DEFAULT", manualOverride={"output": 99.0})})
        v = [self._make_sku("V-IN", "Gemini 9 Test Global Text Input - Predictions", 0, 4000, "count"),
             self._make_sku("V-OUT", "Gemini 9 Test Global Text Output - Predictions", 0, 20000, "count"),
             self._make_sku("V-THK", "Gemini 9 Test Thinking Text Output - Predictions", 0, 30000, "count"),
             self._make_sku("V-RIN", "Gemini 9 Test Regional Text Input - Predictions", 0, 4400, "count", ["europe-west3"])]
        g = [self._make_sku("G-IN", "Generate content input token count gemini 9 test text", 0, 2000, "count")]
        cfg = self._sync_with_catalog(v, g)
        m = cfg["models"]["gemini-9-test"]
        self.assertEqual(m["pricingStatus"], "CATALOG")
        self.assertEqual(m["input"], 4.0)
        self.assertEqual(m["output"], 99.0)                              # manual override wins over catalog 20.0
        self.assertEqual(m["manualOverride"], {"output": 99.0})        # manual override is never replaced
        self.assertEqual(m["regional_input"], 4.4)
        self.assertEqual(m["geminiApiRates"], {"input": 2.0})
        self.assertEqual(m["catalog"]["vertex"]["text"]["thinking"], 30.0)
        self.assertEqual(m["lastSkuIdRegional"], "V-RIN")
        self.assertTrue(m["source"] == "MANUAL" or m["source"].startswith("GCP_BILLING_API"))
        # a model with no SKU at all is reported as such (its numbers are not presented as catalog prices)
        self.assertEqual(cfg["models"]["gemini-9-nocat"]["pricingStatus"], "NO_CATALOG_PRICE")
        self.assertGreaterEqual(cfg["lastApiSync"]["skusMatched"], 4)

    def test_partial_vertex_catalog_never_replaces_vertex_rates_with_gemini_api_ones(self) -> None:
        self._seed_models({"gemini-9-test": self._entry("gemini-9-test", "google", "GCP_BILLING_API:C7E2-9256-1C43",
                                                        pricingStatus="CATALOG", input=4.0, output=20.0)})

        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                return 200, {"publisherModels": [{"name": "publishers/google/models/gemini-9-test"}]}
            if "publishers/anthropic/models" in url:
                return 200, {"publisherModels": []}
            if "C7E2-9256-1C43/skus" in url:
                return 503, {"error": {"message": "x"}}
            if "AEFD-7695-64FA/skus" in url:
                return 200, {"skus": [self._make_sku("G-IN", "Generate content input token count gemini 9 test text", 0, 2000, "count")]}
            return 200, {"skus": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="p")
        m = cfg["models"]["gemini-9-test"]
        self.assertEqual((m["input"], m["output"]), (4.0, 20.0))          # Vertex rates untouched
        self.assertEqual(m["geminiApiRates"], {"input": 2.0})              # the complete service is applied
        self.assertEqual(m["pricingStatus"], "CATALOG")

    def test_catalog_failure_leaves_pricing_status_untouched(self) -> None:
        self._seed_models({"gemini-9-test": self._entry("gemini-9-test", "google", "GCP_BILLING_API:C7E2-9256-1C43",
                                                        pricingStatus="CATALOG", input=4.0)})
        cfg = self._sync_with_catalog([], catalog_status=503)
        self.assertTrue(cfg["lastApiSync"]["partial"])
        self.assertEqual(cfg["models"]["gemini-9-test"]["pricingStatus"], "CATALOG")
        self.assertEqual(cfg["models"]["gemini-9-test"]["input"], 4.0)
        self.assertNotIn("pricingStatus", cfg["models"]["gemini-9-nocat"])

    def test_non_google_kept_when_its_publisher_list_was_not_read(self) -> None:
        self._seed_models({"claude-old": self._entry("claude-old", "anthropic", "BUILTIN_DEFAULT"),
                           "llama-x": self._entry("llama-x", "partner", "BUILTIN_DEFAULT")})

        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                return 200, {"publisherModels": [{"name": "publishers/google/models/gemini-a"}]}
            if "publishers/anthropic/models" in url:
                return 500, {"error": {"message": "boom"}}
            return 200, {"skus": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertIn("claude-old", cfg["models"])      # Anthropic list not read: nothing decided
        self.assertNotIn("status", cfg["models"]["claude-old"])
        self.assertNotIn("llama-x", cfg["models"])      # partner family is never listed: removed once Google list is complete
        self.assertTrue(cfg["lastApiSync"]["partial"])

    def test_empty_or_broken_second_page_never_marks_models_deleted(self) -> None:
        self._seed_models({"gemini-old": self._entry("gemini-old", "google", "BUILTIN_DEFAULT")})
        # 200 with an empty Google list: not authoritative
        self.ns["gcp_api_get"] = self._fake_publishers([], [])
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertFalse(cfg["lastApiSync"]["listAuthoritative"])
        self.assertNotIn("status", cfg["models"]["gemini-old"])

        # first page ok, second page fails: not authoritative
        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                if "pageToken=p2" in url:
                    return 429, {"error": {"message": "slow down"}}
                return 200, {"publisherModels": [{"name": "publishers/google/models/gemini-a"}], "nextPageToken": "p2"}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertFalse(cfg["lastApiSync"]["listAuthoritative"])
        self.assertNotIn("status", cfg["models"]["gemini-old"])
        self.assertEqual(cfg["models"]["gemini-a"]["status"], "active")

    def test_more_than_ten_pages_is_not_authoritative(self) -> None:
        self._seed_models({"gemini-old": self._entry("gemini-old", "google", "BUILTIN_DEFAULT")})
        counter = {"n": 0}

        def fake_get(url, token, timeout=12, user_project=None):
            if "publishers/google/models" in url:
                counter["n"] += 1
                return 200, {"publisherModels": [{"name": f"publishers/google/models/gemini-p{counter['n']}"}],
                             "nextPageToken": f"t{counter['n']}"}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertEqual(counter["n"], 10)
        self.assertFalse(cfg["lastApiSync"]["listAuthoritative"])
        self.assertNotIn("status", cfg["models"]["gemini-old"])

    def test_publisher_list_is_read_across_pages(self) -> None:
        self.ns["gcp_api_get"] = self._fake_publishers(["gemini-a", "gemini-b"], [], pages=True)
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project=None)
        self.assertEqual(cfg["models"]["gemini-a"]["status"], "active")
        self.assertEqual(cfg["models"]["gemini-b"]["status"], "active")
        self.assertEqual(cfg["lastApiSync"]["modelsListedByApi"], 2)

    def test_default_catalog_seeds_only_google_models(self) -> None:
        defaults = self.ns["_build_default_models_pricing_config"]()["models"]
        self.assertTrue(defaults)
        self.assertTrue(all(m["publisher"] == "google" for m in defaults.values()))

    def test_billing_sync_429_sets_partial_and_records_sanitized_error(self) -> None:
        def fake_get(url, token, timeout=12, user_project=None):
            if "C7E2-9256-1C43/skus" in url:
                return 429, {"error": {"message": "Rate limit exceeded for secret-token-123"}}
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("secret-token-123", user_project="proj-1")
        self.assertTrue(cfg["lastApiSync"]["partial"])
        self.assertTrue(len(cfg["lastApiSync"]["errors"]) >= 1)
        joined_errors = " ".join(cfg["lastApiSync"]["errors"])
        self.assertIn("HTTP 429", joined_errors)
        self.assertNotIn("secret-token-123", joined_errors)

    def test_manual_override_survives_api_sync(self) -> None:
        ok, err, _ = self.ns["validate_and_apply_models_pricing_update"](
            {
                "models": {
                    "gemini-2.5-pro": {
                        "input": 2.22,
                        "output": 14.44,
                    }
                }
            }
        )
        self.assertTrue(ok, err)

        def fake_get(url, token, timeout=12, user_project=None):
            if "AEFD-7695-64FA/skus" in url:
                return 200, {
                    "skus": [
                        self._make_sku(
                            "SKU-PRO-IN",
                            "Gemini 2.5 Pro Text Input Tokens",
                            0,
                            1_250_000,
                            "1,000 tokens",
                            ["global"],
                        )
                    ]
                }
            return 200, {"skus": [], "publisherModels": []}

        self.ns["gcp_api_get"] = fake_get
        cfg = self.ns["sync_models_and_pricing_from_gcp_api"]("tok", user_project="proj-1")
        pro = cfg["models"]["gemini-2.5-pro"]
        self.assertEqual(pro["source"], "MANUAL")
        self.assertAlmostEqual(pro["input"], 2.22, places=4)
        self.assertAlmostEqual(pro["output"], 14.44, places=4)
        self.assertAlmostEqual(pro["manualOverride"]["input"], 2.22, places=4)

        rates = self.ns["get_model_rates"]("gemini-2.5-pro", "global")
        self.assertAlmostEqual(rates["input"], 2.22, places=4)
        self.assertAlmostEqual(rates["output"], 14.44, places=4)
        self.assertFalse(rates["isEstimated"])

    def test_daily_sync_runs_once_per_day_and_observed_models_registered_without_network(self) -> None:
        now = self.ns["time"].time()
        self.ns["save_tokens_store"](
            {
                "accounts": {
                    "u@example.com": {
                        "email": "u@example.com",
                        "access_token": "tok",
                        "refresh_token": None,
                        "expires_at": now + 3000,
                        "login_date": self.ns["get_today_date_str"](),
                        "daily_expires_at": now + 3000,
                        "session_id": "SID1",
                        "needs_reauth": False,
                    }
                }
            }
        )
        sync_calls = []

        def fake_sync(token, user_project=None, extra_model_ids=None, quota_candidates=None):
            sync_calls.append((token, user_project))
            cfg = self.ns["load_models_pricing_config"]()
            cfg["lastApiSync"] = {
                "syncedAt": self.ns["datetime"].now(self.ns["timezone"].utc).isoformat(),
                "partial": False,
                "errors": [],
            }
            self.ns["save_models_pricing_config"](cfg)
            return cfg

        self.ns["sync_models_and_pricing_from_gcp_api"] = fake_sync
        self.ns["list_all_accessible_projects"] = lambda token: [{"projectId": "p-demo", "name": "Demo"}]
        self.ns["inspect_single_project"] = lambda p, *args, **kwargs: {
            "projectId": p["projectId"],
            "name": p["name"],
            "billingEnabled": True,
            "skippedNoBilling": False,
            "aiActive": True,
            "scanStatus": "OK",
            "estimatedCostUsd": 1.0,
            "totalRequests": 5,
            "inferenceRequests": 5,
            "totalTokens": 1000,
            "models": [{"modelId": "custom-observed-model-v1", "calls": 5, "totalTokens": 1000, "costUsd": 1.0}],
            "enabledAiApis": [{"service": "aiplatform.googleapis.com", "title": "Vertex AI"}],
            "permissions": {"accessLevel": "FULL", "grantedIamPermissions": [], "missingIamPermissions": [], "areas": {}},
        }

        # First scan today triggers sync once and registers observed model locally
        res1 = self.ns["scan_all_projects"](
            days=7, requested_account="u@example.com", browser_accounts=["u@example.com"], session_id="SID1"
        )
        self.assertTrue(res1["success"])
        self.assertEqual(len(sync_calls), 1)
        self.assertEqual(sync_calls[0][1], "p-demo")

        cfg_after = self.ns["load_models_pricing_config"]()
        self.assertIn("custom-observed-model-v1", cfg_after["models"])
        self.assertEqual(cfg_after["models"]["custom-observed-model-v1"]["source"], "CLOUD_MONITORING_DISCOVERED")

        # Second scan on the same day does NOT call sync_models_and_pricing_from_gcp_api again
        res2 = self.ns["scan_all_projects"](
            days=7, requested_account="u@example.com", browser_accounts=["u@example.com"], session_id="SID1"
        )
        self.assertTrue(res2["success"])
        self.assertEqual(len(sync_calls), 1)

    def test_models_pricing_http_endpoints_validation_and_concurrency(self) -> None:
        self.ns["MonitorHandler"].log_message = lambda *args, **kwargs: None
        now = self.ns["time"].time()
        self.ns["save_tokens_store"](
            {
                "accounts": {
                    "u@example.com": {
                        "email": "u@example.com",
                        "access_token": "tok-secret",
                        "refresh_token": None,
                        "expires_at": now + 3000,
                        "login_date": self.ns["get_today_date_str"](),
                        "daily_expires_at": now + 3000,
                        "session_id": "SID_OK",
                        "needs_reauth": False,
                    }
                }
            }
        )
        # Seed a local oauthClientOwners entry on disk to verify HTTP sanitization never leaks it
        cfg_disk = self.ns["load_models_pricing_config"]()
        cfg_disk["oauthClientOwners"] = {"123-client": {"ownerEmail": "private@example.com"}}
        self.ns["save_models_pricing_config"](cfg_disk)

        srv = self.ns["ThreadingHTTPServer"](("127.0.0.1", 0), self.ns["MonitorHandler"])
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cookie = f"{self.ns['COOKIE_NAME']}=u%40example.com; {self.ns['SESSION_COOKIE_NAME']}=SID_OK"

        def api_call(method: str, path: str, payload: dict = None) -> tuple[int, dict]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                headers = {"Cookie": cookie}
                body = None
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                    body = json.dumps(payload)
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
            finally:
                conn.close()

        try:
            # 1. GET /api/models-pricing returns sanitized config without oauthClientOwners or accessToken
            st_code, body = api_call("GET", "/api/models-pricing")
            self.assertEqual(st_code, 200)
            self.assertTrue(body["success"])
            self.assertNotIn("oauthClientOwners", body["config"])
            self.assertNotIn("accessToken", body["auth"])
            self.assertGreater(body["modelsCount"], 0)

            # 2. Invalid POST /api/models-pricing/config payloads -> 400
            for bad_payload in (
                {"oauthClientOwners": {"x": "y"}},
                {"billingSettings": {"vertexBillingCreditDiscountPct": 99}},
                {"billingSettings": {"vertexImplicitCacheHitRatioPct": -5}},
                {"billingSettings": {"regionalMultiplierDefault": 5.0}},
                {"models": {"INVALID MODEL ID!": {"input": 1.0}}},
                {"models": {"gemini-2.5-pro": {"input": 2000.0}}},
                {"models": {"gemini-2.5-pro": {"output": -1.0}}},
            ):
                code, resp = api_call("POST", "/api/models-pricing/config", bad_payload)
                self.assertEqual(code, 400, f"Expected 400 for {bad_payload}, got {code}: {resp}")

            # 3. Valid POST /api/models-pricing/config -> 200, persists manualOverride & preserves disk oauthClientOwners
            code, resp = api_call(
                "POST",
                "/api/models-pricing/config",
                {
                    "billingSettings": {"vertexBillingCreditDiscountPct": 12.5, "regionalMultiplierDefault": 1.15},
                    "models": {"gemini-2.5-pro": {"input": 1.5, "output": 11.0, "unknownExtraField": "ignored"}},
                },
            )
            self.assertEqual(code, 200)
            self.assertAlmostEqual(resp["config"]["billingSettings"]["vertexBillingCreditDiscountPct"], 12.5, places=2)
            self.assertEqual(resp["config"]["models"]["gemini-2.5-pro"]["source"], "MANUAL")
            self.assertAlmostEqual(resp["config"]["models"]["gemini-2.5-pro"]["manualOverride"]["input"], 1.5, places=4)
            self.assertNotIn("unknownExtraField", resp["config"]["models"]["gemini-2.5-pro"])
            self.assertNotIn("oauthClientOwners", resp["config"])
            # Disk still has oauthClientOwners untouched
            self.assertIn("123-client", self.ns["load_models_pricing_config"]().get("oauthClientOwners", {}))

            # 3b. Verify clearManualOverride restores source and removes manualOverride
            code_clr, resp_clr = api_call(
                "POST",
                "/api/models-pricing/config",
                {
                    "models": {
                        "gemini-2.5-pro": {
                            "clearManualOverride": True,
                        }
                    }
                },
            )
            self.assertEqual(code_clr, 200)
            self.assertNotIn("manualOverride", resp_clr["config"]["models"]["gemini-2.5-pro"])
            self.assertNotEqual(resp_clr["config"]["models"]["gemini-2.5-pro"]["source"], "MANUAL")

            # 4. Concurrent POST /api/models-pricing/sync when lock is held -> 409
            self.ns["MODELS_PRICING_SYNC_LOCK"].acquire()
            try:
                code_409, _ = api_call("POST", "/api/models-pricing/sync", {})
                self.assertEqual(code_409, 409)
            finally:
                self.ns["MODELS_PRICING_SYNC_LOCK"].release()
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
