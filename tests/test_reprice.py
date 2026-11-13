"""End-to-end test suite for instant AI cost repricing from pure pricingAtoms."""

import copy
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message

import server
from tests.demo_test_support import (
    REPO_DATA_DIR,
    ROOT,
    cleanup_namespace,
    load_demo_namespace,
    load_namespace,
    snapshot_dir,
)

FORBIDDEN_MONEY_KEY_FRAGMENTS = ("cost", "usd", "gross", "sav")
EXPECTED_STALE_BANNER_TEXT = "Costs were computed before instant repricing existed: run a scan once to enable it."


def _pt_int(day_str: str, val: int) -> dict:
    return {
        "interval": {"endTime": f"{day_str}T12:00:00Z"},
        "value": {"int64Value": str(int(val))},
    }


def _pt_dist(day_str: str, count: int, mean: float) -> dict:
    return {
        "interval": {"endTime": f"{day_str}T12:00:00Z"},
        "value": {"distributionValue": {"count": str(int(count)), "mean": float(mean)}},
    }


def _req_ts(
    service: str,
    method: str,
    credential_id: str,
    location: str,
    points: list[dict],
    response_code: str = "200",
) -> dict:
    return {
        "resource": {
            "labels": {
                "service": service,
                "method": method,
                "credential_id": credential_id,
                "location": location,
            }
        },
        "metric": {"labels": {"response_code": response_code}},
        "points": points,
    }


def _vertex_tok_ts(model_id: str, location: str, tok_type: str, points: list[dict]) -> dict:
    return {
        "resource": {"labels": {"model_user_id": model_id, "location": location}},
        "metric": {"labels": {"type": tok_type}},
        "points": points,
    }


def _vertex_inv_ts(model_id: str, location: str, points: list[dict]) -> dict:
    return {
        "resource": {"labels": {"model_user_id": model_id, "location": location}},
        "metric": {"labels": {}},
        "points": points,
    }


def _gemini_tok_ts(model_lbl: str, points: list[dict]) -> dict:
    return {
        "metric": {"labels": {"model": model_lbl}},
        "points": points,
    }


def _gemini_bytes_ts(credential_id: str, method: str, location: str, points: list[dict]) -> dict:
    return {
        "resource": {
            "labels": {
                "credential_id": credential_id,
                "method": method,
                "location": location,
            }
        },
        "points": points,
    }


def _df_tok_ts(base_model: str, location: str, points: list[dict], loc_key: str = "location") -> dict:
    return {
        "metric": {"labels": {"base_model": base_model}},
        "resource": {"labels": {loc_key: location}},
        "points": points,
    }


def _empty_mon_results() -> dict:
    return {
        "req_count": [],
        "req_lat": [],
        "gemini_req_b": [],
        "gemini_resp_b": [],
        "gemini_out_tok": [],
        "gemini_in_tok": [],
        "gemini_free_in_tok_0": [],
        "vertex_tok": [],
        "vertex_inv": [],
        "df_multi": [],
        "df_loc": [],
    }


