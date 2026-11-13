"""Tests for the 3-path Cloud Billing calibration engine, HTTP endpoints, demo isolation and top-bar warning UI."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import demo_test_support as sup
import server

ROOT = Path(server.__file__).resolve().parent
NODE = shutil.which("node")


def _bq_schema_and_rows():
    schema = {
        "fields": [
            {"name": "service_id"},
            {"name": "service_desc"},
            {"name": "sku_id"},
            {"name": "sku_desc"},
            {"name": "currency"},
            {"name": "usage_amount"},
            {"name": "list_cost"},
            {"name": "gross_cost"},
            {"name": "credits_sum"},
        ]
    }
    raw_rows = [
        ("C7E2-9256-1C43", "Vertex AI", "SKU-1", "Gemini 9 Test Global Text Input - Online Predictions", "EUR", "10000000", "20.0", "20.0", "-8.0"),
        ("C7E2-9256-1C43", "Vertex AI", "SKU-2", "Gemini 9 Test Regional Text Input - Online Predictions", "EUR", "10000000", "24.0", "24.0", "-9.6"),
        ("C7E2-9256-1C43", "Vertex AI", "SKU-3", "Gemini 9 Test Global Text Output - Online Predictions", "EUR", "1000000", "10.0", "10.0", "-4.0"),
        ("C7E2-9256-1C43", "Vertex AI", "SKU-4", "Gemini 9 Test Regional Text Output - Online Predictions", "EUR", "1000000", "12.0", "12.0", "-4.8"),
        ("C7E2-9256-1C43", "Vertex AI", "SKU-5", "Gemini 9 Test Regional Text Input Caching Online", "EUR", "50000000", "12.0", "12.0", "-4.8"),
        ("AEFD-7695-64FA", "Gemini API", "SKU-6", "Generate content input token count gemini 9 test text", "EUR", "10000000", "25.0", "25.0", "-2.5"),
        ("AEFD-7695-64FA", "Gemini API", "SKU-7", "Generate content cached input token count gemini 9 test text", "EUR", "90000000", "9.0", "9.0", "-0.9"),
    ]
    rows = [{"f": [{"v": col} for col in r]} for r in raw_rows]
    return {"jobComplete": True, "schema": schema, "rows": rows}


class IsolatedPricingCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name
        self.pricing_file = os.path.join(self.tmp_dir, "models_pricing_config.json")
        self._patches = [
            mock.patch.object(server, "DATA_DIR", self.tmp_dir),
            mock.patch.object(server, "MODELS_PRICING_FILE", self.pricing_file),
            mock.patch.dict(server._MODELS_PRICING_MEM_CACHE, {"mtime": 0.0, "data": None}, clear=True),
            mock.patch.dict(server._BQ_CHECKED_DATE_BY_ACCOUNT, {}, clear=True),
        ]
        for p in self._patches:
            p.start()
        cfg = server._build_default_models_pricing_config()
        cfg["models"]["gemini-9-test"] = {
            "modelId": "gemini-9-test",
            "displayName": "gemini-9-test",
            "publisher": "google",
            "input": 2.5,
            "output": 12.5,
            "thinking": 12.5,
            "cache_read_input": 0.25,
            "regional_input": 2.75,
            "regional_output": 13.75,
            "regional_thinking": 13.75,
            "regional_cache_read_input": 0.275,
            "source": "GCP_BILLING_API:C7E2-9256-1C43",
            "lastSkuIdGlobal": "SKU-1",
            "lastSkuIdRegional": "SKU-2",
            "updatedAt": "2026-11-01T00:00:00+00:00",
        }
        server.save_models_pricing_config(cfg)

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class TestBillingCalibrationEngine(IsolatedPricingCase):
    def test_parse_bigquery_table_ref_strict_validation(self) -> None:
        self.assertEqual(
            server.parse_bigquery_table_ref("acme-billing-hub.billing_export.gcp_billing_export_v1_0123AB_4567CD"),
            ("acme-billing-hub", "billing_export", "gcp_billing_export_v1_0123AB_4567CD"),
        )
        self.assertEqual(
            server.parse_bigquery_table_ref("`acme-billing-hub:billing_export.gcp_billing_export_resource_v1_0123AB`"),
            ("acme-billing-hub", "billing_export", "gcp_billing_export_resource_v1_0123AB"),
        )
        for bad in (
            "",
            "only_two.parts",
            "UPPERCASE_PROJ.ds.tbl",
            "acme-billing-hub.ds.tbl; DROP TABLE x",
            "acme-billing-hub.ds.tbl--comment",
            "a.b.c.d",
        ):
            self.assertIsNone(server.parse_bigquery_table_ref(bad), bad)

    def test_bigquery_auto_discovery_and_job_project_fallback(self) -> None:
        def fake_get(url, token, timeout=12, user_project=None):
            if "/projects/acme-billing-hub/datasets?" in url:
                return 200, {"datasets": [{"datasetReference": {"projectId": "acme-billing-hub", "datasetId": "billing_export"}}]}
            if "/projects/acme-billing-hub/datasets/billing_export/tables?" in url:
                return 200, {"tables": [{"tableReference": {"projectId": "acme-billing-hub", "datasetId": "billing_export", "tableId": "gcp_billing_export_v1_010203_ABCDEF"}}]}
            return 200, {}

        post_calls = []

        def fake_post(url, token, payload, timeout=15, user_project=None):
            post_calls.append((url, payload.get("query", "")))
            if "/projects/acme-billing-hub/queries" in url:
                return 403, {"error": {"message": "Access Denied: Project acme-billing-hub: User does not have bigquery.jobs.create permission", "errors": [{"reason": "accessDenied"}]}}
            if "/projects/acme-ml-lab/queries" in url:
                # Simulate _PARTITIONTIME failing first so usage_start_time fallback is also exercised
                if "_PARTITIONTIME" in payload.get("query", ""):
                    return 400, {"error": {"message": "Unrecognized name: _PARTITIONTIME", "errors": [{"reason": "invalidQuery"}]}}
                return 200, _bq_schema_and_rows()
            return 404, {"error": {"message": "Not found"}}

        raw_projects = [
            {"projectId": "acme-billing-hub", "name": "Billing Hub"},
            {"projectId": "acme-ml-lab", "name": "ML Lab"},
        ]
        with mock.patch.object(server, "gcp_api_get", side_effect=fake_get), mock.patch.object(server, "gcp_api_post", side_effect=fake_post):
            res = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                raw_projects=raw_projects,
                quota_candidates=["acme-ml-lab"],
                auto_apply=True,
                force_apply=False,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["bigqueryStatus"], "OK")
        self.assertTrue(res["applied"])
        cfg = res["config"]
        cal = cfg["billingCalibration"]
        bs = cfg["billingSettings"]
        self.assertEqual(cal["activeSource"], "BIGQUERY_EXPORT")
        self.assertEqual(cal["discoveredTable"], "acme-billing-hub.billing_export.gcp_billing_export_v1_010203_ABCDEF")
        self.assertEqual(cal["jobProject"], "acme-ml-lab")
        self.assertEqual(bs["vertexBillingCreditDiscountPct"], 40.0)
        self.assertEqual(bs["geminiApiBillingCreditDiscountPct"], 10.0)
        self.assertAlmostEqual(bs["vertexImplicitCacheHitRatioPct"], 71.4, places=1)
        self.assertEqual(bs["geminiApiImplicitCacheHitRatioPct"], 90.0)
        self.assertEqual(bs["regionalMultiplierDefault"], 1.2)
        self.assertEqual(cfg["models"]["gemini-9-test"]["geminiApiCacheHitRatioPct"], 90.0)
        self.assertGreaterEqual(len(post_calls), 3)

    def test_bigquery_permission_denied_403_vs_api_disabled(self) -> None:
        def fake_get_disabled_only(url, token, timeout=12, user_project=None):
            return 403, {
                "error": {
                    "message": "BigQuery API has not been used in project acme-ml-lab before or it is disabled.",
                    "errors": [{"reason": "accessNotConfigured"}],
                }
            }

        with mock.patch.object(server, "gcp_api_get", side_effect=fake_get_disabled_only):
            res_disabled = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                raw_projects=[{"projectId": "acme-ml-lab"}],
                quota_candidates=["acme-ml-lab"],
            )
        self.assertEqual(res_disabled["bigqueryStatus"], "NOT_FOUND")

        def fake_get_iam_denied(url, token, timeout=12, user_project=None):
            if "/projects/acme-billing-hub/datasets?" in url:
                return 200, {"datasets": [{"datasetReference": {"projectId": "acme-billing-hub", "datasetId": "billing_export"}}]}
            if "/projects/acme-billing-hub/datasets/billing_export/tables?" in url:
                return 403, {
                    "error": {
                        "message": "Access Denied: Dataset acme-billing-hub:billing_export: Permission bigquery.tables.list denied.",
                        "errors": [{"reason": "accessDenied"}],
                    }
                }
            return 200, {}

        with mock.patch.object(server, "gcp_api_get", side_effect=fake_get_iam_denied):
            res_denied = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                raw_projects=[{"projectId": "acme-billing-hub"}],
                quota_candidates=["acme-billing-hub"],
            )
        self.assertEqual(res_denied["bigqueryStatus"], "PERMISSION_DENIED")
        cal = res_denied["config"]["billingCalibration"]
        self.assertIn("acme-billing-hub.billing_export", cal["deniedTargets"])
        self.assertIn("403", cal["bigqueryMessage"])

    def test_manual_override_respected_until_forced_or_reset(self) -> None:
        ok, err, cfg = server.validate_and_apply_models_pricing_update({
            "billingSettings": {"vertexBillingCreditDiscountPct": 25.0}
        })
        self.assertTrue(ok, err)
        self.assertEqual(cfg["billingCalibration"]["activeSource"], "MANUAL")
        self.assertTrue(cfg["billingCalibration"]["manualOverride"])

        def fake_post(url, token, payload, timeout=15, user_project=None):
            return 200, _bq_schema_and_rows()

        with mock.patch.object(server, "gcp_api_post", side_effect=fake_post):
            # Auto-scan (force_apply=False) verifies BigQuery OK but preserves manual discount
            res_auto = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                explicit_table="acme-billing-hub.billing_export.gcp_billing_export_v1_010203",
                quota_candidates=["acme-ml-lab"],
                auto_apply=True,
                force_apply=False,
            )
            self.assertEqual(res_auto["bigqueryStatus"], "OK")
            self.assertFalse(res_auto["applied"])
            self.assertEqual(res_auto["config"]["billingSettings"]["vertexBillingCreditDiscountPct"], 25.0)
            self.assertEqual(res_auto["config"]["billingCalibration"]["activeSource"], "MANUAL")

            # Explicit button click (force_apply=True) applies BigQuery calibration and clears manualOverride
            res_forced = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                explicit_table="acme-billing-hub.billing_export.gcp_billing_export_v1_010203",
                quota_candidates=["acme-ml-lab"],
                auto_apply=True,
                force_apply=True,
            )
            self.assertTrue(res_forced["applied"])
            self.assertEqual(res_forced["config"]["billingSettings"]["vertexBillingCreditDiscountPct"], 40.0)
            self.assertEqual(res_forced["config"]["billingCalibration"]["activeSource"], "BIGQUERY_EXPORT")
            self.assertFalse(res_forced["config"]["billingCalibration"]["manualOverride"])

        # Reset to defaults restores DEFAULT_LIST_PRICES
        ok_rst, _, cfg_rst = server.validate_and_apply_models_pricing_update({
            "billingSettings": {"vertexBillingCreditDiscountPct": 0.0},
            "resetBillingSettings": True,
        })
        self.assertTrue(ok_rst)
        self.assertEqual(cfg_rst["billingCalibration"]["activeSource"], "DEFAULT_LIST_PRICES")
        self.assertFalse(cfg_rst["billingCalibration"]["manualOverride"])

    def test_csv_upload_italian_and_english_locales(self) -> None:
        it_csv = "\n".join([
            "Descrizione servizio;ID servizio;Descrizione SKU;Quantità di utilizzo;Costo di listino;Altri risparmi",
            'Vertex AI;C7E2-9256-1C43;Gemini 9 Test Global Text Input - Online Predictions;"10.000.000";"20,00";"-8,00"',
            'Vertex AI;C7E2-9256-1C43;Gemini 9 Test Regional Text Input - Online Predictions;"10.000.000";"24,00";"-9,60"',
            'Vertex AI;C7E2-9256-1C43;Gemini 9 Test Regional Text Input Caching Online;"50.000.000";"12,00";"-4,80"',
            'Gemini API;AEFD-7695-64FA;Generate content input token count gemini 9 test text;"10.000.000";"25,00";"-2,50"',
            'Gemini API;AEFD-7695-64FA;Generate content cached input token count gemini 9 test text;"90.000.000";"9,00";"-0,90"',
        ])
        ok_it, err_it, cfg_it = server.calibrate_from_csv_uploads([{"name": "report_it.csv", "content": it_csv}])
        self.assertTrue(ok_it, err_it)
        self.assertEqual(cfg_it["billingCalibration"]["activeSource"], "CSV_UPLOAD")
        self.assertEqual(cfg_it["billingCalibration"]["csvFiles"], ["report_it.csv"])
        self.assertEqual(cfg_it["billingSettings"]["vertexBillingCreditDiscountPct"], 40.0)
        self.assertEqual(cfg_it["billingSettings"]["geminiApiBillingCreditDiscountPct"], 10.0)
        self.assertEqual(cfg_it["billingSettings"]["regionalMultiplierDefault"], 1.2)
        self.assertEqual(cfg_it["models"]["gemini-9-test"]["geminiApiCacheHitRatioPct"], 90.0)
        # Ensure raw CSV was never persisted to disk
        self.assertEqual(os.listdir(self.tmp_dir), ["models_pricing_config.json"])

        en_csv = "\n".join([
            "Service description,Service ID,SKU description,Usage amount,Cost at list,Negotiated savings,Other savings",
            'Vertex AI,C7E2-9256-1C43,Gemini 9 Test Global Text Input - Online Predictions,"10,000,000","20.00","-5.00","-3.00"',
            'Gemini API,AEFD-7695-64FA,Generate content input token count gemini 9 test text,"10,000,000","25.00","0.00","-2.50"',
            'Gemini API,AEFD-7695-64FA,Generate content cached input token count gemini 9 test text,"90,000,000","9.00","0.00","-0.90"',
        ])
        ok_en, err_en, cfg_en = server.calibrate_from_csv_uploads([{"name": "report_en.csv", "content": en_csv}])
        self.assertTrue(ok_en, err_en)
        self.assertEqual(cfg_en["billingSettings"]["vertexBillingCreditDiscountPct"], 40.0)
        self.assertEqual(cfg_en["billingSettings"]["geminiApiBillingCreditDiscountPct"], 10.0)

        # When BigQuery export is connected (OK) with 0 AI rows yet, existing CSV discount is preserved and applied=False
        def fake_post_empty(url, token, payload, timeout=15, user_project=None):
            return 200, {"jobComplete": True, "schema": {"fields": []}, "rows": []}

        with mock.patch.object(server, "gcp_api_post", side_effect=fake_post_empty):
            res_empty = server.discover_and_calibrate_bigquery_billing(
                token="fake-token",
                active_acc="analyst@example.com",
                explicit_table="acme-billing-hub.billing_export.gcp_billing_export_v1_010203",
                quota_candidates=["acme-ml-lab"],
                auto_apply=True,
                force_apply=True,
            )
        self.assertEqual(res_empty["bigqueryStatus"], "OK")
        self.assertFalse(res_empty["applied"])
        self.assertEqual(res_empty["config"]["billingCalibration"]["activeSource"], "CSV_UPLOAD")
        self.assertEqual(res_empty["config"]["billingSettings"]["vertexBillingCreditDiscountPct"], 40.0)

    def test_unauthenticated_calibration_endpoints_return_401(self) -> None:
        import http.client
        import threading

        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.MonitorHandler)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            for path in ("/api/models-pricing/calibrate-bigquery", "/api/models-pricing/calibrate-csv"):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("POST", path, body="{}", headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})
                resp = conn.getresponse()
                raw = json.loads(resp.read().decode("utf-8"))
                conn.close()
                self.assertEqual(resp.status, 401, path)
                self.assertTrue(raw.get("needsLogin"), path)
        finally:
            srv.shutdown()
            srv.server_close()


class TestBigQueryAutoSyncIsOptIn(IsolatedPricingCase):
    """Scans and syncs never run a (billable) BigQuery query job unless the user turned the option on."""

    def test_default_is_off_and_no_network_call_is_made(self) -> None:
        self.assertIs(server.load_models_pricing_config()["billingCalibration"]["bigqueryAutoSync"], False)
        with mock.patch.object(server, "gcp_api_get") as g, mock.patch.object(server, "gcp_api_post") as p:
            res = server.maybe_auto_calibrate_bigquery_for_account("fake-token", "analyst@example.com", force_check=True)
        self.assertIsNone(res)
        g.assert_not_called()
        p.assert_not_called()

    def test_enabled_option_runs_the_discovery(self) -> None:
        ok, err, _ = server.validate_and_apply_models_pricing_update({"bigqueryAutoSync": True})
        self.assertTrue(ok, err)
        self.assertIs(server.load_models_pricing_config()["billingCalibration"]["bigqueryAutoSync"], True)
        with mock.patch.object(server, "discover_and_calibrate_bigquery_billing", return_value={"config": {}}) as d:
            server.maybe_auto_calibrate_bigquery_for_account("fake-token", "analyst@example.com", force_check=True)
        d.assert_called_once()

    def test_turning_it_off_again_and_invalid_values(self) -> None:
        server.validate_and_apply_models_pricing_update({"bigqueryAutoSync": True})
        ok, err, _ = server.validate_and_apply_models_pricing_update({"bigqueryAutoSync": False})
        self.assertTrue(ok, err)
        self.assertIs(server.load_models_pricing_config()["billingCalibration"]["bigqueryAutoSync"], False)
        for bad in ("yes", 1, None):
            ok, _err, _ = server.validate_and_apply_models_pricing_update({"bigqueryAutoSync": bad})
            self.assertFalse(ok, f"{bad!r} must be rejected")

    def test_ui_has_the_switch_with_the_cost_warning(self) -> None:
        view = open(os.path.join(os.path.dirname(__file__), "..", "frontend", "js", "views_pricing.js"), encoding="utf-8").read()
        self.assertIn("pricing-bq-auto-sync", view)
        self.assertIn("may bill you", view)


class TestDemoCalibrationEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_before = sup.snapshot_dir(sup.REPO_DATA_DIR)
        cls.ns = sup.load_demo_namespace()
        cls.srv = sup.InProcessServer(cls.ns)
        cls.client = sup.Client(cls.srv.port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.close()
        sup.cleanup_namespace(cls.ns)

    def test_bigquery_calibration_blocked_and_csv_upload_isolated_in_demo(self) -> None:
        st_code, _, _ = self.client.get("/api/auth/status")
        self.assertEqual(st_code, 200)

        code_bq, _, body_bq = self.client.post("/api/models-pricing/calibrate-bigquery", {})
        self.assertEqual(code_bq, 403)
        self.assertTrue(body_bq.get("demo"))

        csv_text = "\n".join([
            "Service description,Service ID,SKU description,Usage amount,Cost at list,Other savings",
            'Vertex AI,C7E2-9256-1C43,Gemini 2.5 Flash Global Text Input - Online Predictions,"10,000,000","30.00","-6.00"',
        ])
        code_csv, _, body_csv = self.client.post(
            "/api/models-pricing/calibrate-csv",
            {"files": [{"name": "demo_sample.csv", "content": csv_text}]},
        )
        self.assertEqual(code_csv, 200, body_csv)
        self.assertTrue(body_csv["success"])
        self.assertEqual(body_csv["config"]["billingCalibration"]["activeSource"], "CSV_UPLOAD")
        self.assertEqual(body_csv["config"]["billingSettings"]["vertexBillingCreditDiscountPct"], 20.0)

        scan_code, _, scan_body = self.client.get("/api/scan?days=30&cached=1")
        self.assertEqual(scan_code, 200)
        self.assertEqual(scan_body["billingCalibration"]["activeSource"], "CSV_UPLOAD")
        self.assertEqual(sup.snapshot_dir(sup.REPO_DATA_DIR), self.repo_before)


@unittest.skipUnless(NODE, "node not available")
class TestHeaderBillingWarningUiState(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "frontend" / "js" / "core_and_auth.js").read_text(encoding="utf-8")
        m = re.search(r"// JT-BILLING-WARNING-STATE-BEGIN.*?\n(.*?)// JT-BILLING-WARNING-STATE-END", src, re.S)
        assert m, "JT-BILLING-WARNING-STATE markers missing"
        cls.fn_src = m.group(1)

    def eval_state(self, cal, is_logged_in: bool) -> dict:
        js = (
            "const f = new Function(process.argv[3] + '; return computeHeaderBillingWarningState;')();"
            "console.log(JSON.stringify(f(JSON.parse(process.argv[1]), JSON.parse(process.argv[2]))));"
        )
        res = subprocess.run(  # noqa: S603
            [NODE, "-e", js, json.dumps(cal), json.dumps(is_logged_in), self.fn_src],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(res.stdout.strip().splitlines()[-1])

    def test_hidden_when_logged_out_or_bigquery_ok(self) -> None:
        self.assertFalse(self.eval_state({"bigqueryStatus": "NOT_FOUND", "activeSource": "DEFAULT_LIST_PRICES"}, False)["visible"])
        self.assertFalse(self.eval_state({"bigqueryStatus": "OK", "activeSource": "BIGQUERY_EXPORT"}, True)["visible"])
        self.assertFalse(self.eval_state({"bigqueryStatus": "OK", "activeSource": "MANUAL"}, True)["visible"])

    def test_remains_visible_until_bigquery_is_ok_even_with_csv_or_manual(self) -> None:
        s403 = self.eval_state({"bigqueryStatus": "PERMISSION_DENIED", "activeSource": "CSV_UPLOAD"}, True)
        self.assertTrue(s403["visible"])
        self.assertEqual(s403["severity"], "danger")
        self.assertEqual(s403["label"], "Billing 403")
        self.assertIn("403", s403["tip"])
        self.assertIn("Uploaded Billing CSV", s403["tip"])

        s_nf = self.eval_state({"bigqueryStatus": "NOT_FOUND", "activeSource": "MANUAL"}, True)
        self.assertTrue(s_nf["visible"])
        self.assertEqual(s_nf["severity"], "warning")
        self.assertEqual(s_nf["label"], "Billing setup")
        self.assertIn("Manual parameters", s_nf["tip"])


if __name__ == "__main__":
    unittest.main()
