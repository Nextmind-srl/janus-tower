"""Content of the demo dataset as it is written at startup: invented only, English only, same shapes as the real backend."""

import importlib.util
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

import demo_test_support as sup

ROOT = sup.ROOT
sys.path.insert(0, str(ROOT / "tools"))
import find_italian  # noqa: E402

ACCOUNT = "demo.admin@example.com"
RESERVED_DOMAINS = ("example.com", "example.org", "contractor.example.net")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
SECRET_RES = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"ya29\.[0-9A-Za-z_\-]{10,}"),
    re.compile(r"GOCSPX-[0-9A-Za-z_\-]{10,}"),
    re.compile(r"-----BEGIN"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b1//[0-9A-Za-z_\-]{20,}"),
    re.compile(r"eyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9/._:@\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Z])[A-Za-z0-9_\-]{40,}(?![A-Za-z0-9/._:@\-])"),
]


def walk_strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def load_demo_data_module():
    spec = importlib.util.spec_from_file_location("janustower_demo_data_content", ROOT / "backend" / "demo_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DemoFilesCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = sup.load_demo_namespace()
        cls.data_dir = Path(cls.ns["DATA_DIR"])
        cls.files = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(cls.data_dir.glob("*.json"))}
        cls.cache30 = cls.files["scan_cache_v9_demo_admin_example_com_30d.json"]
        cls.demo = load_demo_data_module()

    @classmethod
    def tearDownClass(cls):
        sup.cleanup_namespace(cls.ns)


class TestNoItalianAndNoRealIdentifiers(DemoFilesCase):
    def test_generator_source_has_no_italian_text(self):
        self.assertEqual(find_italian.scan_file(ROOT / "backend" / "demo_data.py"), [])
        self.assertEqual(find_italian.scan_file(ROOT / "backend" / "demo_mode.py"), [])

    def test_no_italian_in_any_written_file(self):
        found = []
        for name, doc in self.files.items():
            for text in walk_strings(doc):
                if find_italian.italian_hits(text):
                    found.append(f"{name}: {text[:80]}")
        self.assertEqual(found, [])

    def test_texts_are_the_ones_the_real_backend_produces(self):
        everything = " ".join(walk_strings(self.cache30))
        for expected in ("Not Enabled", "Permission Denied (403)", "No Active Billing ($0)",
                         "Project Billing Status", "Actual Billing Account Invoices", "Enabled APIs & Services", "Registered MCP server"):
            self.assertIn(expected, everything)
        registry = " ".join(walk_strings(self.files["projects_sync_registry.json"]))
        self.assertIn("No active Billing ($0)", registry)
        self.assertIn("Missing IAM permissions (403)", registry)
        for old in ("Non Abilitato", "Senza Billing", "Permesso Negato", "verifica non completata", "Nessun dato"):
            self.assertNotIn(old, everything + registry)
        sync_text = " ".join(walk_strings(self.demo.build_demo_scan_payload(days=7, enrich=False)["sync"]))
        self.assertNotIn("Dati AI rilevati", sync_text)

    def test_emails_only_on_reserved_domains(self):
        seen = set()
        for name, doc in self.files.items():
            for text in walk_strings(doc):
                for m in EMAIL_RE.finditer(text):
                    email = m.group(0).lower().rstrip(".")
                    seen.add(email)
                    local, domain = email.split("@", 1)
                    ok_user = domain in RESERVED_DOMAINS
                    ok_sa = (domain.endswith(".iam.gserviceaccount.com") and domain.startswith("acme-")) or (
                        domain == "developer.gserviceaccount.com" and re.fullmatch(r"555\d{9}-compute", local))
                    self.assertTrue(ok_user or ok_sa, f"{name}: e-mail outside the reserved domains: {email}")
        self.assertIn(ACCOUNT, seen)

    def test_no_secret_like_strings_in_any_file(self):
        for name, doc in self.files.items():
            for text in walk_strings(doc):
                for rx in SECRET_RES:
                    self.assertIsNone(rx.search(text), f"{name}: secret-like string ({rx.pattern}): {text[:80]}")

    def test_no_real_google_cloud_identifiers(self):
        projects = self.cache30["projects"]
        for p in projects:
            self.assertTrue(p["projectId"].startswith("acme-"), p["projectId"])
            self.assertTrue(str(p["projectNumber"]).startswith("555"), p["projectNumber"])
            self.assertTrue(not p.get("billingAccountName") or "DEMO" in p["billingAccountName"], p.get("billingAccountName"))
            for sa in p["serviceAccounts"]:
                self.assertTrue(sa["uniqueId"].startswith("999"), sa["uniqueId"])
            for k in p["apiKeys"]:
                self.assertTrue(k["uid"].startswith("00000000-0000-4000-8000-"), k["uid"])
        blob = json.dumps(self.files)
        self.assertNotIn("gen-lang-client", blob)
        # every "projects/<number>" reference is one of the invented numbers
        for number in re.findall(r"projects/(\d{6,})", blob):
            self.assertTrue(number.startswith("555"), number)
        # a 12-digit number (the size of a real project number) is always one of the invented ranges
        for number in re.findall(r"(?<![\d.])(\d{12})(?![\d.])", blob):
            self.assertTrue(number.startswith(("555", "999", "000")), number)

    def test_login_store_has_no_real_token_and_only_the_demo_account(self):
        store = self.files["oauth_tokens.json"]
        self.assertEqual(list(store["accounts"]), [ACCOUNT])
        acc = store["accounts"][ACCOUNT]
        self.assertIsNone(acc["refresh_token"])
        self.assertEqual(acc["access_token"], "demo-access-token-not-valid")
        self.assertTrue(acc["session_id"])
        self.assertEqual(acc["login_date"], self.ns["get_today_date_str"]())

    def test_everything_uses_the_demo_account(self):
        self.assertEqual(self.cache30["auth"]["activeAccount"], ACCOUNT)
        self.assertEqual(list(self.files["projects_sync_registry.json"]["accounts"]), [ACCOUNT])