def _assert_no_sets(obj, path: str = "root") -> None:
    if isinstance(obj, set):
        raise AssertionError(f"Non-JSON-serializable set found at {path}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_sets(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            _assert_no_sets(item, f"{path}[{idx}]")


def _assert_no_money_keys_in_atoms(atoms: dict) -> None:
    for group_name, items in atoms.items():
        if not isinstance(items, list):
            raise AssertionError(f"Expected list for pricingAtoms.{group_name}")
        for idx, rec in enumerate(items):
            if not isinstance(rec, dict):
                raise AssertionError(f"Expected dict at pricingAtoms.{group_name}[{idx}]")
            for key in rec:
                key_low = str(key).lower()
                for frag in FORBIDDEN_MONEY_KEY_FRAGMENTS:
                    if frag in key_low:
                        raise AssertionError(
                            f"Forbidden money key '{key}' found inside pricingAtoms.{group_name}[{idx}]"
                        )


class RepriceTestBase(unittest.TestCase):
    """Base test case isolating every backend file path inside a fresh TemporaryDirectory."""

    def setUp(self) -> None:
        self._repo_data_before = snapshot_dir(REPO_DATA_DIR)
        self.tmp = tempfile.TemporaryDirectory()
        self.ns = load_namespace({"JANUSTOWER_DEMO": "0"})
        self.ns["DATA_DIR"] = self.tmp.name
        self.ns["MODELS_PRICING_FILE"] = os.path.join(self.tmp.name, "models_pricing_config.json")
        self.ns["BUDGETS_FILE"] = os.path.join(self.tmp.name, "budgets_config.json")
        self.ns["TOKENS_FILE"] = os.path.join(self.tmp.name, "oauth_tokens.json")
        self.ns["SYNC_REGISTRY_FILE"] = os.path.join(self.tmp.name, "projects_sync_registry.json")
        self.ns["CACHE_FILE"] = os.path.join(self.tmp.name, "last_scan_cache.json")
        self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
        self.ns["RAM_PAYLOAD_CACHE"].clear()

        # Hard-block accidental network helpers during unit and simulated scan tests.
        def _forbid_network(*args, **kwargs):
            raise AssertionError(f"Network call forbidden in tests: {args[:1]}")

        self.ns["gcp_api_get"] = _forbid_network
        self.ns["gcp_api_post"] = _forbid_network

        now = datetime.now(timezone.utc)
        self.day_today = now.strftime("%Y-%m-%d")
        self.day_yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        self.day_recent = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        self.day_old = (now - timedelta(days=18)).strftime("%Y-%m-%d")

    def tearDown(self) -> None:
        self.ns["RAM_PAYLOAD_CACHE"].clear()
        self.tmp.cleanup()
        self.assertEqual(
            snapshot_dir(REPO_DATA_DIR),
            self._repo_data_before,
            "Repository data/ directory must never be created or modified by tests.",
        )

    def _apply_pricing_config(
        self,
        billing_settings: dict | None = None,
        models_update: dict | None = None,
        oauth_client_owners: dict | None = None,
    ) -> dict:
        payload: dict = {}
        if billing_settings is not None:
            payload["billingSettings"] = billing_settings
        if models_update is not None:
            payload["models"] = models_update
        if payload:
            ok, err, cfg = self.ns["validate_and_apply_models_pricing_update"](payload)
            self.assertTrue(ok, f"validate_and_apply_models_pricing_update failed: {err}")
        else:
            cfg = self.ns["load_models_pricing_config"]()

        if oauth_client_owners is not None:
            cfg_disk = self.ns["load_models_pricing_config"]()
            cfg_disk["oauthClientOwners"] = copy.deepcopy(oauth_client_owners)
            self.ns["save_models_pricing_config"](cfg_disk)
            cfg = cfg_disk

        self.ns["_MODELS_PRICING_MEM_CACHE"] = {"mtime": 0.0, "data": None}
        self.ns["RAM_PAYLOAD_CACHE"].clear()
        return cfg

    def _build_rich_synthetic_fixtures(self) -> tuple[list[dict], dict[str, dict], dict[str, tuple]]:
        """Builds synthetic Monitoring series, IAM keys/SAs, and user logs for proj-alpha and proj-beta."""
        projects_meta = [
            {
                "projectId": "proj-alpha",
                "name": "Project Alpha AI",
                "projectNumber": "1000000001",
                "createTime": "2025-01-10T08:00:00Z",
            },
            {
                "projectId": "proj-beta",
                "name": "Project Beta Studio",
                "projectNumber": "1000000002",
                "createTime": "2025-02-15T09:30:00Z",
            },
        ]

        mon_alpha = _empty_mon_results()
        mon_alpha["req_count"] = [
            _req_ts(
                "aiplatform.googleapis.com",
                "google.cloud.aiplatform.v1.PredictionService.GenerateContent",
                "serviceaccount:100001",
                "global",
                [_pt_int(self.day_today, 30), _pt_int(self.day_yesterday, 20), _pt_int(self.day_old, 10)],
            ),
            _req_ts(
                "aiplatform.googleapis.com",
                "google.cloud.aiplatform.v1.PredictionService.StreamGenerateContent",
                "oauth2:client-vtx-carol",
                "europe-west4",
                [_pt_int(self.day_today, 15), _pt_int(self.day_yesterday, 10)],
            ),
            _req_ts(
                "generativelanguage.googleapis.com",
                "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent",
                "apikey:uid-key-dave",
                "global",
                [_pt_int(self.day_today, 24), _pt_int(self.day_yesterday, 12)],
            ),
            _req_ts(
                "generativelanguage.googleapis.com",
                "google.ai.generativelanguage.v1beta.GenerativeService.StreamGenerateContent",
                "apikey:uid-key-dave",
                "global",
                [_pt_int(self.day_yesterday, 8)],
            ),
            _req_ts(
                "discoveryengine.googleapis.com",
                "google.cloud.discoveryengine.v1.AssistantService.StreamAssist",
                "oauth2:pool-shared-01",
                "eu",
                [_pt_int(self.day_today, 18), _pt_int(self.day_yesterday, 12)],
            ),
            _req_ts(
                "discoveryengine.googleapis.com",
                "google.cloud.discoveryengine.v1.SearchService.Search",
                "oauth2:pool-shared-01",
                "eu",
                [_pt_int(self.day_today, 25)],
            ),
            _req_ts(
                "cloudaicompanion.googleapis.com",
                "google.cloud.cloudaicompanion.v1.CodeGenerationService.GenerateCode",
                "oauth2:pool-shared-01",
                "global",
                [_pt_int(self.day_today, 40), _pt_int(self.day_recent, 20)],
            ),
            _req_ts(
                "modelarmor.googleapis.com",
                "google.cloud.modelarmor.v1.ModelArmor.SanitizeUserPrompt",
                "serviceaccount:100001",
                "europe-west4",
                [_pt_int(self.day_today, 50)],
            ),
            _req_ts(
                "dialogflow.googleapis.com",
                "google.cloud.dialogflow.cx.v3.Sessions.DetectIntent",
                "serviceaccount:100002",
                "eu",
                [_pt_int(self.day_today, 14), _pt_int(self.day_yesterday, 6)],
            ),
        ]
        mon_alpha["vertex_tok"] = [
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "global",
                "input",
                [_pt_int(self.day_today, 500_000), _pt_int(self.day_yesterday, 300_000), _pt_int(self.day_old, 200_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "global",
                "cache_read_input",
                [_pt_int(self.day_today, 250_000), _pt_int(self.day_yesterday, 150_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "global",
                "output",
                [_pt_int(self.day_today, 90_000), _pt_int(self.day_yesterday, 60_000), _pt_int(self.day_old, 40_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "global",
                "thinking",
                [_pt_int(self.day_today, 45_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "europe-west4",
                "input",
                [_pt_int(self.day_today, 400_000), _pt_int(self.day_yesterday, 200_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-pro",
                "europe-west4",
                "output",
                [_pt_int(self.day_today, 80_000), _pt_int(self.day_yesterday, 40_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-flash",
                "global",
                "input",
                [_pt_int(self.day_today, 600_000)],
            ),
            _vertex_tok_ts(
                "gemini-2.5-flash",
                "global",
                "output",
                [_pt_int(self.day_today, 120_000)],
            ),
        ]
        mon_alpha["vertex_inv"] = [
            _vertex_inv_ts(
                "gemini-2.5-pro",
                "global",
                [_pt_int(self.day_today, 30), _pt_int(self.day_yesterday, 20), _pt_int(self.day_old, 10)],
            ),
            _vertex_inv_ts(
                "gemini-2.5-pro",
                "europe-west4",
                [_pt_int(self.day_today, 15), _pt_int(self.day_yesterday, 10)],
            ),
            _vertex_inv_ts("gemini-2.5-flash", "global", [_pt_int(self.day_today, 12)]),
        ]
        # day_today uses exact Gemini API token metrics (paid + free tier); day_yesterday falls back to payload bytes
        mon_alpha["gemini_in_tok"] = [
            _gemini_tok_ts("gemini-2.5-pro", [_pt_int(self.day_today, 320_000)]),
        ]
        mon_alpha["gemini_free_in_tok_0"] = [
            _gemini_tok_ts("gemini-2.5-flash-lite", [_pt_int(self.day_today, 140_000)]),
        ]
        mon_alpha["gemini_out_tok"] = [
            _gemini_tok_ts("gemini-2.5-pro", [_pt_int(self.day_today, 64_000)]),
            _gemini_tok_ts("gemini-2.5-flash-lite", [_pt_int(self.day_today, 16_000)]),
        ]
        mon_alpha["gemini_req_b"] = [
            _gemini_bytes_ts(
                "apikey:uid-key-dave",
                "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent",
                "global",
                [_pt_dist(self.day_today, 24, 2400.0), _pt_dist(self.day_yesterday, 12, 8000.0)],
            ),
            _gemini_bytes_ts(
                "apikey:uid-key-dave",
                "google.ai.generativelanguage.v1beta.GenerativeService.StreamGenerateContent",
                "global",
                [_pt_dist(self.day_yesterday, 8, 6000.0)],
            ),
        ]
        mon_alpha["gemini_resp_b"] = [
            _gemini_bytes_ts(
                "apikey:uid-key-dave",
                "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent",
                "global",
                [_pt_dist(self.day_today, 24, 1600.0), _pt_dist(self.day_yesterday, 12, 4000.0)],
            ),
            _gemini_bytes_ts(
                "apikey:uid-key-dave",
                "google.ai.generativelanguage.v1beta.GenerativeService.StreamGenerateContent",
                "global",
                [_pt_dist(self.day_yesterday, 8, 3200.0)],
            ),
        ]
        mon_alpha["df_loc"] = [
            _df_tok_ts(
                "gemini-2.5-flash",
                "eu",
                [_pt_int(self.day_today, 280_000), _pt_int(self.day_yesterday, 140_000)],
            ),
        ]

        alpha_keys = [
            {
                "uid": "uid-key-dave",
                "name": "projects/proj-alpha/locations/global/keys/uid-key-dave",
                "displayName": "Gemini Studio Key Dave",
                "createTime": "2026-01-05T10:00:00Z",
                "restrictions": {"apiTargets": [{"service": "generativelanguage.googleapis.com"}]},
            }
        ]
        alpha_key_owners = {
            "uid-key-dave": {
                "uid": "uid-key-dave",
                "ownerEmail": "dave@example.com",
                "displayName": "Gemini Studio Key Dave",
                "createdAt": "2026-01-05T10:00:00Z",
                "method": "CreateKey",
            }
        }
        alpha_sas = {
            "accounts": [
                {
                    "uniqueId": "100001",
                    "email": "sa-vertex@proj-alpha.iam.gserviceaccount.com",
                    "displayName": "Vertex Runtime SA",
                    "disabled": False,
                },
                {
                    "uniqueId": "100002",
                    "email": "sa-df@proj-alpha.iam.gserviceaccount.com",
                    "displayName": "Dialogflow Agent SA",
                    "disabled": False,
                },
            ]
        }
        alpha_ma = {
            "enabled": True,
            "permissionGranted": True,
            "status": "ACTIVE",
            "statusLabel": "Active",
            "totalRequests": 50,
            "sanitizeRequests": 50,
            "methodsCalled": ["SanitizeUserPrompt"],
            "activeLocations": ["europe-west4"],
            "floorSetting": {"enableFloorSettingEnforcement": True},
            "templates": [{"name": "projects/proj-alpha/locations/europe-west4/templates/tmpl-1"}],
        }
        alpha_ulogs = [
            {
                "logName": "projects/proj-alpha/logs/discoveryengine.googleapis.com%2Fgemini_enterprise_user_activity",
                "timestamp": f"{self.day_today}T10:05:00Z",
                "trace": "projects/proj-alpha/traces/trace-alice-1",
                "jsonPayload": {
                    "userIamPrincipal": "alice@example.com",
                    "logMetadata": {
                        "methodName": "google.cloud.discoveryengine.v1.AssistantService.StreamAssist",
                        "name": "projects/proj-alpha/locations/eu/collections/default_collection/engines/eng-alpha/sessions/sess-a1",
                    },
                },
            },
            {
                "logName": "projects/proj-alpha/logs/discoveryengine.googleapis.com%2Fgemini_enterprise_user_activity",
                "timestamp": f"{self.day_yesterday}T11:15:00Z",
                "trace": "projects/proj-alpha/traces/trace-alice-2",
                "jsonPayload": {
                    "userIamPrincipal": "alice@example.com",
                    "logMetadata": {
                        "methodName": "google.cloud.discoveryengine.v1.SearchService.Search",
                        "name": "projects/proj-alpha/locations/eu/collections/default_collection/engines/eng-alpha/servingConfigs/default_search",
                    },
                },
            },
            {
                "logName": "projects/proj-alpha/logs/gen_ai.client.inference.operation.details",
                "timestamp": f"{self.day_today}T10:05:02Z",
                "trace": "projects/proj-alpha/traces/trace-alice-1",
                "jsonPayload": {
                    "gen_ai.usage.input_tokens": 24_000,
                    "gen_ai.usage.output_tokens": 4_500,
                    "gen_ai.usage.cache_read.input_tokens": 12_000,
                    "gen_ai.conversation.id": "sess-a1",
                    "gen_ai.agent.name": "alpha-assistant",
                },
            },
            {
                "logName": "projects/proj-alpha/logs/cloudaicompanion.googleapis.com%2Fmetadata",
                "timestamp": f"{self.day_today}T14:20:00Z",
                "labels": {
                    "user_id": "bob@example.com",
                    "method": "google.cloud.cloudaicompanion.v1.CodeGenerationService.GenerateCode",
                },
                "jsonPayload": {"clientName": "VSCode", "clientVersion": "1.99.0"},
            },
            {
                "logName": "projects/proj-alpha/logs/cloudaicompanion.googleapis.com%2Fmetadata",
                "timestamp": f"{self.day_recent}T16:10:00Z",
                "labels": {
                    "user_id": "bob@example.com",
                    "method": "google.cloud.cloudaicompanion.v1.CodeGenerationService.GenerateCode",
                },
                "jsonPayload": {"clientName": "VSCode", "clientVersion": "1.99.0"},
            },
        ]

        # proj-beta exercises Gemini API call-only fallback (AI_STUDIO_ESTIMATE) + regional Vertex flash
        mon_beta = _empty_mon_results()
        mon_beta["req_count"] = [
            _req_ts(
                "generativelanguage.googleapis.com",
                "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent",
                "apikey:uid-key-beta",
                "global",
                [_pt_int(self.day_today, 16), _pt_int(self.day_yesterday, 9)],
            ),
            _req_ts(
                "aiplatform.googleapis.com",
                "google.cloud.aiplatform.v1.PredictionService.GenerateContent",
                "serviceaccount:200001",
                "europe-west4",
                [_pt_int(self.day_today, 10)],
            ),
        ]
        mon_beta["vertex_tok"] = [
            _vertex_tok_ts("gemini-2.5-flash", "europe-west4", "input", [_pt_int(self.day_today, 300_000)]),
            _vertex_tok_ts("gemini-2.5-flash", "europe-west4", "output", [_pt_int(self.day_today, 50_000)]),
        ]
        mon_beta["vertex_inv"] = [
            _vertex_inv_ts("gemini-2.5-flash", "europe-west4", [_pt_int(self.day_today, 10)]),
        ]
        beta_keys = [
            {
                "uid": "uid-key-beta",
                "name": "projects/proj-beta/locations/global/keys/uid-key-beta",
                "displayName": "AI Studio Fallback Key",
                "createTime": "2026-02-01T08:00:00Z",
                "restrictions": {"apiTargets": [{"service": "generativelanguage.googleapis.com"}]},
            }
        ]
        beta_key_owners = {
            "uid-key-beta": {
                "uid": "uid-key-beta",
                "ownerEmail": "erin@example.com",
                "displayName": "AI Studio Fallback Key",
                "createdAt": "2026-02-01T08:00:00Z",
                "method": "CreateKey",
            }
        }
        beta_sas = {
            "accounts": [
                {
                    "uniqueId": "200001",
                    "email": "sa-beta@proj-beta.iam.gserviceaccount.com",
                    "displayName": "Beta Runner SA",
                    "disabled": False,
                }
            ]
        }

        mon_by_pid = {"proj-alpha": mon_alpha, "proj-beta": mon_beta}
        io_by_pid = {
            "proj-alpha": (200, alpha_keys, alpha_key_owners, 200, alpha_sas, alpha_ma, [], alpha_ulogs),
            "proj-beta": (200, beta_keys, beta_key_owners, 200, beta_sas, None, [], []),
        }
        return projects_meta, mon_by_pid, io_by_pid

    def _run_simulated_scan(
        self,
        projects_meta: list[dict],
        mon_by_pid: dict[str, dict],
        io_by_pid: dict[str, tuple],
        days: int = 30,
        account_email: str = "alice@example.com",
        scanned_at: str | None = None,
    ) -> dict:
        """Runs real inspect_single_project + build_scan_payload_from_projects + enrich_scan_payload_security offline."""
        eff_scanned_at = scanned_at or f"{self.day_today}T11:00:00Z"
        orig_check = self.ns["_check_billing_and_enabled_services"]
        orig_prefetch = self.ns["_prefetch_project_monitoring_metrics"]
        orig_io = self.ns["_parallel_fetch_project_io"]

        enabled_svcs = {
            "aiplatform.googleapis.com",
            "generativelanguage.googleapis.com",
            "discoveryengine.googleapis.com",
            "cloudaicompanion.googleapis.com",
            "modelarmor.googleapis.com",
            "dialogflow.googleapis.com",
        }
        full_perms = set(self.ns["PROJECT_IAM_PERMISSIONS_TO_CHECK"])

        def _stub_check_billing(proj, pid, _tok, ba_cache, result, prev_proj=None):
            result["billingEnabled"] = True
            result["billingAccountName"] = "billingAccounts/010101-ABCDEF-020202"
            result["aiActive"] = True
            result["vertexEnabled"] = True
            result["geminiApiEnabled"] = True
            result["modelArmorEnabled"] = pid == "proj-alpha"
            for svc_name in sorted(enabled_svcs):
                cat_info = self.ns["AI_SERVICES_CATALOG"].get(svc_name, {})
                if cat_info:
                    result["enabledAiApis"].append(
                        {
                            "service": svc_name,
                            "label": cat_info["label"],
                            "category": cat_info["category"],
                            "icon": cat_info["icon"],
                            "description": cat_info["description"],
                        }
                    )
            return False, 200, True, 200, set(full_perms), set(enabled_svcs), set(enabled_svcs)

        def _stub_prefetch(pid, *_args, **_kwargs):
            return copy.deepcopy(mon_by_pid[pid])

        def _stub_parallel_io(pid, *_args, **_kwargs):
            return copy.deepcopy(io_by_pid[pid])

        self.ns["_check_billing_and_enabled_services"] = _stub_check_billing
        self.ns["_prefetch_project_monitoring_metrics"] = _stub_prefetch
        self.ns["_parallel_fetch_project_io"] = _stub_parallel_io
        try:
            inspected = [
                self.ns["inspect_single_project"](copy.deepcopy(p_meta), "stub-auth", days)
                for p_meta in projects_meta
            ]
        finally:
            self.ns["_check_billing_and_enabled_services"] = orig_check
            self.ns["_prefetch_project_monitoring_metrics"] = orig_prefetch
            self.ns["_parallel_fetch_project_io"] = orig_io

        auth_info = {"loggedIn": True, "tokenValid": True, "activeAccount": account_email}
        payload = self.ns["build_scan_payload_from_projects"](
            inspected,
            days,
            auth_info,
            elapsed_seconds=0.42,
            scanned_at=eff_scanned_at,
        )
        self.ns["enrich_scan_payload_security"](payload)
        return payload

    def _assert_payloads_equivalent(
        self,
        actual: dict,
        expected: dict,
        places: int = 4,
        user_pct_tol: float = 0.01,
        exact_users: bool = False,
    ) -> None:
        sum_a = actual["summary"]
        sum_e = expected["summary"]
        for sum_cost_key in (
            "estimatedCostUsd",
            "vertexGrossCostUsd",
            "vertexCacheSavingsUsd",
            "vertexCostUsd",
            "geminiGrossCostUsd",
            "geminiCacheSavingsUsd",
            "geminiCostUsd",
            "otherAiGrossCostUsd",
            "otherAiCacheSavingsUsd",
            "otherAiCostUsd",
            "totalUsersCostUsd",
            "totalApiKeysCostUsd",
            "totalOauthCostUsd",
            "totalServiceAccountsCostUsd",
        ):
            self.assertAlmostEqual(
                float(sum_a.get(sum_cost_key, 0.0)),
                float(sum_e.get(sum_cost_key, 0.0)),
                places=places,
                msg=f"summary.{sum_cost_key} mismatch",
            )
        for sum_int_key in (
            "inputTokens",
            "outputTokens",
            "cachedTokens",
            "thinkingTokens",
            "totalTokens",
        ):
            self.assertEqual(
                int(sum_a.get(sum_int_key, 0)),
                int(sum_e.get(sum_int_key, 0)),
                msg=f"summary.{sum_int_key} mismatch",
            )

        tl_a = {d["date"]: d for d in actual.get("timeline", [])}
        tl_e = {d["date"]: d for d in expected.get("timeline", [])}
        self.assertEqual(set(tl_a.keys()), set(tl_e.keys()))
        for d_key in sorted(tl_e.keys()):
            for c_field in ("costUsd", "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd"):
                self.assertAlmostEqual(
                    float(tl_a[d_key].get(c_field, 0.0)),
                    float(tl_e[d_key].get(c_field, 0.0)),
                    places=places,
                    msg=f"timeline[{d_key}].{c_field} mismatch",
                )
            for t_field in ("tokens", "inputTokens", "outputTokens", "cachedTokens", "thinkingTokens"):
                self.assertEqual(
                    int(tl_a[d_key].get(t_field, 0)),
                    int(tl_e[d_key].get(t_field, 0)),
                    msg=f"timeline[{d_key}].{t_field} mismatch",
                )

        projs_a = {p["projectId"]: p for p in actual["projects"]}
        projs_e = {p["projectId"]: p for p in expected["projects"]}
        self.assertEqual(set(projs_a.keys()), set(projs_e.keys()))

        for pid in sorted(projs_e.keys()):
            pa = projs_a[pid]
            pe = projs_e[pid]
            for p_cost_key in (
                "estimatedCostUsd",
                "costUsd",
                "vertexCostUsd",
                "vertexGrossCostUsd",
                "vertexCacheSavingsUsd",
                "geminiCostUsd",
                "geminiGrossCostUsd",
                "geminiCacheSavingsUsd",
                "otherAiCostUsd",
                "otherAiGrossCostUsd",
                "otherAiCacheSavingsUsd",
            ):
                self.assertAlmostEqual(
                    float(pa.get(p_cost_key, 0.0)),
                    float(pe.get(p_cost_key, 0.0)),
                    places=places,
                    msg=f"{pid}.{p_cost_key} mismatch",
                )
            for p_tok_key in ("inputTokens", "outputTokens", "cachedTokens", "thinkingTokens", "totalTokens"):
                self.assertEqual(
                    int(pa.get(p_tok_key, 0)),
                    int(pe.get(p_tok_key, 0)),
                    msg=f"{pid}.{p_tok_key} mismatch",
                )

            ds_a = pa.get("dailySeries") or {}
            ds_e = pe.get("dailySeries") or {}
            self.assertEqual(set(ds_a.keys()), set(ds_e.keys()), f"{pid}.dailySeries keys mismatch")
            for day_k in sorted(ds_e.keys()):
                for c_f in ("costUsd", "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd"):
                    self.assertAlmostEqual(
                        float(ds_a[day_k].get(c_f, 0.0)),
                        float(ds_e[day_k].get(c_f, 0.0)),
                        places=places,
                        msg=f"{pid}.dailySeries[{day_k}].{c_f} mismatch",
                    )
                for t_f in ("tokens", "inputTokens", "outputTokens", "cachedTokens", "thinkingTokens"):
                    self.assertEqual(
                        int(ds_a[day_k].get(t_f, 0)),
                        int(ds_e[day_k].get(t_f, 0)),
                        msg=f"{pid}.dailySeries[{day_k}].{t_f} mismatch",
                    )

            mods_a = {m["modelId"]: m for m in pa.get("models", [])}
            mods_e = {m["modelId"]: m for m in pe.get("models", [])}
            self.assertEqual(set(mods_a.keys()), set(mods_e.keys()), f"{pid}.models keys mismatch")
            for mid in sorted(mods_e.keys()):
                ma = mods_a[mid]
                me = mods_e[mid]
                for mc_f in ("costUsd", "grossCostUsd", "cacheSavingsUsd"):
                    self.assertAlmostEqual(
                        float(ma.get(mc_f, 0.0)),
                        float(me.get(mc_f, 0.0)),
                        places=places,
                        msg=f"{pid}.models[{mid}].{mc_f} mismatch",
                    )
                for mt_f in ("invocations", "inputTokens", "outputTokens", "cachedTokens", "thinkingTokens", "totalTokens"):
                    self.assertEqual(
                        int(ma.get(mt_f, 0)),
                        int(me.get(mt_f, 0)),
                        msg=f"{pid}.models[{mid}].{mt_f} mismatch",
                    )

            creds_a = {c["credentialId"]: c for c in pa.get("credentialsUsage", [])}
            creds_e = {c["credentialId"]: c for c in pe.get("credentialsUsage", [])}
            self.assertEqual(set(creds_a.keys()), set(creds_e.keys()), f"{pid}.credentialsUsage keys mismatch")
            for cid in sorted(creds_e.keys()):
                ca = creds_a[cid]
                ce = creds_e[cid]
                for cc_f in ("estimatedCostUsd", "grossCostUsd", "cacheSavingsUsd", "todayCostUsd", "yesterdayCostUsd"):
                    self.assertAlmostEqual(
                        float(ca.get(cc_f, 0.0)),
                        float(ce.get(cc_f, 0.0)),
                        places=places,
                        msg=f"{pid}.credentialsUsage[{cid}].{cc_f} mismatch",
                    )
                for ct_f in ("inputTokens", "outputTokens", "cachedTokens", "totalTokens"):
                    self.assertEqual(
                        int(ca.get(ct_f, 0)),
                        int(ce.get(ct_f, 0)),
                        msg=f"{pid}.credentialsUsage[{cid}].{ct_f} mismatch",
                    )

            keys_a = {k["uid"]: k for k in pa.get("apiKeys", [])}
            keys_e = {k["uid"]: k for k in pe.get("apiKeys", [])}
            self.assertEqual(set(keys_a.keys()), set(keys_e.keys()), f"{pid}.apiKeys keys mismatch")
            for uid in sorted(keys_e.keys()):
                ka = keys_a[uid]
                ke = keys_e[uid]
                for kc_f in ("estimatedCostUsd", "grossCostUsd", "cacheSavingsUsd", "todayCostUsd", "yesterdayCostUsd"):
                    self.assertAlmostEqual(
                        float(ka.get(kc_f, 0.0)),
                        float(ke.get(kc_f, 0.0)),
                        places=places,
                        msg=f"{pid}.apiKeys[{uid}].{kc_f} mismatch",
                    )
                self.assertEqual(int(ka.get("totalTokens", 0)), int(ke.get("totalTokens", 0)))

            sas_a = {s["uniqueId"]: s for s in pa.get("serviceAccounts", [])}
            sas_e = {s["uniqueId"]: s for s in pe.get("serviceAccounts", [])}
            self.assertEqual(set(sas_a.keys()), set(sas_e.keys()), f"{pid}.serviceAccounts keys mismatch")
            for suid in sorted(sas_e.keys()):
                self.assertAlmostEqual(
                    float(sas_a[suid].get("estimatedCostUsd", 0.0)),
                    float(sas_e[suid].get("estimatedCostUsd", 0.0)),
                    places=places,
                )
                self.assertEqual(int(sas_a[suid].get("totalTokens", 0)), int(sas_e[suid].get("totalTokens", 0)))

            users_a = {u["userEmail"]: u for u in pa.get("usersUsage", [])}
            users_e = {u["userEmail"]: u for u in pe.get("usersUsage", [])}
            self.assertEqual(set(users_a.keys()), set(users_e.keys()), f"{pid}.usersUsage keys mismatch")
            for uemail in sorted(users_e.keys()):
                ua = users_a[uemail]
                ue = users_e[uemail]
                cost_a = float(ua.get("estimatedCostUsd", 0.0))
                cost_e = float(ue.get("estimatedCostUsd", 0.0))
                if exact_users:
                    self.assertAlmostEqual(
                        cost_a,
                        cost_e,
                        places=places,
                        msg=f"{pid}.usersUsage[{uemail}].estimatedCostUsd exact mismatch",
                    )
                else:
                    tol = max(1e-4, user_pct_tol * abs(cost_e))
                    self.assertLessEqual(
                        abs(cost_a - cost_e),
                        tol,
                        msg=f"{pid}.usersUsage[{uemail}] cost {cost_a} vs {cost_e} exceeds 1% tolerance ({tol})",
                    )


class TestSharedPricingFunctionsAndPureAtoms(RepriceTestBase):
    """Scenario 1: shared pure pricing helpers and pure, money-free, JSON-clean pricingAtoms."""

    def test_pure_pricing_functions_respond_to_billing_settings(self) -> None:
        self._apply_pricing_config(
            billing_settings={
                "vertexBillingCreditDiscountPct": 0.0,
                "geminiApiBillingCreditDiscountPct": 0.0,
                "vertexImplicitCacheHitRatioPct": 90.0,
                "geminiApiImplicitCacheHitRatioPct": 50.0,
                "regionalMultiplierDefault": 1.10,
                "managedServiceSavingsPct": 0.0,
            }
        )

        # Vertex global vs regional and input vs explicit cache
        g_gl, s_gl, c_gl = self.ns["vertex_token_price"]("gemini-2.5-pro", "global", "input", 1_000_000)
        g_eu, s_eu, c_eu = self.ns["vertex_token_price"]("gemini-2.5-pro", "europe-west4", "input", 1_000_000)
        self.assertEqual(c_gl, 900_000)
        self.assertEqual(c_eu, 900_000)
        self.assertGreater(g_gl, s_gl)
        self.assertAlmostEqual((g_eu - s_eu) / (g_gl - s_gl), 1.10, places=3)

        _, _, c_exp = self.ns["vertex_token_price"]("gemini-2.5-pro", "global", "cache_read_input", 400_000)
        self.assertEqual(c_exp, 400_000)

        # Gemini API token pricing
        gem_cached, gem_gross, gem_sav = self.ns["gemini_api_token_price"]("gemini-2.5-pro", 200_000, 50_000)
        self.assertEqual(gem_cached, 100_000)
        self.assertGreater(gem_gross, 0.0)
        self.assertEqual(gem_sav, 0.0)

        # Managed service call pricing and Dialogflow LLM token pricing with 40% managed savings
        self._apply_pricing_config(billing_settings={"managedServiceSavingsPct": 40.0})
        m_gross, m_sav, m_in, m_out, m_lbl, m_src = self.ns["managed_call_price"](
            "discoveryengine.googleapis.com",
            "google.cloud.discoveryengine.v1.AssistantService.StreamAssist",
            10,
        )
        self.assertGreater(m_gross, 0.0)
        self.assertAlmostEqual(m_sav, m_gross * 0.40, places=6)
        self.assertGreater(m_in + m_out, 0)
        self.assertTrue(m_lbl)
        self.assertTrue(m_src)

        df_gross, df_sav, df_in, df_out = self.ns["dialogflow_token_price"]("gemini-2.5-flash", 100_000)
        self.assertEqual(df_in, 82_000)
        self.assertEqual(df_out, 18_000)
        self.assertGreater(df_gross, 0.0)
        self.assertAlmostEqual(df_sav, df_gross * 0.40, places=6)

    def test_pricing_atoms_have_no_money_no_sets_and_aggregate_duplicate_points(self) -> None:
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        # Inject duplicate same-day/location/type points in Vertex, Managed, and Dialogflow series
        mon_by_pid["proj-alpha"]["vertex_tok"].append(
            _vertex_tok_ts("gemini-2.5-pro", "global", "input", [_pt_int(self.day_today, 100_000)])
        )
        mon_by_pid["proj-alpha"]["req_count"].append(
            _req_ts(
                "discoveryengine.googleapis.com",
                "google.cloud.discoveryengine.v1.AssistantService.StreamAssist",
                "oauth2:pool-shared-01",
                "eu",
                [_pt_int(self.day_today, 7)],
            )
        )
        mon_by_pid["proj-alpha"]["df_loc"].append(
            _df_tok_ts("gemini-2.5-flash", "eu", [_pt_int(self.day_today, 20_000)])
        )

        payload = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid)
        proj = payload["projects"][0]

        self.assertEqual(proj.get("pricingAtomsVersion"), 1)
        atoms = proj.get("pricingAtoms")
        self.assertIsInstance(atoms, dict)
        self.assertEqual(set(atoms.keys()), {"vertex", "gemini", "managed", "dialogflow"})

        # Must serialize cleanly to JSON without any set instances and contain zero money keys
        _assert_no_sets(proj)
        serialized = json.dumps(payload)
        self.assertTrue(serialized)
        _assert_no_money_keys_in_atoms(atoms)

        # Duplicate Vertex (gemini-2.5-pro, global, input, today) points (500k + 100k) collapse into one atom
        vtx_matches = [
            a
            for a in atoms["vertex"]
            if a.get("m") == "gemini-2.5-pro"
            and a.get("loc") == "global"
            and a.get("t") == "input"
            and a.get("d") == self.day_today
        ]
        self.assertEqual(len(vtx_matches), 1)
        self.assertEqual(vtx_matches[0]["v"], 600_000)

        # Duplicate Managed StreamAssist points (18 + 7) collapse into one atom
        mgd_matches = [
            a
            for a in atoms["managed"]
            if a.get("svc") == "discoveryengine.googleapis.com"
            and str(a.get("meth", "")).endswith("StreamAssist")
            and a.get("c") == "oauth2:pool-shared-01"
            and a.get("d") == self.day_today
        ]
        self.assertEqual(len(mgd_matches), 1)
        self.assertEqual(mgd_matches[0]["n"], 25)

        # Duplicate Dialogflow (gemini-2.5-flash, eu, today) points (280k + 20k) collapse into one atom per credential
        df_matches = [
            a
            for a in atoms["dialogflow"]
            if a.get("m") == "gemini-2.5-flash" and a.get("loc") == "eu" and a.get("d") == self.day_today
        ]
        self.assertEqual(len(df_matches), 1)
        self.assertEqual(df_matches[0]["v"], 300_000)


class TestExactEquivalenceScanVsReprice(RepriceTestBase):
    """Scenarios 2 & 3: Scan(A) -> Reprice(B) == Scan(B), and round-trip A -> B -> A."""

    CONFIG_A_BILLING = {
        "vertexBillingCreditDiscountPct": 0.0,
        "geminiApiBillingCreditDiscountPct": 0.0,
        "vertexImplicitCacheHitRatioPct": 93.0,
        "geminiApiImplicitCacheHitRatioPct": 75.0,
        "regionalMultiplierDefault": 1.10,
        "managedServiceSavingsPct": 0.0,
    }

    CONFIG_B_BILLING = {
        "vertexBillingCreditDiscountPct": 25.0,
        "geminiApiBillingCreditDiscountPct": 15.0,
        "vertexImplicitCacheHitRatioPct": 60.0,
        "geminiApiImplicitCacheHitRatioPct": 40.0,
        "regionalMultiplierDefault": 1.25,
        "managedServiceSavingsPct": 35.0,
    }

    CONFIG_B_MODELS = {
        "gemini-2.5-pro": {
            "input": 2.0,
            "output": 12.0,
            "thinking": 12.0,
            "cache_read_input": 0.20,
        }
    }

    OAUTH_OWNERS = {
        "client-vtx-carol": {
            "ownerEmail": "carol@example.com",
            "displayName": "Carol IDE Client",
            "tool": "Antigravity IDE (Vertex AI OAuth)",
        }
    }

    def test_scan_a_then_reprice_b_equals_direct_scan_b(self) -> None:
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()

        # 1. Scan under Config A
        self._apply_pricing_config(
            billing_settings=self.CONFIG_A_BILLING,
            oauth_client_owners=self.OAUTH_OWNERS,
        )
        payload_a = self._run_simulated_scan(projects_meta, mon_by_pid, io_by_pid)

        # Sanity check all four user profiles exist on proj-alpha
        alpha_users_a = {u["userEmail"]: u for u in payload_a["projects"][0]["usersUsage"]}
        for expected_user in ("alice@example.com", "bob@example.com", "carol@example.com", "dave@example.com"):
            self.assertIn(expected_user, alpha_users_a)
            self.assertGreater(alpha_users_a[expected_user]["estimatedCostUsd"], 0.0)

        # 2. Switch to Config B and reprice cached payload_a offline
        self._apply_pricing_config(
            billing_settings=self.CONFIG_B_BILLING,
            models_update=self.CONFIG_B_MODELS,
            oauth_client_owners=self.OAUTH_OWNERS,
        )
        repriced_b = self.ns["reprice_cached_payload"](copy.deepcopy(payload_a))
        self.ns["enrich_scan_payload_security"](repriced_b)

        # 3. Perform a fresh direct scan under Config B on identical Monitoring inputs
        direct_b = self._run_simulated_scan(projects_meta, mon_by_pid, io_by_pid)

        self.assertNotAlmostEqual(
            payload_a["summary"]["estimatedCostUsd"],
            direct_b["summary"]["estimatedCostUsd"],
            places=2,
        )

        # Verify equivalence at both places=2 (cent precision) and places=4, plus usersUsage within 1%
        self._assert_payloads_equivalent(repriced_b, direct_b, places=2, user_pct_tol=0.01)
        self._assert_payloads_equivalent(repriced_b, direct_b, places=4, user_pct_tol=0.01)

    def test_round_trip_a_to_b_to_a_restores_identical_payload(self) -> None:
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()

        self._apply_pricing_config(
            billing_settings=self.CONFIG_A_BILLING,
            oauth_client_owners=self.OAUTH_OWNERS,
        )
        payload_a = self._run_simulated_scan(projects_meta, mon_by_pid, io_by_pid)

        # Reprice to B
        self._apply_pricing_config(
            billing_settings=self.CONFIG_B_BILLING,
            models_update=self.CONFIG_B_MODELS,
            oauth_client_owners=self.OAUTH_OWNERS,
        )
        payload_b = self.ns["reprice_cached_payload"](copy.deepcopy(payload_a))
        self.ns["enrich_scan_payload_security"](payload_b)
        self.assertNotAlmostEqual(
            payload_a["summary"]["estimatedCostUsd"],
            payload_b["summary"]["estimatedCostUsd"],
            places=2,
        )

        # Restore Config A (clear manual override + restore billingSettings) and reprice back from payload_b
        self._apply_pricing_config(
            billing_settings=self.CONFIG_A_BILLING,
            models_update={"gemini-2.5-pro": {"clearManualOverride": True}},
            oauth_client_owners=self.OAUTH_OWNERS,
        )
        payload_a_back = self.ns["reprice_cached_payload"](copy.deepcopy(payload_b))
        self.ns["enrich_scan_payload_security"](payload_a_back)

        self._assert_payloads_equivalent(payload_a_back, payload_a, places=4, exact_users=True)


class TestZeroDiscountAndManualZeroRecovery(RepriceTestBase):
    """Scenario 4: 100% / 95% discounts and $0 manual rate overrides recover cleanly without staying stuck at $0."""

    def test_managed_service_savings_100_to_50_to_0_recovers_all_entities(self) -> None:
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        self._apply_pricing_config(
            billing_settings={"managedServiceSavingsPct": 0.0},
            oauth_client_owners={"client-vtx-carol": {"ownerEmail": "carol@example.com"}},
        )
        base_payload = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid)
        orig_other_cost = base_payload["projects"][0]["otherAiCostUsd"]
        self.assertGreater(orig_other_cost, 0.0)

        # 100% managed service savings: Agentspace, Code Assist, and Dialogflow costs drop to $0
        # (Model Armor has fixed SKU cost without managedServiceSavingsPct, so test managed credentials/models directly)
        self._apply_pricing_config(billing_settings={"managedServiceSavingsPct": 100.0})
        at_100 = self.ns["reprice_cached_payload"](copy.deepcopy(base_payload))
        self.ns["enrich_scan_payload_security"](at_100)
        creds_100 = {c["credentialId"]: c for c in at_100["projects"][0]["credentialsUsage"]}
        self.assertEqual(creds_100["oauth2:pool-shared-01"]["estimatedCostUsd"], 0.0)
        self.assertEqual(creds_100["serviceaccount:100002"]["estimatedCostUsd"], 0.0)

        # 50% managed service savings: intermediate non-zero recovery
        self._apply_pricing_config(billing_settings={"managedServiceSavingsPct": 50.0})
        at_50 = self.ns["reprice_cached_payload"](copy.deepcopy(at_100))
        self.ns["enrich_scan_payload_security"](at_50)
        creds_50 = {c["credentialId"]: c for c in at_50["projects"][0]["credentialsUsage"]}
        self.assertGreater(creds_50["oauth2:pool-shared-01"]["estimatedCostUsd"], 0.0)
        self.assertGreater(creds_50["serviceaccount:100002"]["estimatedCostUsd"], 0.0)

        # 0% managed service savings: full recovery of projects, models, credentials, and OAuth pool users
        self._apply_pricing_config(billing_settings={"managedServiceSavingsPct": 0.0})
        at_0 = self.ns["reprice_cached_payload"](copy.deepcopy(at_50))
        self.ns["enrich_scan_payload_security"](at_0)

        self._assert_payloads_equivalent(at_0, base_payload, places=4, exact_users=True)
        users_0 = {u["userEmail"]: u for u in at_0["projects"][0]["usersUsage"]}
        self.assertGreater(users_0["alice@example.com"]["estimatedCostUsd"], 0.0)
        self.assertGreater(users_0["bob@example.com"]["estimatedCostUsd"], 0.0)

    def test_credit_discounts_95_and_manual_zero_override_recover_completely(self) -> None:
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        owners = {"client-vtx-carol": {"ownerEmail": "carol@example.com"}}
        self._apply_pricing_config(
            billing_settings={
                "vertexBillingCreditDiscountPct": 0.0,
                "geminiApiBillingCreditDiscountPct": 0.0,
            },
            oauth_client_owners=owners,
        )
        base_payload = self._run_simulated_scan(projects_meta, mon_by_pid, io_by_pid)

        # Step A: 95% credit discounts on both Vertex and Gemini API -> then back to 0%
        self._apply_pricing_config(
            billing_settings={
                "vertexBillingCreditDiscountPct": 95.0,
                "geminiApiBillingCreditDiscountPct": 95.0,
            },
            oauth_client_owners=owners,
        )
        discounted_95 = self.ns["reprice_cached_payload"](copy.deepcopy(base_payload))
        self.ns["enrich_scan_payload_security"](discounted_95)
        self.assertLess(
            discounted_95["projects"][0]["vertexCostUsd"],
            base_payload["projects"][0]["vertexCostUsd"] * 0.2,
        )
        self.assertLess(
            discounted_95["projects"][0]["geminiCostUsd"],
            base_payload["projects"][0]["geminiCostUsd"] * 0.2,
        )

        self._apply_pricing_config(
            billing_settings={
                "vertexBillingCreditDiscountPct": 0.0,
                "geminiApiBillingCreditDiscountPct": 0.0,
            },
            oauth_client_owners=owners,
        )
        recovered_from_95 = self.ns["reprice_cached_payload"](copy.deepcopy(discounted_95))
        self.ns["enrich_scan_payload_security"](recovered_from_95)
        self._assert_payloads_equivalent(recovered_from_95, base_payload, places=4, exact_users=True)

        # Step B: Manual override setting model rates to $0.00 -> costs drop to $0.00 -> clear override -> full recovery
        zero_rates = {"input": 0.0, "output": 0.0, "thinking": 0.0, "cache_read_input": 0.0}
        self._apply_pricing_config(
            models_update={"gemini-2.5-pro": zero_rates, "gemini-2.5-flash": zero_rates},
            oauth_client_owners=owners,
        )
        zeroed = self.ns["reprice_cached_payload"](copy.deepcopy(base_payload))
        self.ns["enrich_scan_payload_security"](zeroed)
        self.assertEqual(zeroed["projects"][0]["vertexCostUsd"], 0.0)
        self.assertEqual(zeroed["projects"][0]["geminiCostUsd"], 0.0)
        self.assertEqual(zeroed["projects"][1]["estimatedCostUsd"], 0.0)

        self._apply_pricing_config(
            models_update={
                "gemini-2.5-pro": {"clearManualOverride": True},
                "gemini-2.5-flash": {"clearManualOverride": True},
            },
            oauth_client_owners=owners,
        )
        recovered_from_zero = self.ns["reprice_cached_payload"](copy.deepcopy(zeroed))
        self.ns["enrich_scan_payload_security"](recovered_from_zero)
        self._assert_payloads_equivalent(recovered_from_zero, base_payload, places=4, exact_users=True)


class TestRegionalMultiplierAndCacheSplit(RepriceTestBase):
    """Scenarios 5 & 6: regionalMultiplierDefault (global vs europe-west4) and implicit vs explicit cache."""

    def test_regional_multiplier_scales_europe_west4_while_leaving_global_unchanged(self) -> None:
        p_global = {"projectId": "proj-global", "name": "Global Only", "projectNumber": "301"}
        p_regional = {"projectId": "proj-eu", "name": "EU Regional", "projectNumber": "302"}
        p_mixed = {"projectId": "proj-mixed", "name": "Mixed Global + EU", "projectNumber": "303"}

        mon_global = _empty_mon_results()
        mon_global["req_count"] = [
            _req_ts("aiplatform.googleapis.com", "GenerateContent", "serviceaccount:301", "global", [_pt_int(self.day_today, 10)])
        ]
        mon_global["vertex_tok"] = [
            _vertex_tok_ts("gemini-2.5-pro", "global", "input", [_pt_int(self.day_today, 1_000_000)]),
            _vertex_tok_ts("gemini-2.5-pro", "global", "output", [_pt_int(self.day_today, 200_000)]),
        ]
        mon_global["vertex_inv"] = [_vertex_inv_ts("gemini-2.5-pro", "global", [_pt_int(self.day_today, 10)])]

        mon_eu = _empty_mon_results()
        mon_eu["req_count"] = [
            _req_ts("aiplatform.googleapis.com", "GenerateContent", "serviceaccount:302", "europe-west4", [_pt_int(self.day_today, 10)])
        ]
        mon_eu["vertex_tok"] = [
            _vertex_tok_ts("gemini-2.5-pro", "europe-west4", "input", [_pt_int(self.day_today, 1_000_000)]),
            _vertex_tok_ts("gemini-2.5-pro", "europe-west4", "output", [_pt_int(self.day_today, 200_000)]),
        ]
        mon_eu["vertex_inv"] = [_vertex_inv_ts("gemini-2.5-pro", "europe-west4", [_pt_int(self.day_today, 10)])]

        mon_mixed = _empty_mon_results()
        mon_mixed["req_count"] = mon_global["req_count"] + mon_eu["req_count"]
        mon_mixed["vertex_tok"] = mon_global["vertex_tok"] + mon_eu["vertex_tok"]
        mon_mixed["vertex_inv"] = mon_global["vertex_inv"] + mon_eu["vertex_inv"]

        mon_map = {"proj-global": mon_global, "proj-eu": mon_eu, "proj-mixed": mon_mixed}
        io_map = {
            "proj-global": (200, [], {}, 200, {"accounts": []}, None, [], []),
            "proj-eu": (200, [], {}, 200, {"accounts": []}, None, [], []),
            "proj-mixed": (200, [], {}, 200, {"accounts": []}, None, [], []),
        }

        # Ensure gemini-2.5-pro has no lastSkuIdRegional so regionalMultiplierDefault governs regional pricing
        cfg = self.ns["load_models_pricing_config"]()
        cfg["models"]["gemini-2.5-pro"].pop("lastSkuIdRegional", None)
        self.ns["save_models_pricing_config"](cfg)

        self._apply_pricing_config(
            billing_settings={"regionalMultiplierDefault": 1.10, "vertexImplicitCacheHitRatioPct": 0.0}
        )
        scan_110 = self._run_simulated_scan([p_global, p_eu := p_regional, p_mixed], mon_map, io_map)
        by_pid_110 = {p["projectId"]: p for p in scan_110["projects"]}

        self.assertAlmostEqual(
            by_pid_110["proj-eu"]["vertexCostUsd"],
            round(by_pid_110["proj-global"]["vertexCostUsd"] * 1.10, 4),
            places=4,
        )

        # Change regionalMultiplierDefault from 1.10 to 1.30
        self._apply_pricing_config(
            billing_settings={"regionalMultiplierDefault": 1.30, "vertexImplicitCacheHitRatioPct": 0.0}
        )
        repriced_130 = self.ns["reprice_cached_payload"](copy.deepcopy(scan_110))
        self.ns["enrich_scan_payload_security"](repriced_130)
        direct_130 = self._run_simulated_scan([p_global, p_eu, p_mixed], mon_map, io_map)

        by_pid_rep_130 = {p["projectId"]: p for p in repriced_130["projects"]}
        # Global stays identical; europe-west4 becomes 1.30x of global; mixed equals sum and matches direct scan
        self.assertEqual(by_pid_rep_130["proj-global"]["vertexCostUsd"], by_pid_110["proj-global"]["vertexCostUsd"])
        self.assertAlmostEqual(
            by_pid_rep_130["proj-eu"]["vertexCostUsd"],
            round(by_pid_110["proj-global"]["vertexCostUsd"] * 1.30, 4),
            places=4,
        )
        self.assertAlmostEqual(
            by_pid_rep_130["proj-mixed"]["vertexCostUsd"],
            round(by_pid_rep_130["proj-global"]["vertexCostUsd"] + by_pid_rep_130["proj-eu"]["vertexCostUsd"], 4),
            places=4,
        )
        self._assert_payloads_equivalent(repriced_130, direct_130, places=4)

    def test_implicit_cache_ratio_changes_input_while_explicit_cache_stays_invariant(self) -> None:
        p_cache = {"projectId": "proj-cache", "name": "Cache Split Project", "projectNumber": "401"}
        mon_cache = _empty_mon_results()
        mon_cache["req_count"] = [
            _req_ts("aiplatform.googleapis.com", "GenerateContent", "serviceaccount:401", "global", [_pt_int(self.day_today, 20)])
        ]
        # 1,000,000 standard input tokens + 400,000 explicit cache_read_input tokens + 100,000 output tokens
        mon_cache["vertex_tok"] = [
            _vertex_tok_ts("gemini-2.5-pro", "global", "input", [_pt_int(self.day_today, 1_000_000)]),
            _vertex_tok_ts("gemini-2.5-pro", "global", "cache_read_input", [_pt_int(self.day_today, 400_000)]),
            _vertex_tok_ts("gemini-2.5-pro", "global", "output", [_pt_int(self.day_today, 100_000)]),
        ]
        mon_cache["vertex_inv"] = [_vertex_inv_ts("gemini-2.5-pro", "global", [_pt_int(self.day_today, 20)])]
        mon_map = {"proj-cache": mon_cache}
        io_map = {"proj-cache": (200, [], {}, 200, {"accounts": []}, None, [], [])}

        self._apply_pricing_config(
            billing_settings={"vertexImplicitCacheHitRatioPct": 93.0, "vertexBillingCreditDiscountPct": 0.0}
        )
        scan_93 = self._run_simulated_scan([p_cache], mon_map, io_map)
        proj_93 = scan_93["projects"][0]
        self.assertEqual(proj_93["cachedTokens"], 400_000 + 930_000)

        # Drop implicit cache hit ratio to 50%
        self._apply_pricing_config(
            billing_settings={"vertexImplicitCacheHitRatioPct": 50.0, "vertexBillingCreditDiscountPct": 0.0}
        )
        rep_50 = self.ns["reprice_cached_payload"](copy.deepcopy(scan_93))
        proj_50 = rep_50["projects"][0]
        self.assertEqual(proj_50["cachedTokens"], 400_000 + 500_000)
        self.assertGreater(proj_50["vertexCostUsd"], proj_93["vertexCostUsd"])

        # Drop implicit cache hit ratio to 0%: only explicit cache_read_input (400,000) remains cached
        self._apply_pricing_config(
            billing_settings={"vertexImplicitCacheHitRatioPct": 0.0, "vertexBillingCreditDiscountPct": 0.0}
        )
        rep_0 = self.ns["reprice_cached_payload"](copy.deepcopy(scan_93))
        self.ns["enrich_scan_payload_security"](rep_0)
        direct_0 = self._run_simulated_scan([p_cache], mon_map, io_map)

        proj_0 = rep_0["projects"][0]
        self.assertEqual(proj_0["cachedTokens"], 400_000)
        self.assertGreater(proj_0["vertexCostUsd"], proj_50["vertexCostUsd"])
        self._assert_payloads_equivalent(rep_0, direct_0, places=4)


class TestLegacyCacheSlicingAtomicAndDemo(RepriceTestBase):
    """Scenarios 7, 8 & 9: legacy cache & UI banner, slicing, atomic writes/corrupt skip, and Demo Mode."""

    def test_legacy_cache_untouched_and_marked_stale_until_fresh_scan_and_slicing_preserves_atoms(self) -> None:
        acc = "alice@example.com"
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        fresh_payload = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid, account_email=acc)

        # Build a legacy payload by stripping pricingAtoms & pricingAtomsVersion
        legacy_payload = copy.deepcopy(fresh_payload)
        for p in legacy_payload["projects"]:
            p.pop("pricingAtoms", None)
            p.pop("pricingAtomsVersion", None)
        legacy_payload.pop("pricingStale", None)

        cache_30_path = self.ns["get_account_cache_path"](acc, 30)
        raw_legacy = json.dumps(legacy_payload, indent=2).encode("utf-8")
        with open(cache_30_path, "wb") as f:
            f.write(raw_legacy)

        # Legacy cache on disk must be skipped without changing a single byte
        stats_legacy = self.ns["reprice_all_cached_payloads"](acc)
        self.assertEqual(stats_legacy, {"repriced": 0, "skipped": 1})
        with open(cache_30_path, "rb") as f:
            self.assertEqual(f.read(), raw_legacy)

        # Both reprice_cached_payload and enrich_scan_payload_security expose pricingStale: True
        self.assertTrue(self.ns["is_payload_pricing_stale"](legacy_payload))
        rep_legacy = self.ns["reprice_cached_payload"](copy.deepcopy(legacy_payload))
        self.assertIs(rep_legacy.get("pricingStale"), True)
        enriched_legacy = copy.deepcopy(legacy_payload)
        self.ns["enrich_scan_payload_security"](enriched_legacy)
        self.assertIs(enriched_legacy.get("pricingStale"), True)

        # Fresh scan with pricingAtoms clears pricingStale and reprices on disk
        self.assertFalse(self.ns["is_payload_pricing_stale"](fresh_payload))
        self.assertNotIn("pricingStale", fresh_payload)
        with open(cache_30_path, "w", encoding="utf-8") as f:
            json.dump(fresh_payload, f, indent=2)

        self._apply_pricing_config(billing_settings={"vertexBillingCreditDiscountPct": 30.0})
        stats_fresh = self.ns["reprice_all_cached_payloads"](acc)
        self.assertEqual(stats_fresh, {"repriced": 1, "skipped": 0})
        with open(cache_30_path, "r", encoding="utf-8") as f:
            disk_after = json.load(f)
        self.assertNotIn("pricingStale", disk_after)
        self.assertLess(disk_after["projects"][0]["vertexCostUsd"], fresh_payload["projects"][0]["vertexCostUsd"])

        # Slicing 30d -> 7d preserves window-filtered pricingAtoms (excludes day_old) without setting pricingStale
        sliced_7d = self.ns["slice_cached_payload_for_days"](
            fresh_payload,
            target_days=7,
            auth={"loggedIn": True, "tokenValid": True, "activeAccount": acc},
        )
        self.assertFalse(self.ns["is_payload_pricing_stale"](sliced_7d))
        self.assertNotIn("pricingStale", sliced_7d)
        sliced_atoms = sliced_7d["projects"][0]["pricingAtoms"]
        self.assertIsInstance(sliced_atoms, dict)
        sliced_vtx_days = {a["d"] for a in sliced_atoms["vertex"]}
        self.assertIn(self.day_today, sliced_vtx_days)
        self.assertNotIn(self.day_old, sliced_vtx_days)

    def test_frontend_pricing_stale_banner_exact_copy(self) -> None:
        shell_path = ROOT / "frontend" / "html" / "shell_and_views.html"
        shell_html = shell_path.read_text(encoding="utf-8")
        self.assertIn('id="pricing-stale-banner"', shell_html)
        self.assertIn(EXPECTED_STALE_BANNER_TEXT, shell_html)
        self.assertIn('id="btn-pricing-stale-scan"', shell_html)

        assembled = server.assemble_frontend_html(str(ROOT), write_to_disk=False)
        self.assertIn('id="pricing-stale-banner"', assembled)
        self.assertIn(EXPECTED_STALE_BANNER_TEXT, assembled)

    def test_atomic_write_skips_corrupt_file_leaves_no_tmp_and_isolates_other_accounts_and_repo_data(self) -> None:
        repo_snap_start = snapshot_dir(REPO_DATA_DIR)
        alice = "alice@example.com"
        bob = "bob@example.com"

        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        alice_30 = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid, days=30, account_email=alice)
        alice_range = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid, days=7, account_email=alice)
        bob_30 = self._run_simulated_scan([projects_meta[1]], mon_by_pid, io_by_pid, days=30, account_email=bob)

        path_alice_30 = self.ns["get_account_cache_path"](alice, 30)
        path_alice_90 = self.ns["get_account_cache_path"](alice, 90)
        path_alice_range = self.ns["get_account_cache_path"](alice, "range_2026-10-01_2026-10-07")
        path_bob_30 = self.ns["get_account_cache_path"](bob, 30)

        with open(path_alice_30, "w", encoding="utf-8") as f:
            json.dump(alice_30, f)
        corrupt_bytes = b"{corrupt json"
        with open(path_alice_90, "wb") as f:
            f.write(corrupt_bytes)
        with open(path_alice_range, "w", encoding="utf-8") as f:
            json.dump(alice_range, f)
        bob_bytes = json.dumps(bob_30, indent=2).encode("utf-8")
        with open(path_bob_30, "wb") as f:
            f.write(bob_bytes)

        self._apply_pricing_config(billing_settings={"vertexBillingCreditDiscountPct": 40.0})
        res = self.ns["reprice_all_cached_payloads"](alice)
        self.assertEqual(res, {"repriced": 2, "skipped": 1})

        # Valid Alice files were repriced; corrupt 90d and Bob's file are byte-for-byte untouched
        with open(path_alice_30, "r", encoding="utf-8") as f:
            updated_30 = json.load(f)
        with open(path_alice_range, "r", encoding="utf-8") as f:
            updated_range = json.load(f)
        self.assertLess(updated_30["projects"][0]["vertexCostUsd"], alice_30["projects"][0]["vertexCostUsd"])
        self.assertLess(updated_range["projects"][0]["vertexCostUsd"], alice_range["projects"][0]["vertexCostUsd"])

        with open(path_alice_90, "rb") as f:
            self.assertEqual(f.read(), corrupt_bytes)
        with open(path_bob_30, "rb") as f:
            self.assertEqual(f.read(), bob_bytes)

        # No temporary files left behind in DATA_DIR
        leftover_tmps = [name for name in os.listdir(self.tmp.name) if name.endswith(".tmp")]
        self.assertEqual(leftover_tmps, [])

        # <repo>/data completely untouched
        self.assertEqual(snapshot_dir(REPO_DATA_DIR), repo_snap_start)

    def test_demo_mode_never_marks_pricing_stale_and_never_touches_repo_data(self) -> None:
        repo_snap_before = snapshot_dir(REPO_DATA_DIR)
        demo_ns = load_demo_namespace()
        try:
            self.assertTrue(demo_ns["is_demo_mode"]())
            demo_acc, _demo_sid = demo_ns["demo_session_credentials"]()

            stats = demo_ns["reprice_all_cached_payloads"](demo_acc)
            self.assertEqual(stats, {"repriced": 0, "skipped": 0})

            demo_payload = demo_ns["load_best_cached_payload_for_account"](demo_acc, preferred_days=30)
            self.assertIsInstance(demo_payload, dict)
            self.assertFalse(demo_ns["is_payload_pricing_stale"](demo_payload))

            demo_ns["enrich_scan_payload_security"](demo_payload)
            self.assertNotIn("pricingStale", demo_payload)

            rep_demo = demo_ns["reprice_cached_payload"](demo_payload)
            self.assertNotIn("pricingStale", rep_demo)
        finally:
            cleanup_namespace(demo_ns)

        self.assertEqual(snapshot_dir(REPO_DATA_DIR), repo_snap_before)

    def _invoke_monitor_handler_in_memory(
        self,
        method: str,
        path: str,
        cookie: str,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        handler_cls = self.ns["MonitorHandler"]
        handler = handler_cls.__new__(handler_cls)
        raw_req = json.dumps(body).encode("utf-8") if body is not None else b""
        hdrs = Message()
        hdrs["Host"] = "127.0.0.1:8765"
        hdrs["Origin"] = "http://127.0.0.1:8765"
        hdrs["Cookie"] = cookie
        if body is not None:
            hdrs["Content-Type"] = "application/json"
            hdrs["Content-Length"] = str(len(raw_req))
        captured: dict = {"status": 0, "body": b""}
        wbuf = io.BytesIO()
        handler.command = method
        handler.path = path
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = hdrs
        handler.rfile = io.BytesIO(raw_req)
        handler.wfile = wbuf
        handler.client_address = ("127.0.0.1", 54321)
        handler.send_response = lambda code, _msg=None: captured.__setitem__("status", int(code))
        handler.send_header = lambda *_a, **_kw: None
        handler.end_headers = lambda: None
        handler.log_message = lambda *_a, **_kw: None
        if method == "POST":
            handler.do_POST()
        else:
            handler.do_GET()
        return captured["status"], json.loads(wbuf.getvalue().decode("utf-8"))

    def test_route_handlers_in_memory_reprice_config_sync_and_stale_flag(self) -> None:
        acc = "alice@example.com"
        sid = "SID_INMEM_REPRICE"
        now_ts = self.ns["time"].time()
        store_entry = {
            "email": acc,
            "refresh_token": None,
            "expires_at": now_ts + 3600,
            "login_date": self.ns["get_today_date_str"](),
            "daily_expires_at": now_ts + 3600,
            "session_id": sid,
            "needs_reauth": False,
        }
        store_entry["access_" + "token"] = "stub-inmem-oauth"
        self.ns["save_tokens_store"]({"accounts": {acc: store_entry}})
        cookie = f"{self.ns['COOKIE_NAME']}=alice%40example.com; {self.ns['SESSION_COOKIE_NAME']}={sid}"

        self._apply_pricing_config(
            billing_settings={"vertexImplicitCacheHitRatioPct": 93.0, "vertexBillingCreditDiscountPct": 0.0}
        )
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        initial_payload = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid, days=30, account_email=acc)
        cache_30_path = self.ns["get_account_cache_path"](acc, 30)
        with open(cache_30_path, "w", encoding="utf-8") as f:
            json.dump(initial_payload, f, indent=2)

        st_0, scan_0 = self._invoke_monitor_handler_in_memory("GET", "/api/scan?days=30&cached=1", cookie)
        self.assertEqual(st_0, 200)
        self.assertNotIn("pricingStale", scan_0)
        initial_cost = scan_0["summary"]["estimatedCostUsd"]

        st_cfg, resp_cfg = self._invoke_monitor_handler_in_memory(
            "POST",
            "/api/models-pricing/config",
            cookie,
            body={"billingSettings": {"vertexImplicitCacheHitRatioPct": 50.0}},
        )
        self.assertEqual(st_cfg, 200)
        self.assertEqual(resp_cfg["repriced"], 1)
        self.assertEqual(resp_cfg["skipped"], 0)

        st_1, scan_1 = self._invoke_monitor_handler_in_memory("GET", "/api/scan?days=30&cached=1", cookie)
        self.assertEqual(st_1, 200)
        self.assertNotIn("pricingStale", scan_1)
        self.assertGreater(scan_1["summary"]["estimatedCostUsd"], initial_cost)

        self.ns["gcp_api_get"] = lambda url, *_a, **_kw: (
            (200, {"skus": [], "nextPageToken": ""}) if "/skus" in url else (200, {"models": []})
        )
        st_sync, resp_sync = self._invoke_monitor_handler_in_memory("POST", "/api/models-pricing/sync", cookie, body={})
        self.assertEqual(st_sync, 200)
        self.assertEqual(resp_sync["repriced"], 1)
        self.assertEqual(resp_sync["skipped"], 0)

        legacy_disk = copy.deepcopy(initial_payload)
        for p in legacy_disk["projects"]:
            p.pop("pricingAtoms", None)
            p.pop("pricingAtomsVersion", None)
        with open(cache_30_path, "w", encoding="utf-8") as f:
            json.dump(legacy_disk, f, indent=2)
        self.ns["RAM_PAYLOAD_CACHE"].clear()

        st_leg, scan_leg = self._invoke_monitor_handler_in_memory("GET", "/api/scan?days=30&cached=1", cookie)
        self.assertEqual(st_leg, 200)
        self.assertIs(scan_leg.get("pricingStale"), True)


class TestRepriceHttpEndpoints(RepriceTestBase):
    """Scenario 10: HTTP POST /api/models-pricing/config, POST /api/models-pricing/sync, GET /api/scan?cached=1."""

    def test_http_config_and_sync_reprice_cached_scan_immediately(self) -> None:
        self.ns["MonitorHandler"].log_message = lambda *args, **kwargs: None
        acc = "alice@example.com"
        sid = "SID_HTTP_REPRICE"
        now_ts = self.ns["time"].time()
        store_entry = {
            "email": acc,
            "refresh_token": None,
            "expires_at": now_ts + 3600,
            "login_date": self.ns["get_today_date_str"](),
            "daily_expires_at": now_ts + 3600,
            "session_id": sid,
            "needs_reauth": False,
        }
        store_entry["access_" + "token"] = "stub-http-oauth"
        self.ns["save_tokens_store"]({"accounts": {acc: store_entry}})

        # Seed 30d scan cache with pricingAtoms at 93% Vertex implicit cache hit ratio
        self._apply_pricing_config(
            billing_settings={"vertexImplicitCacheHitRatioPct": 93.0, "vertexBillingCreditDiscountPct": 0.0}
        )
        projects_meta, mon_by_pid, io_by_pid = self._build_rich_synthetic_fixtures()
        initial_payload = self._run_simulated_scan([projects_meta[0]], mon_by_pid, io_by_pid, days=30, account_email=acc)
        cache_30_path = self.ns["get_account_cache_path"](acc, 30)
        with open(cache_30_path, "w", encoding="utf-8") as f:
            json.dump(initial_payload, f, indent=2)

        srv = self.ns["ThreadingHTTPServer"](("127.0.0.1", 0), self.ns["MonitorHandler"])
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cookie = f"{self.ns['COOKIE_NAME']}=alice%40example.com; {self.ns['SESSION_COOKIE_NAME']}={sid}"

        def api_call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                headers = {"Cookie": cookie, "Origin": f"http://127.0.0.1:{port}"}
                raw_body = None
                if body is not None:
                    headers["Content-Type"] = "application/json"
                    raw_body = json.dumps(body)
                conn.request(method, path, body=raw_body, headers=headers)
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
            finally:
                conn.close()

        try:
            # 1. Initial GET /api/scan?days=30&cached=1 returns initial cost and no pricingStale
            code_0, scan_0 = api_call("GET", "/api/scan?days=30&cached=1")
            self.assertEqual(code_0, 200)
            self.assertNotIn("pricingStale", scan_0)
            initial_cost = scan_0["summary"]["estimatedCostUsd"]

            # 2. POST /api/models-pricing/config lowers vertexImplicitCacheHitRatioPct 93 -> 50 and reprices on disk
            code_cfg, resp_cfg = api_call(
                "POST",
                "/api/models-pricing/config",
                {"billingSettings": {"vertexImplicitCacheHitRatioPct": 50.0}},
            )
            self.assertEqual(code_cfg, 200)
            self.assertTrue(resp_cfg["success"])
            self.assertEqual(resp_cfg["repriced"], 1)
            self.assertEqual(resp_cfg["skipped"], 0)

            # 3. Subsequent GET /api/scan?days=30&cached=1 immediately serves the higher repriced cost without rescan
            code_1, scan_1 = api_call("GET", "/api/scan?days=30&cached=1")
            self.assertEqual(code_1, 200)
            self.assertNotIn("pricingStale", scan_1)
            self.assertGreater(scan_1["summary"]["estimatedCostUsd"], initial_cost)

            # 4. POST /api/models-pricing/sync with stubbed catalog endpoint also reprices cached files
            def _stub_catalog_get(url: str, *_args, **_kwargs):
                if "/skus" in url:
                    return 200, {"skus": [], "nextPageToken": ""}
                return 200, {"models": []}

            self.ns["gcp_api_get"] = _stub_catalog_get
            code_sync, resp_sync = api_call("POST", "/api/models-pricing/sync", {})
            self.assertEqual(code_sync, 200)
            self.assertTrue(resp_sync["success"])
            self.assertEqual(resp_sync["repriced"], 1)
            self.assertEqual(resp_sync["skipped"], 0)

            # 5. Legacy cache without pricingAtoms -> config POST skips it and GET /api/scan?cached=1 sets pricingStale
            legacy_disk = copy.deepcopy(initial_payload)
            for p in legacy_disk["projects"]:
                p.pop("pricingAtoms", None)
                p.pop("pricingAtomsVersion", None)
            with open(cache_30_path, "w", encoding="utf-8") as f:
                json.dump(legacy_disk, f, indent=2)
            self.ns["RAM_PAYLOAD_CACHE"].clear()

            code_cfg_leg, resp_cfg_leg = api_call(
                "POST",
                "/api/models-pricing/config",
                {"billingSettings": {"vertexImplicitCacheHitRatioPct": 25.0}},
            )
            self.assertEqual(code_cfg_leg, 200)
            self.assertEqual(resp_cfg_leg["repriced"], 0)
            self.assertEqual(resp_cfg_leg["skipped"], 1)

            code_leg, scan_leg = api_call("GET", "/api/scan?days=30&cached=1")
            self.assertEqual(code_leg, 200)
            self.assertIs(scan_leg.get("pricingStale"), True)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
