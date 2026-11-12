"""Demo mode on a real handler: isolated data directory, no network, blocked live actions, working demo views."""

import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import demo_test_support as sup

ROOT = sup.ROOT


class DemoServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_before = sup.snapshot_dir(sup.REPO_DATA_DIR)
        cls.ns = sup.load_demo_namespace()
        cls.srv = sup.InProcessServer(cls.ns)
        cls.client = sup.Client(cls.srv.port)
        cls.external_connects = []
        cls._real_connect = socket.socket.connect

        def guarded_connect(sock, address, *a, **kw):
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
                cls.external_connects.append(address)
                raise AssertionError(f"demo mode tried to reach {address}")
            return cls._real_connect(sock, address, *a, **kw)

        cls._patch = mock.patch.object(socket.socket, "connect", guarded_connect)
        cls._patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        cls.srv.close()
        sup.cleanup_namespace(cls.ns)

    def login(self):
        status, _, body = self.client.get("/api/auth/status")
        self.assertEqual(status, 200)
        return body


class TestIsolation(DemoServerCase):
    def test_data_dir_is_a_temp_folder_and_not_the_repo_data(self):
        data_dir = Path(self.ns["DATA_DIR"]).resolve()
        self.assertNotEqual(data_dir, sup.REPO_DATA_DIR.resolve())
        self.assertEqual(self.ns["DATA_DIR"], self.ns["DEMO_DATA_DIR"])
        self.assertIn(Path(tempfile.gettempdir()).resolve(), data_dir.parents)
        self.assertNotIn(ROOT.resolve(), data_dir.parents)
        for name in ("TOKENS_FILE", "CACHE_FILE", "BUDGETS_FILE", "MODELS_PRICING_FILE", "SYNC_REGISTRY_FILE", "INFRA_CATALOG_CACHE_FILE"):
            self.assertTrue(str(Path(self.ns[name]).resolve()).startswith(str(data_dir)), name)
        self.assertEqual(self.ns["get_account_cache_path"]("demo.admin@example.com", 30), str(data_dir / "scan_cache_v9_demo_admin_example_com_30d.json"))

    def test_demo_data_is_in_the_temp_dir(self):
        names = set(os.listdir(self.ns["DATA_DIR"]))
        for expected in ("oauth_tokens.json", "projects_sync_registry.json", "models_pricing_config.json", "budgets_config.json",
                         "scan_cache_v9_demo_admin_example_com_30d.json", "scan_cache_v9_demo_admin_example_com_90d.json"):
            self.assertIn(expected, names)

    def test_no_file_created_or_modified_in_repo_data(self):
        self.login()
        for path in ("/api/scan?days=30&cached=1", "/api/scan?days=7&cached=1", "/api/scan?days=14&cached=1&preset=today", "/api/models-pricing",
                     "/api/projects-sync", "/api/budgets", "/api/scan?days=30&cached=0", "/api/gemini-enterprise/inspect?projectId=a&resourceId=b"):
            self.client.get(path)
        for path in ("/api/budgets", "/api/projects-sync/toggle", "/api/models-pricing/config", "/api/data/purge", "/api/auth/logout",
                     "/api/projects-sync/force-scan", "/api/project-scan", "/api/models-pricing/sync", "/api/killswitch/toggle"):
            self.client.post(path, {"projectId": "acme-ml-lab", "budgetUsd": 7, "action": "apply_auto_rule", "billingSettings": {"infraSavingsPct": 5}})
        self.assertEqual(sup.snapshot_dir(sup.REPO_DATA_DIR), self.repo_before)

    def test_the_demo_login_has_no_real_credential(self):
        store = json.loads((Path(self.ns["TOKENS_FILE"])).read_text(encoding="utf-8"))
        acc = store["accounts"]["demo.admin@example.com"]
        self.assertIsNone(acc["refresh_token"])
        self.assertEqual(acc["access_token"], "demo-access-token-not-valid")
        self.assertEqual(list(store["accounts"]), ["demo.admin@example.com"])
        self.assertEqual(acc["login_date"], self.ns["get_today_date_str"]())
        self.assertGreater(acc["daily_expires_at"], time.time())


