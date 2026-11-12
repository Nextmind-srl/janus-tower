"""Generator of invented demo data (backend/demo_data.py): determinism, coherence, privacy, shape (no network)."""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import unittest
from datetime import date, timedelta

import demo_test_support as sup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = "2026-11-04"


def load_app_namespace() -> dict:
    """A private backend in demo mode: its DATA_DIR is a temporary folder, so these tests never touch <repo>/data."""
    return sup.load_demo_namespace()


def load_demo_module():
    spec = importlib.util.spec_from_file_location("janustower_demo_data", os.path.join(ROOT, "backend", "demo_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def walk_strings(obj):
    """Yields every string (keys and values) of a JSON-like structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


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
    # any long opaque run mixing digits and capitals (ids here are short, readable and dashed; CLI flags have neither)
    re.compile(r"(?<![A-Za-z0-9/._:@\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Z])[A-Za-z0-9_\-]{40,}(?![A-Za-z0-9/._:@\-])"),
]
COST_TOLERANCE = 0.011


class TestDemoData(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.demo = load_demo_module()
        cls.payload = cls.demo.build_demo_scan_payload(days=30, seed=7, reference_date=REF)
        cls.ns = load_app_namespace()
        cls.addClassCleanup(sup.cleanup_namespace, cls.ns)

    def projects(self, payload=None):
        return (payload or self.payload)["projects"]

    def active_projects(self, payload=None):
        return [p for p in self.projects(payload) if p.get("dailySeries") and p.get("totalRequests", 0) > 0]

    # ---- determinism -------------------------------------------------------------------------------------

    def test_enrichment_available(self) -> None:
        self.assertTrue(self.payload["demo"]["enriched"], "the backend enrichment must be applied in the test environment")

    def test_deterministic_for_same_inputs(self) -> None:
        again = self.demo.build_demo_scan_payload(days=30, seed=7, reference_date=REF)
        self.assertEqual(dump(self.payload), dump(again))
        raw_a = self.demo.build_demo_scan_payload(days=30, seed=7, reference_date=REF, enrich=False)
        raw_b = self.demo.build_demo_scan_payload(days=30, seed=7, reference_date=REF, enrich=False)
        self.assertEqual(dump(raw_a), dump(raw_b))

    def test_seed_and_reference_date_change_the_output(self) -> None:
        other_seed = self.demo.build_demo_scan_payload(days=30, seed=8, reference_date=REF)
        self.assertNotEqual(self.payload["summary"]["estimatedCostUsd"], other_seed["summary"]["estimatedCostUsd"])
        shifted = self.demo.build_demo_scan_payload(days=30, seed=7, reference_date="2026-12-15")
        self.assertEqual(shifted["timeline"][-1]["date"], "2026-12-15")
        self.assertEqual(shifted["periodRange"]["endDate"], "2026-12-15")

    def test_window_is_anchored_to_the_reference_date_not_to_the_clock(self) -> None:
        dates = [t["date"] for t in self.payload["timeline"]]
        self.assertEqual(len(dates), 30)
        self.assertEqual(dates[-1], REF)
        self.assertEqual(dates[0], (date.fromisoformat(REF) - timedelta(days=29)).isoformat())
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(self.payload["periodRange"], {"days": 30, "startDate": dates[0], "endDate": REF})
        self.assertTrue(self.payload["scannedAt"].startswith(REF))
        # ageDays of the API keys comes from the (frozen) reference date, not from today's date
        for p in self.projects():
            for k in p.get("apiKeys", []):
                created = date.fromisoformat(k["createTime"][:10])
                self.assertEqual(k["ageDays"], (date.fromisoformat(REF) - created).days)

    def test_other_window_lengths(self) -> None:
        for n in (7, 60):
            pl = self.demo.build_demo_scan_payload(days=n, seed=7, reference_date=REF)
            self.assertEqual(len(pl["timeline"]), n)
            self.assertEqual(pl["days"], n)

    # ---- coherence of totals across levels ---------------------------------------------------------------

    def _check_project_coherence(self, p: dict, where: str) -> None:
        cost = p["estimatedCostUsd"]
        msg = f"{where} {p['projectId']}"
        if not p.get("dailySeries"):
            return
        self.assertAlmostEqual(cost, sum(v["costUsd"] for v in p["dailySeries"].values()), delta=COST_TOLERANCE, msg=msg)
        self.assertAlmostEqual(cost, p["vertexCostUsd"] + p["geminiCostUsd"] + p["otherAiCostUsd"], delta=COST_TOLERANCE, msg=msg)
        self.assertAlmostEqual(cost, sum(m["costUsd"] for m in p["models"]), delta=COST_TOLERANCE, msg=msg)
        for m in p["models"]:
            self.assertAlmostEqual(m["costUsd"], sum(v["costUsd"] for v in m["dailySeries"].values()), delta=COST_TOLERANCE, msg=msg)
            self.assertEqual(m["totalTokens"], sum(v["tokens"] for v in m["dailySeries"].values()), msg)
        self.assertEqual(p["totalRequests"], sum(v["requests"] for v in p["dailySeries"].values()), msg)
        self.assertEqual(p["inferenceRequests"], sum(v["inferenceRequests"] for v in p["dailySeries"].values()), msg)
        self.assertEqual(p["totalTokens"], sum(v["tokens"] for v in p["dailySeries"].values()), msg)
        self.assertEqual(p["totalTokens"], sum(m["totalTokens"] for m in p["models"]), msg)
        self.assertEqual(p["errors429"], sum(v["errors429"] for v in p["dailySeries"].values()), msg)
        # credentials carry the monitored (Vertex + Gemini API) cost; the pool products are attributed to users only
        creds_cost = sum(c["estimatedCostUsd"] for c in p["credentialsUsage"])
        self.assertAlmostEqual(creds_cost, p["vertexCostUsd"] + p["geminiCostUsd"], delta=COST_TOLERANCE, msg=msg)
        for c in p["credentialsUsage"]:
            self.assertAlmostEqual(c["estimatedCostUsd"], sum(v["costUsd"] for v in c["dailySeries"].values()), delta=COST_TOLERANCE, msg=msg)
        # users = credentials that belong to a person + managed pool products
        attributed = sum(c["estimatedCostUsd"] for c in p["credentialsUsage"] if c.get("ownerEmail"))
        users_cost = sum(u["estimatedCostUsd"] for u in p["usersUsage"])
        self.assertAlmostEqual(users_cost, attributed + p["otherAiCostUsd"], delta=COST_TOLERANCE * 3, msg=msg)
        # API keys mirror their credential
        creds_by_id = {c["credentialId"]: c for c in p["credentialsUsage"]}
        for k in p["apiKeys"]:
            c = creds_by_id.get(f"apikey:{k['uid']}")
            if c:
                self.assertAlmostEqual(k["estimatedCostUsd"], c["estimatedCostUsd"], delta=COST_TOLERANCE, msg=msg)
        # total bill = AI + infra
        self.assertAlmostEqual(p["totalBillCostUsd"], cost + p["infraCostUsd"], delta=COST_TOLERANCE, msg=msg)

    def test_costs_are_coherent_between_levels(self) -> None:
        for p in self.active_projects():
            self._check_project_coherence(p, "30d")

    def test_summary_and_timeline_match_the_projects(self) -> None:
        s = self.payload["summary"]
        projects = self.projects()
        self.assertEqual(s["totalProjects"], len(projects))
        for key in ("totalRequests", "inferenceRequests", "errors429", "totalTokens", "inputTokens", "outputTokens", "cachedTokens"):
            self.assertEqual(s[key], sum(p[key] for p in projects), key)
        for key in ("estimatedCostUsd", "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd", "infraCostUsd", "totalBillCostUsd"):
            self.assertAlmostEqual(s[key], sum(p[key] for p in projects), delta=COST_TOLERANCE, msg=key)
        tl = self.payload["timeline"]
        self.assertAlmostEqual(s["estimatedCostUsd"], sum(t["costUsd"] for t in tl), delta=COST_TOLERANCE)
        self.assertEqual(s["totalRequests"], sum(t["requests"] for t in tl))
        self.assertEqual(s["totalTokens"], sum(t["tokens"] for t in tl))
        for t in tl:
            self.assertEqual(t["requests"], sum(p["dailySeries"].get(t["date"], {}).get("requests", 0) for p in projects))
        users = {u["userEmail"] for p in projects for u in p["usersUsage"]}
        self.assertEqual(s["totalActiveUsers"], len(users))
        self.assertAlmostEqual(s["totalUsersCostUsd"], sum(u["estimatedCostUsd"] for p in projects for u in p["usersUsage"]), delta=0.05)

    def test_summary_matches_the_backend_assembly(self) -> None:
        """The hand-built summary equals what the real backend computes from the same projects."""
        rebuilt = self.ns["build_scan_payload_from_projects"](copy.deepcopy(self.projects()), 30, self.payload["auth"], 1.0, scanned_at=self.payload["scannedAt"])
        for key in (
            "totalProjects", "billedProjects", "skippedNoBillingProjects", "aiEnabledProjects", "hiddenNoAiProjects", "noMonitoringAccessProjects",
            "partialAccessProjects", "fullAccessProjects", "activeAiProjects", "modelArmorProjects", "totalDeployedAiResources", "totalRequests",
            "inferenceRequests", "systemRequests", "vertexRequests", "geminiApiRequests", "errors429", "totalTokens", "inputTokens", "outputTokens",
            "cachedTokens", "thinkingTokens", "totalApiKeys", "totalServiceAccounts", "totalActiveUsers",
        ):
            self.assertEqual(self.payload["summary"][key], rebuilt["summary"][key], key)
        for key in (
            "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd", "estimatedCostUsd", "infraCostUsd", "totalBillCostUsd", "totalUsersCostUsd",
            "totalApiKeysCostUsd", "totalOauthCostUsd", "totalServiceAccountsCostUsd",
        ):
            self.assertAlmostEqual(self.payload["summary"][key], rebuilt["summary"][key], delta=COST_TOLERANCE, msg=key)

    def test_timeline_is_credible(self) -> None:
        tl = self.payload["timeline"]
        costs = [t["costUsd"] for t in tl]
        self.assertTrue(all(c > 0 for c in costs[:-1]))
        weekday = [t["costUsd"] for t in tl[:-1] if date.fromisoformat(t["date"]).weekday() < 5]
        weekend = [t["costUsd"] for t in tl[:-1] if date.fromisoformat(t["date"]).weekday() >= 5]
        self.assertTrue(weekend)
        self.assertLess(sum(weekend) / len(weekend), 0.8 * sum(weekday) / len(weekday))
        # the last (in progress) day is lighter than a typical weekday
        self.assertGreater(len(set(round(c) for c in costs)), 15)

    # ---- privacy -----------------------------------------------------------------------------------------

    def test_only_reserved_email_domains(self) -> None:
        seen = set()
        for text in walk_strings(self.payload):
            for m in EMAIL_RE.finditer(text):
                email = m.group(0).lower().rstrip(".")
                seen.add(email)
                domain = email.split("@", 1)[1]
                local = email.split("@", 1)[0]
                ok_user = domain in ("example.com", "example.org", "contractor.example.net")
                # service accounts keep Google's naming scheme but with invented ids
                ok_sa = (domain.endswith(".iam.gserviceaccount.com") and domain.startswith("acme-")) or (
                    domain == "developer.gserviceaccount.com" and re.fullmatch(r"555\d{9}-compute", local)
                )
                self.assertTrue(ok_user or ok_sa, f"e-mail outside the reserved domains: {email}")
        self.assertTrue(any(e.endswith("@contractor.example.net") for e in seen))
        self.assertTrue(any(e.endswith("@example.org") for e in seen))
        self.assertIn(self.demo.DEMO_ACCOUNT, seen)

    def test_invented_identifiers_only(self) -> None:
        for p in self.projects():
            self.assertTrue(p["projectId"].startswith("acme-"), p["projectId"])
            self.assertTrue(str(p["projectNumber"]).startswith("555"), p["projectNumber"])
        self.assertNotIn("gen-lang-client", dump(self.payload))
        for u in (u for p in self.projects() for u in p["usersUsage"]):
            em = u["userEmail"]
            self.assertTrue(em.startswith("oauth-workload:") or em.split("@")[1] in ("example.com", "example.org", "contractor.example.net"), em)
        # service account unique ids and API key uids are obviously fake
        for p in self.projects():
            for k in p["apiKeys"]:
                self.assertTrue(k["uid"].startswith("00000000-0000-4000-8000-"), k["uid"])
            for sa in p["serviceAccounts"]:
                self.assertTrue(sa["uniqueId"].startswith("999"), sa["uniqueId"])

    def test_no_secret_like_strings(self) -> None:
        for text in walk_strings(self.payload):
            for rx in SECRET_RES:
                self.assertIsNone(rx.search(text), f"secret-like string ({rx.pattern}): {text[:80]}")
        auth = self.demo.build_demo_auth_status(REF)
        for text in walk_strings(auth):
            for rx in SECRET_RES:
                self.assertIsNone(rx.search(text), text)
        self.assertNotIn("accessToken", auth)
        self.assertEqual(auth["activeAccount"], self.demo.DEMO_ACCOUNT)
        self.assertTrue(auth["tokenValid"])

    def test_cli_refuses_to_write_inside_the_repository(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.demo.main(["--output", os.path.join(ROOT, "demo_should_not_exist.json")]), 2)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "demo_should_not_exist.json")))

    # ---- slicing keeps the shape -------------------------------------------------------------------------

    def test_payload_goes_through_slice_for_30_and_7_days(self) -> None:
        fn = self.ns["slice_cached_payload_for_days"]
        original_dump = dump(self.payload)
        for n in (30, 7):
            sliced = fn(copy.deepcopy(self.payload), n, {})
            self.assertEqual(sliced["periodRange"]["days"], n)
            self.assertEqual(sliced["periodRange"]["endDate"], REF)
            self.assertEqual(len(sliced["timeline"]), n)
            self.assertEqual(set(sliced["summary"]).issuperset({"totalProjects", "estimatedCostUsd", "securityPosture", "dataResidency", "finopsExtended"}), True)
            self.assertEqual(len(sliced["projects"]), len(self.payload["projects"]))
            by_id = {p["projectId"]: p for p in self.payload["projects"]}
            for sp in sliced["projects"]:
                self.assertTrue(set(by_id[sp["projectId"]]).issubset(set(sp)), f"keys lost by the slice in {sp['projectId']}")
                self._check_project_coherence(sp, f"{n}d")
                self.assertLessEqual(sp["estimatedCostUsd"], by_id[sp["projectId"]]["estimatedCostUsd"] + COST_TOLERANCE)
            self.assertAlmostEqual(sliced["summary"]["estimatedCostUsd"], sum(t["costUsd"] for t in sliced["timeline"]), delta=COST_TOLERANCE * 3)
        seven = fn(copy.deepcopy(self.payload), 7, {})
        self.assertLess(seven["summary"]["estimatedCostUsd"], self.payload["summary"]["estimatedCostUsd"])
        self.assertEqual(original_dump, dump(self.payload), "the slice must not alter the source payload (it works on a copy)")

    def test_security_sections_survive_the_slice(self) -> None:
        seven = self.ns["slice_cached_payload_for_days"](copy.deepcopy(self.payload), 7, {})
        for p in seven["projects"]:
            self.assertIn("aiSecurityPosture", p)
            self.assertGreaterEqual(p["aiSecurityPosture"]["score"], 0)
            self.assertLessEqual(p["aiSecurityPosture"]["score"], 100)
        self.assertGreater(seven["summary"]["securityPosture"]["evaluatedProjects"], 0)

    # ---- fields read by the views ------------------------------------------------------------------------

    def test_top_level_keys(self) -> None:
        for key in ("success", "scannedAt", "elapsedSeconds", "days", "auth", "summary", "timeline", "projects", "sync", "periodRange", "fromCache", "scanMode"):
            self.assertIn(key, self.payload)
        self.assertEqual(self.payload["auth"]["activeAccount"], self.demo.DEMO_ACCOUNT)
        sync = self.payload["sync"]
        self.assertEqual(sync["totalSynchronized"], len(self.payload["projects"]))
        for key in ("includedToScanCount", "excludedFromScanCount", "withAiDataCount", "newProjectsCount", "projects", "lastSyncAt"):
            self.assertIn(key, sync)
        self.assertGreaterEqual(sync["newProjectsCount"], 1)
        self.assertGreaterEqual(sync["manualOverridesCount"], 1)

    def test_executive_dashboard_and_daily_spend_fields(self) -> None:
        s = self.payload["summary"]
        for key in (
            "totalProjects", "billedProjects", "aiEnabledProjects", "totalRequests", "inferenceRequests", "errors429", "totalTokens", "inputTokens",
            "outputTokens", "cachedTokens", "estimatedCostUsd", "totalBillCostUsd", "infraCostUsd", "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd",
            "totalApiKeys", "totalServiceAccounts", "totalActiveUsers", "totalTcoUsd", "cacheHitRatePct", "excludedNonAiInfraCostUsd",
            "securityPosture", "dataResidency", "finopsExtended", "agentspaceTelemetry", "aiToolsOverview", "serviceAccountsInventory",
            "modelArmorMatrix", "geminiEnterpriseInventory", "mcpAndAgentRegistry", "aiLogForensics", "httpStatusBreakdown", "avgLatencyMs",
        ):
            self.assertIn(key, s, key)
        for key in ("date", "requests", "inferenceRequests", "errors429", "tokens", "inputTokens", "outputTokens", "cachedTokens", "costUsd",
                    "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd"):
            self.assertIn(key, self.payload["timeline"][0], key)
        fin = s["finopsExtended"]
        for key in ("cacheHitRatePct", "forecast30dAiUsd", "dailyBurnRateAiUsd", "costTrend7dPct", "projectBudgets", "idleResources"):
            self.assertIn(key, fin, key)
        self.assertGreater(s["errors429"], 0)
        self.assertGreater(s["cachedTokens"], 0)
        self.assertGreater(s["totalBillCostUsd"], s["estimatedCostUsd"])

    def test_project_level_fields(self) -> None:
        required = (
            "projectId", "name", "projectNumber", "billingEnabled", "skippedNoBilling", "aiActive", "scanStatus", "enabledAiApis", "vertexFeatures",
            "deployedAiResources", "modelArmor", "permissions", "totalRequests", "inferenceRequests", "errors429", "totalTokens", "estimatedCostUsd",
            "infraServices", "models", "credentialsUsage", "usersUsage", "apiKeys", "serviceAccounts", "dailySeries", "budgetUsd",
            "dataResidency", "finopsExtended", "agentspaceTelemetry", "aiToolsSummary", "aiLogForensics", "aiSecurityPosture",
        )
        for p in self.projects():
            for key in required:
                self.assertIn(key, p, f"{p['projectId']}: {key}")

    def test_project_states_cover_denied_unverified_and_no_billing(self) -> None:
        by_id = {p["projectId"]: p for p in self.projects()}
        self.assertEqual(by_id["acme-partner-portal"]["scanStatus"], "NO_PERMISSIONS_403")
        self.assertFalse(by_id["acme-partner-portal"]["permissions"]["areas"]["monitoring"]["granted"])
        self.assertEqual(by_id["acme-pilot-unverified"]["transientError"], "RATE_LIMITED")
        self.assertTrue(by_id["acme-research-sandbox"]["skippedNoBilling"])
        self.assertFalse(by_id["acme-hackathon-2026"]["billingEnabled"])
        self.assertTrue(by_id["acme-hackathon-2026"]["isAiStudioProject"])
        self.assertGreaterEqual(len(by_id), 10)
        self.assertLessEqual(len(by_id), 14)
        s = self.payload["summary"]
        self.assertEqual(s["noMonitoringAccessProjects"], 1)
        self.assertGreaterEqual(s["skippedNoBillingProjects"], 1)
        self.assertGreaterEqual(s["partialAccessProjects"], 1)
        self.assertGreaterEqual(s["fullAccessProjects"], 1)
        for p in self.projects():
            areas = p["permissions"].get("areas")
            if areas:
                self.assertEqual(set(areas), {"billingInfo", "billingCosts", "serviceUsage", "monitoring", "aiResources", "modelArmor", "apiKeys", "serviceAccounts"})

    def test_cost_by_user_with_antigravity_oauth_workload(self) -> None:
        users = [(p["projectId"], u) for p in self.projects() for u in p["usersUsage"]]
        workload = [(pid, u) for pid, u in users if u["userEmail"].startswith("oauth-workload:")]
        self.assertEqual(len(workload), 1)
        pid, wl = workload[0]
        self.assertRegex(wl["userEmail"], r"^oauth-workload:\d+$")
        self.assertEqual(wl["userType"], "OAUTH_WORKLOAD")
        self.assertGreater(wl["vertexOauthCostUsd"], 0)
        self.assertEqual(len(wl["oauthClientsDetails"]), 1)
        self.assertIn("Antigravity", wl["oauthClientsDetails"][0]["tool"])
        self.assertIn("Antigravity IDE (Vertex AI OAuth)", wl["toolsUsed"])
        # it is the single most expensive identity of the company
        top = max(users, key=lambda x: x[1]["estimatedCostUsd"])
        self.assertEqual(top[1]["userEmail"], wl["userEmail"])
        types = {u["userType"] for _pid, u in users}
        self.assertTrue({"INTERNAL_USER", "EXTERNAL_USER", "OAUTH_WORKLOAD"}.issubset(types))
        for _pid, u in users:
            for key in ("userEmail", "userType", "estimatedCostUsd", "oauthCostUsd", "apiKeysCostUsd", "toolsUsed", "attributedTokens", "totalInteractions", "firstSeen", "lastSeen"):
                self.assertIn(key, u)

    def test_ai_models_fields(self) -> None:
        ids = set()
        for p in self.active_projects():
            for m in p["models"]:
                ids.add(m["modelId"])
                for key in ("modelId", "locations", "invocations", "inputTokens", "outputTokens", "cachedTokens", "totalTokens", "costUsd", "grossCostUsd", "cacheSavingsUsd", "dailySeries"):
                    self.assertIn(key, m)
        for expected in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "text-embedding-005"):
            self.assertIn(expected, ids)
        self.assertGreater(len(ids), 6)
        self.assertTrue(any(p["vertexFeatures"] for p in self.projects()))

    def test_pricing_view_observed_models_fallback(self) -> None:
        """Pricing & Rates falls back to globalScanData.projects[].models[] when the server has no observed models yet."""
        for p in self.active_projects():
            for m in p["models"]:
                self.assertTrue(m["modelId"])
                self.assertIsInstance(m["invocations"], int)

    def test_ai_studio_and_notebooks_fields(self) -> None:
        tools = self.payload["summary"]["aiToolsOverview"]
        self.assertGreaterEqual(tools["aiStudioProjectsCount"], 2)
        self.assertGreater(tools["aiStudioTotalKeys"], 2)
        self.assertGreater(tools["colabResourcesTotalCount"], 20)
        by_id = {p["projectId"]: p for p in self.projects()}
        sandbox = by_id["acme-aistudio-sandbox"]["aiToolsSummary"]
        self.assertTrue(sandbox["aiStudio"]["isAiStudioProject"])
        self.assertGreaterEqual(sandbox["aiStudioKeysCount"], 3)
        # one NotebookLM Enterprise project with many users (expandable lists)
        agentspace = by_id["acme-agentspace"]["aiToolsSummary"]
        self.assertGreater(agentspace["notebookLmEnterpriseCalls"], 0)
        self.assertGreater(len(agentspace["notebooks"]["users"]), 15)
        # scheduled Colab executions: several runs of the same job, with success and failures
        ml = by_id["acme-ml-lab"]
        jobs = [r for r in ml["deployedAiResources"] if r["resourceType"] == "COLAB_EXECUTION_JOB"]
        names = {}
        for j in jobs:
            names.setdefault((j["displayName"], j["runtimeUser"]), []).append(j["state"])
        self.assertTrue(any(len(v) > 10 for v in names.values()))
        self.assertTrue(any("JOB_STATE_FAILED" in v for v in names.values()))
        self.assertGreater(ml["aiToolsSummary"]["notebooks"]["colabRuntimesCount"], 2)
        self.assertGreaterEqual(ml["aiToolsSummary"]["notebooks"]["colabTemplatesCount"], 1)
        self.assertGreaterEqual(ml["aiToolsSummary"]["notebooks"]["workbenchInstancesCount"], 1)

    def test_gemini_enterprise_and_agentspace(self) -> None:
        agentspace = {p["projectId"]: p for p in self.projects()}["acme-agentspace"]
        tele = agentspace["agentspaceTelemetry"]
        self.assertGreaterEqual(tele["totalApps"], 2)
        self.assertGreaterEqual(tele["totalDataStores"], 5)
        self.assertGreaterEqual(tele["unusedDataStoresCount"], 1)
        self.assertGreater(tele["totalUserQueries"], 0)
        self.assertTrue(any(len(a["users"]) > 15 for a in tele["apps"]))
        inv = self.payload["summary"]["geminiEnterpriseInventory"]
        self.assertGreaterEqual(inv["summary"]["totalApps"], 2)
        self.assertGreaterEqual(len(inv["apps"]), 2)
        users = agentspace["usersUsage"]
        self.assertGreater(len(users), 20)
        self.assertTrue(any(u["userType"] == "EXTERNAL_USER" for u in users))

    def test_api_keys_and_service_accounts(self) -> None:
        keys = [k for p in self.projects() for k in p["apiKeys"]]
        names = {k["displayName"] for k in keys}
        self.assertIn("AI Reporting", names)
        self.assertTrue(any(not k["restrictions"] for k in keys), "at least one unrestricted key")
        self.assertTrue(any(k["restrictions"] for k in keys), "at least one restricted key")
        self.assertTrue(any(k["status"] == "DELETED_OR_EXTERNAL" and k["inferenceRequests"] > 0 for k in keys))
        self.assertTrue(any(k["ageDays"] > 90 for k in keys))
        for k in keys:
            for key in ("uid", "displayName", "status", "ownerEmail", "createTime", "restrictions", "inferenceRequests", "estimatedCostUsd", "ageDays"):
                self.assertIn(key, k)
        sas = [sa for p in self.projects() for sa in p["serviceAccounts"]]
        self.assertTrue(any(sa["userManagedKeysCount"] > 0 for sa in sas))
        self.assertTrue(any(sa["disabled"] for sa in sas))
        self.assertTrue(any(sa["isDefaultGcpSa"] for sa in sas))
        inv = self.payload["summary"]["serviceAccountsInventory"]
        self.assertEqual(inv["totalCount"], len(sas))
        self.assertGreaterEqual(inv["withExportedKeysCount"], 2)
        self.assertGreaterEqual(inv["withExpiredKeysCount"], 1)

    def test_ai_security_signals_and_posture_scores(self) -> None:
        scores = []
        finding_ids = set()
        for p in self.projects():
            posture = p["aiSecurityPosture"]
            if posture["evaluated"]:
                self.assertGreaterEqual(posture["score"], 0)
                self.assertLessEqual(posture["score"], 100)
                scores.append(posture["score"])
                finding_ids.update(f["id"] for f in posture["findings"])
        self.assertGreaterEqual(len(scores), 8)
        self.assertGreater(max(scores) - min(scores), 50, "scores should be spread across grades")
        for expected in ("UNRESTRICTED_API_KEYS", "STATIC_SA_USER_MANAGED_KEYS", "GDPR_NON_EU_AI_PROCESSING", "MISSING_MODEL_ARMOR", "ACTIVE_MODEL_ARMOR_THREATS"):
            self.assertIn(expected, finding_ids)
        sp = self.payload["summary"]["securityPosture"]
        self.assertGreater(sp["totalFindings"], 10)
        self.assertGreaterEqual(sp["criticalFindings"], 1)
        # Model Armor: some projects protected, some not
        ma = self.payload["summary"]["modelArmorMatrix"]
        self.assertGreaterEqual(ma["protectedProjectsCount"], 2)
        self.assertGreaterEqual(ma["unprotectedProjectsCount"], 2)
        self.assertGreater(self.payload["summary"]["modelArmorProjects"], 0)
        # inference outside the EU
        dr = self.payload["summary"]["dataResidency"]
        self.assertGreaterEqual(dr["gdprNonCompliantProjects"], 1)
        self.assertGreater(dr["nonEuRequests"], 0)
        by_id = {p["projectId"]: p for p in self.projects()}
        self.assertTrue(by_id["acme-finance-prod"]["modelArmorEnabled"])
        self.assertFalse(by_id["acme-ml-lab"]["modelArmorEnabled"])
        self.assertGreater(by_id["acme-support-bot"]["modelArmor"]["threatTelemetry"]["flaggedCount"], 0)


if __name__ == "__main__":
    unittest.main()