class TestShapesMatchTheRealBackend(DemoFilesCase):
    def test_sync_registry_entries_match_update_registry_entry_from_project(self):
        projects = self.cache30["projects"]
        scanned_at = "2026-11-04T06:00:00Z"
        real = {}
        for p in projects:
            self.ns["update_registry_entry_from_project"](real, p, scanned_at, is_new=p["projectId"] == "acme-hackathon-2026")
        demo = self.demo.build_demo_sync_registry_entries(projects, date(2026, 11, 4))
        self.assertEqual(set(real), set(demo))
        for pid, r in real.items():
            d = demo[pid]
            self.assertEqual(set(r), set(d), pid)
            skip = {"firstSeenAt", "lastScannedAt"}
            if pid == "acme-partner-portal":  # the demo pins one manual override, as a user would
                skip |= {"scanEnabled", "scanRule"}
            for key in r:
                if key not in skip:
                    self.assertEqual(r[key], d[key], f"{pid}.{key}")

    def test_sync_block_has_the_fields_of_build_sync_summary_for_account(self):
        registry = self.ns["load_sync_registry"]()
        real = self.ns["build_sync_summary_for_account"](ACCOUNT, registry)
        demo = self.cache30["sync"]
        self.assertEqual(set(demo) - set(real), {"lastScanMode", "scannedLiveCount", "reusedFromCacheCount"})
        self.assertEqual(set(real) - set(demo), set())
        for key in set(real) - {"projects", "lastSyncAt"}:
            self.assertEqual(real[key], demo[key], key)
        self.assertEqual([p["projectId"] for p in real["projects"]], [p["projectId"] for p in demo["projects"]])
        self.assertEqual(real["projects"], demo["projects"])
        # same set of keys the live scan adds to a project (see _attach_sync_meta_to_projects)
        meta = self.cache30["projects"][0]["syncMeta"]
        self.assertEqual(set(meta), {"scanEnabled", "hasAiData", "scanRule", "dataReason", "isNewProject", "lastScannedAt"})

    def test_sync_meta_matches_the_handler_helper(self):
        projects = [dict(p) for p in self.cache30["projects"]]
        for p in projects:
            p.pop("syncMeta", None)
        reg = self.ns["load_sync_registry"]()["accounts"][ACCOUNT]["projects"]
        self.ns["MonitorHandler"]._attach_sync_meta_to_projects(projects, reg)
        self.assertEqual({p["projectId"]: p["syncMeta"] for p in projects}, {p["projectId"]: p["syncMeta"] for p in self.cache30["projects"]})

    def test_permissions_match_build_project_permissions_summary(self):
        build = self.ns["build_project_permissions_summary"]
        all_perms = set(self.ns["PROJECT_IAM_PERMISSIONS_TO_CHECK"])
        def real_build(*args):
            out = build(*args)
            role = out["areas"]["billingCosts"]["requiredRole"]
            out["areas"]["billingCosts"]["requiredRole"] = role.replace("(su Billing Account)", "(on Billing Account)")  # English-only wording of the demo
            return out

        full_real = real_build(200, True, True, 200, all_perms, 200, 200, 3, 2, 4)
        self.assertEqual(self.demo._permissions(True, False, True, 3, 2, 4, True), full_real)
        partial_perms = all_perms - {"modelarmor.floorSettings.get", "modelarmor.templates.list"}
        partial_real = real_build(200, True, False, 200, partial_perms, 200, 200, 3, 2, 4)
        self.assertEqual(self.demo._permissions(False, True, False, 3, 2, 4, True), partial_real)
        denied_real = real_build(200, True, False, 403, {"resourcemanager.projects.get"}, 403, 403, 0, 0, 0)
        self.assertEqual(self.demo._denied_permissions(), denied_real)
        no_billing_real = real_build(200, False, False, 200, all_perms, 200, 200, 0, 0, 0)
        no_billing_demo = self.demo._permissions(True, False, False, 0, 0, 0, False)
        self.assertEqual(no_billing_demo["areas"]["billingInfo"], no_billing_real["areas"]["billingInfo"])

    def test_infra_lines_match__infra_line(self):
        real_line = self.ns["_infra_line"]
        cases = [
            ("sql", 96.4, ["finance-ledger-db", "finance-ledger-replica"], ["europe-west8"], "ok", ""),
            ("compute", 142.3, ["a", "b", "c", "d", "e"], ["europe-west4"], "partial", "ml-eval-gpu-vm: GPU price not found in catalog (europe-west4)"),
            ("sql", 0.0, ["support-tickets-db"], ["europe-west1"], "not_estimable", "support-tickets-db: unsupported tier db-f1-micro"),
            ("redis", 31.2, ["embeddings-cache"], ["europe-west8"], "ok", ""),
        ]
        for key, monthly, instances, locations, status, note in cases:
            demo = self.demo._infra_line_demo(key, monthly, instances, locations, status, note, days=30)
            service, sid, name, subtitle, icon = self.demo.INFRA_SERVICES[key]
            real = real_line(service, sid, name, subtitle, icon, instances=instances, locations=locations, gross=monthly, days=30, status=status, note=note)
            self.assertEqual(demo, real, key)
        self.assertEqual(self.demo.INFRA_SERVICES["sql"][1], self.ns["INFRA_CATALOG_SERVICE_IDS"]["sql"])

    def test_every_project_infra_line_has_the_real_fields(self):
        keys = None
        for p in self.cache30["projects"]:
            for line in p.get("infraServices", []):
                keys = keys or set(line)
                self.assertEqual(set(line), keys)
                self.assertIn(line["estimateStatus"], ("ok", "partial", "not_estimable"))
                self.assertIs(line["estimated"], True)
                self.assertIn("excludedNonAi", line)
                self.assertTrue(line["instances"], p["projectId"])
                self.assertTrue(line["details"])
        self.assertIsNotNone(keys)
        statuses = {line["estimateStatus"] for p in self.cache30["projects"] for line in p.get("infraServices", [])}
        self.assertEqual(statuses, {"ok", "partial", "not_estimable"})
        self.assertGreater(self.cache30["summary"]["infraCostUsd"], 0)

    def test_infra_costs_add_up(self):
        for p in self.cache30["projects"]:
            lines = p.get("infraServices", [])
            if not lines:
                continue
            total = round(sum(line["costUsd"] for line in lines), 2)
            self.assertAlmostEqual(total, p["infraCostUsd"] + p.get("excludedNonAiInfraCostUsd", 0.0), delta=0.02, msg=p["projectId"])

    def test_pricing_config_matches_the_backend_default_shape(self):
        real_default = self.ns["_build_default_models_pricing_config"]()
        standalone = self.demo.build_demo_models_pricing_config("2026-11-04")
        self.assertEqual(set(standalone), set(real_default))
        for section in ("billingSettings", "lastApiSync", "sourceServices"):
            self.assertEqual(set(standalone[section]), set(real_default[section]), section)
        one_real = next(iter(real_default["models"].values()))
        for model in standalone["models"].values():
            self.assertEqual(set(model), set(one_real))
        written = self.files["models_pricing_config.json"]
        self.assertEqual(set(written), set(real_default))
        for model in written["models"].values():
            self.assertEqual(set(model), set(one_real))
        # every model used by the demo traffic is priced exactly like the demo costs
        for mid, (p_in, p_out) in self.demo.MODEL_PRICES.items():
            self.assertEqual((written["models"][mid]["input"], written["models"][mid]["output"]), (p_in, p_out), mid)
        self.assertEqual(written["lastApiSync"]["totalConfiguredModels"], len(written["models"]))
        sanitized = self.ns["sanitize_models_pricing_config_for_http"](self.ns["load_models_pricing_config"]())
        self.assertNotIn("oauthClientOwners", sanitized)
        self.assertEqual(set(sanitized), set(real_default) - {"oauthClientOwners"})

    def test_observed_models_have_a_catalog_price_in_the_demo(self):
        observed = self.ns["compute_observed_models_summary"](ACCOUNT)
        self.assertTrue(observed)
        priced = [item for item in observed if any(item["modelId"].startswith(mid) for mid in self.demo.MODEL_PRICES)]
        self.assertTrue(priced)
        for item in priced:  # managed products (Gemini Enterprise, Code Assist) have no per-token price: they are not listed here
            self.assertFalse(item["isFallback"], f"{item['modelId']} would show a fallback price in the pricing view")

    def test_model_armor_labels_exist_in_the_real_backend(self):
        discovery = (ROOT / "backend" / "gcp_discovery.py").read_text(encoding="utf-8")
        for label in ("Not Enabled", "Active (", "API Enabled (0 Templates / Default Floor Setting not configured)", "INSPECT_AND_BLOCK (Blocks Prompts/Responses)"):
            self.assertIn(label, discovery)
        for project in self.cache30["projects"]:
            ma = project["modelArmor"]
            self.assertIn(ma["status"], ("DISABLED", "CONFIGURED_ACTIVE", "API_ENABLED_DEFAULT"))

    def test_standalone_enrichment_never_touches_the_repo_data(self):
        before = sup.snapshot_dir(sup.REPO_DATA_DIR)
        payload = self.demo.build_demo_scan_payload(days=7, reference_date="2026-11-04", enrich=True)
        self.assertTrue(payload["demo"]["enriched"])
        self.assertEqual(sup.snapshot_dir(sup.REPO_DATA_DIR), before)

    def test_generated_payload_is_deterministic_and_does_not_depend_on_the_runtime(self):
        a = self.demo.build_demo_scan_payload(days=30, seed=3, reference_date="2026-11-04", enrich=False)
        b = self.demo.build_demo_scan_payload(days=30, seed=3, reference_date="2026-11-04", enrich=False)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