class TestNoNetwork(DemoServerCase):
    def test_gcp_helpers_raise_a_clear_error(self):
        err = self.ns["DemoModeError"]
        with self.assertRaises(err) as cm:
            self.ns["gcp_api_get"]("https://cloudresourcemanager.googleapis.com/v1/projects", "token")
        self.assertIn("demo mode", str(cm.exception))
        with self.assertRaises(err):
            self.ns["gcp_api_post"]("https://logging.googleapis.com/v2/entries:list", "token", {"x": 1})
        with self.assertRaises(err):
            self.ns["demo_block_network"]("Anything")

    def test_the_http_pool_refuses_every_request(self):
        with self.assertRaises(self.ns["DemoModeError"]):
            self.ns["HTTP_POOL"].request("GET", "http://127.0.0.1:9/")
        with self.assertRaises(self.ns["DemoModeError"]):
            self.ns["HTTP_POOL"].request("POST", "https://oauth2.googleapis.com/token", body=b"x")

    def test_token_refresh_returns_a_placeholder_without_network(self):
        acc = {"login_date": self.ns["get_today_date_str"](), "daily_expires_at": time.time() + 600, "session_id": "s",
               "access_token": None, "refresh_token": "would-be-real", "needs_reauth": True}
        with mock.patch("urllib3.PoolManager.urlopen", side_effect=AssertionError("network")):
            ok, token = self.ns["refresh_access_token_for_account"](acc)
        self.assertTrue(ok)
        self.assertEqual(token, "demo-access-token-not-valid")
        stale = dict(acc, login_date="2001-01-01")
        self.assertFalse(self.ns["refresh_access_token_for_account"](stale)[0], "the daily session policy still applies")

    def test_infra_catalog_is_not_downloaded(self):
        self.assertIsNone(self.ns["get_infra_catalog"]("token"))

    def test_oauth_routes_redirect_home(self):
        for path in ("/auth/google/start", "/auth/google/start?login_hint=a@example.com", "/oauth2callback?code=abc&state=x",
                     "/auth/google/callback?error=denied", "/oauth2callback"):
            status, resp, _ = self.client.get(path)
            self.assertEqual(status, 302, path)
            self.assertEqual(resp.getheader("Location"), "/", path)
        self.assertEqual(self.external_connects, [])

    def test_no_external_connection_was_attempted(self):
        self.login()
        for path in ("/api/scan?days=30&cached=1", "/api/models-pricing", "/api/scan?days=30&cached=0&async=1", "/auth/google/start"):
            self.client.get(path)
        self.client.post("/api/models-pricing/sync", {})
        self.client.post("/api/projects-sync/force-scan", {"projectId": "acme-ml-lab"})
        self.assertEqual(self.external_connects, [])


class TestLiveActionsRefused(DemoServerCase):
    def test_live_posts_are_refused(self):
        self.login()
        for path in ("/api/projects-sync/force-scan", "/api/project-scan", "/api/models-pricing/sync"):
            status, _, body = self.client.post(path, {"projectId": "acme-ml-lab", "days": 30})
            self.assertEqual(status, 403, path)
            self.assertFalse(body["success"])
            self.assertTrue(body["demo"])
            self.assertIn("disabled in demo mode", body["error"])

    def test_live_scan_get_and_resource_inspection_are_refused(self):
        self.login()
        for path in ("/api/scan?days=30&cached=0", "/api/scan?days=30", "/api/scan?days=30&cached=0&mode=full&async=1",
                     "/api/gemini-enterprise/inspect?projectId=acme-agentspace&resourceId=x&location=eu"):
            status, _, body = self.client.get(path)
            self.assertEqual(status, 403, path)
            self.assertIn("disabled in demo mode", body["error"])

    def test_refused_even_without_a_session(self):
        fresh = sup.Client(self.srv.port)
        for path in ("/api/projects-sync/force-scan", "/api/models-pricing/sync", "/api/data/purge", "/api/auth/logout"):
            self.assertEqual(fresh.post(path, {"projectId": "x"})[0], 403, path)

    def test_purge_and_logout_are_disabled_and_keep_the_demo_data(self):
        self.login()
        before = set(os.listdir(self.ns["DATA_DIR"]))
        self.assertEqual(self.client.post("/api/data/purge", {})[0], 403)
        self.assertEqual(self.client.post("/api/auth/logout", {})[0], 403)
        self.assertEqual(set(os.listdir(self.ns["DATA_DIR"])), before)
        self.assertTrue(self.login()["auth"]["tokenValid"])

    def test_foreign_host_header_is_refused(self):
        status, _, _ = sup.Client(self.srv.port).get("/api/auth/status", headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)


class TestDemoViewsWork(DemoServerCase):
    def test_auth_status_fields_and_valid_login(self):
        body = self.login()
        self.assertIs(body["demo"], True)
        self.assertIs(body["oauthConfigured"], False)
        self.assertTrue(body["success"])
        auth = body["auth"]
        self.assertTrue(auth["tokenValid"])
        self.assertFalse(auth["needsLogin"])
        self.assertEqual(auth["activeAccount"], "demo.admin@example.com")
        self.assertEqual(auth["loginDate"], self.ns["get_today_date_str"]())
        self.assertNotIn("accessToken", auth)
        self.assertEqual(set(body), {"success", "auth", "scanProgress", "demo", "oauthConfigured"})

    def test_the_session_survives_with_the_cookie_only(self):
        self.login()
        other = sup.Client(self.srv.port)
        other.cookies = dict(self.client.cookies)
        body = other.get("/api/auth/status")[2]
        self.assertTrue(body["auth"]["tokenValid"])
        self.assertEqual(set(other.cookies), set(self.client.cookies))

    def test_a_stale_session_is_replaced_by_the_demo_login(self):
        fresh = sup.Client(self.srv.port)
        fresh.cookies = {f"gcp_monitor_account_{self.ns['PORT']}": "someone%40example.com", f"gcp_monitor_sid_{self.ns['PORT']}": "stale"}
        body = fresh.get("/api/auth/status")[2]
        self.assertTrue(body["auth"]["tokenValid"])
        self.assertEqual(body["auth"]["activeAccount"], "demo.admin@example.com")

    def test_cached_scan_returns_the_demo_payload(self):
        self.login()
        status, _, data = self.client.get("/api/scan?days=30&cached=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertTrue(data["fromCache"])
        self.assertGreaterEqual(len(data["projects"]), 12)
        self.assertEqual({p["projectId"] for p in data["projects"] if p["projectId"].startswith("acme-")}, {p["projectId"] for p in data["projects"]})
        self.assertGreater(data["summary"]["totalBillCostUsd"], 100)
        self.assertEqual(data["auth"]["activeAccount"], "demo.admin@example.com")
        self.assertIn("syncMeta", data["projects"][0])
        self.assertEqual(data["sync"]["account"], "demo.admin@example.com")
        self.assertEqual(data["sync"]["totalSynchronized"], len(data["projects"]))
        self.assertIn("totalTcoUsd", data["summary"], "the app's own enrichment ran on the demo payload")

    def test_other_windows_are_sliced_from_the_cache(self):
        self.login()
        for days in (1, 7, 14, 90):
            status, _, data = self.client.get(f"/api/scan?days={days}&cached=1")
            self.assertEqual(status, 200, days)
            self.assertTrue(data["success"], days)
        status, _, data = self.client.get("/api/scan?cached=1&preset=today")
        self.assertEqual(status, 200)

    def test_scan_without_a_session_needs_login_first(self):
        status, _, body = sup.Client(self.srv.port).get("/api/scan?days=30&cached=1")
        self.assertEqual(status, 401)
        self.assertTrue(body["needsLogin"])

    def test_models_pricing_answers(self):
        self.login()
        status, _, body = self.client.get("/api/models-pricing")
        self.assertEqual(status, 200)
        self.assertTrue(body["success"])
        self.assertIn("models", body["config"])
        self.assertNotIn("oauthClientOwners", body["config"])
        self.assertEqual(body["modelsCount"], len(body["config"]["models"]))
        self.assertIsInstance(body["observed"], list)
        self.assertTrue(body["observed"], "the demo traffic uses models")
        self.assertIn("gemini-2.5-flash", body["config"]["models"])

    def test_budgets_and_sync_views_answer(self):
        self.login()
        self.assertEqual(self.client.get("/api/budgets")[0], 200)
        status, _, body = self.client.get("/api/projects-sync")
        self.assertEqual(status, 200)
        self.assertTrue(body["sync"]["projects"])

    def test_local_settings_still_work_inside_the_temp_dir(self):
        self.login()
        status, _, body = self.client.post("/api/budgets", {"projectId": "acme-ml-lab", "budgetUsd": 1234.0})
        self.assertEqual(status, 200)
        self.assertEqual(body["budgetUsd"], 1234.0)
        status, _, body = self.client.post("/api/projects-sync/toggle", {"projectId": "acme-research-sandbox", "scanEnabled": True})
        self.assertEqual(status, 200)

    def test_index_page_is_served(self):
        status, resp, _ = self.client.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", dict(resp.getheaders()))


if __name__ == "__main__":
    unittest.main()
