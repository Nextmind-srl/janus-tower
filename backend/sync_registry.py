SYNC_REGISTRY_FILE = os.path.join(DATA_DIR, "projects_sync_registry.json")


def get_account_cache_path(account_email: str, days: int = 30) -> str:
    if not account_email:
        return CACHE_FILE
    safe = "".join(c if c.isalnum() else "_" for c in account_email.lower())
    return os.path.join(DATA_DIR, f"scan_cache_v9_{safe}_{days}d.json")


def project_has_ai_data(p: dict) -> bool:
    """
    Determines whether a project should be active in 'Da Scansionare' (scanEnabled = True).
    Rule requested by user:
    - If a project has core AI APIs enabled (even with 0 traffic/data) OR has AI data -> 'Da Scansionare' (scanEnabled = True)
    - Only if a project does NOT have core AI APIs enabled and has no AI data -> 'Non Scansionare' (scanEnabled = False)
    """
    if not p or not isinstance(p, dict):
        return False
    if p.get("aiActive") or p.get("vertexEnabled") or p.get("geminiApiEnabled") or p.get("modelArmorEnabled"):
        return True
    enabled_apis = p.get("enabledAiApis") or []
    if any((a.get("service") if isinstance(a, dict) else str(a)) in CORE_AI_SERVICE_NAMES for a in enabled_apis):
        return True
    if (p.get("estimatedCostUsd", 0.0) or 0.0) > 0:
        return True
    if (p.get("totalBillCostUsd", 0.0) or 0.0) > 0:
        return True
    if (p.get("totalRequests", 0) or 0) > 0 or (p.get("inferenceRequests", 0) or 0) > 0:
        return True
    if (p.get("totalTokens", 0) or 0) > 0:
        return True
    if len(p.get("models", []) or []) > 0:
        return True
    if len(p.get("usersUsage", []) or []) > 0:
        return True
    if len(p.get("deployedAiResources", []) or []) > 0:
        return True
    if len(p.get("apiKeys", []) or []) > 0:
        return True
    for c in (p.get("credentialsUsage", []) or []):
        if (c.get("inferenceRequests", 0) or 0) > 0 or (c.get("estimatedCostUsd", 0.0) or 0.0) > 0:
            return True
    return False


def get_project_data_reason(p: dict) -> str:
    if not p or not isinstance(p, dict):
        return "No data"
    reasons = []
    enabled_apis = p.get("enabledAiApis", []) or []
    if p.get("scanStatus") == "SKIPPED_NO_AI_API" and not p.get("aiActive"):
        apis_cnt = sum(1 for a in enabled_apis if (a.get("service") if isinstance(a, dict) else str(a)) in CORE_AI_SERVICE_NAMES)
    else:
        apis_cnt = len(enabled_apis)
    cost = p.get("estimatedCostUsd", 0.0) or 0.0
    reqs = p.get("inferenceRequests", 0) or p.get("totalRequests", 0) or 0
    toks = p.get("totalTokens", 0) or 0
    models_cnt = len(p.get("models", []) or [])
    users_cnt = len(p.get("usersUsage", []) or [])
    res_cnt = len(p.get("deployedAiResources", []) or [])
    if apis_cnt > 0:
        reasons.append(f"{apis_cnt} APIs enabled")
    if cost > 0:
        reasons.append(f"AI cost ${cost:.2f}")
    if reqs > 0:
        reasons.append(f"{reqs:,} calls")
    if toks > 0:
        reasons.append(f"{toks:,} tokens")
    if models_cnt > 0:
        reasons.append(f"{models_cnt} models")
    if users_cnt > 0:
        reasons.append(f"{users_cnt} users")
    if res_cnt > 0:
        reasons.append(f"{res_cnt} apps/resources")
    if reasons:
        return " · ".join(reasons[:3])
    if p.get("skippedNoBilling"):
        return "No active Billing ($0)"
    if p.get("scanStatus") == "NO_PERMISSIONS_403":
        return "Missing IAM permissions (403)"
    if p.get("aiActive"):
        return "AI APIs enabled (0 traffic in the period)"
    return "No AI APIs enabled"


# Reasons saved by versions of the app that wrote Italian text; shown in English without rewriting the file by hand
LEGACY_DATA_REASONS = {
    "Nessuna API AI abilitata": "No AI APIs enabled",
    "Nessun dato AI rilevato (0 costi, 0 token, 0 risorse)": "No AI data detected (0 costs, 0 tokens, 0 resources)",
}


def _normalize_legacy_reasons(reg: dict) -> dict:
    for acc in (reg.get("accounts") or {}).values():
        projects = acc.get("projects") if isinstance(acc, dict) else None
        for entry in (projects or {}).values():
            if isinstance(entry, dict) and entry.get("dataReason") in LEGACY_DATA_REASONS:
                entry["dataReason"] = LEGACY_DATA_REASONS[entry["dataReason"]]
    return reg


def load_sync_registry() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SYNC_REGISTRY_FILE):
        with contextlib.suppress(OSError, ValueError, TypeError):
            with open(SYNC_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "accounts" in data:
                    return _normalize_legacy_reasons(data)
    return {"accounts": {}, "updatedAt": datetime.now(timezone.utc).isoformat()}


def save_sync_registry(reg: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    reg["updatedAt"] = datetime.now(timezone.utc).isoformat()
    with contextlib.suppress(OSError, ValueError, TypeError):
        with open(SYNC_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2, ensure_ascii=False)


# Scan results that must not be reused for a rate-limited project (they may be the old misclassification)
NOT_REUSABLE_SCAN_STATUSES = ("ERROR", "SKIPPED_NO_BILLING", "BILLING_PERMISSION_DENIED", "NO_PERMISSIONS_403")


def purge_account_local_data(account_email: str) -> dict:
    """
    Deletes the local scan data of ONE account (it can contain personal data: user emails from audit logs,
    Agentspace licenses and session metadata): its cache files in data/, its sync-registry entry and the
    in-memory copies. OAuth login and budgets are kept. Other accounts' files are never touched.
    """
    global LAST_LIVE_SCAN_RESULT
    if not account_email:
        return {"success": False, "error": "Missing account"}
    with SCAN_PROGRESS_LOCK:
        if SCAN_PROGRESS.get("active") and SCAN_PROGRESS.get("account") == account_email:
            return {"success": False, "scanInProgress": True,
                    "error": "Scan in progress for this account: wait for it to finish and try again."}

    # Exact file-name match: same pattern as get_account_cache_path(), so "a@x.com" never matches "a@x.com.it".
    safe = "".join(c if c.isalnum() else "_" for c in account_email.lower())
    own_cache_re = re.compile(r"^scan_cache_v9_" + re.escape(safe) + r"_(\d+|range_[^_]{1,10}_[^_]{1,10})d\.json$")
    deleted, kept_other_owner = [], []
    with contextlib.suppress(OSError):
        for fname in sorted(os.listdir(DATA_DIR)):
            if not own_cache_re.match(fname):
                continue
            fpath = os.path.join(DATA_DIR, fname)
            owner = None
            with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
                with open(fpath, "r", encoding="utf-8") as f:
                    owner = (json.load(f).get("auth") or {}).get("activeAccount")
            if owner and owner != account_email:
                # Different account whose email maps to the same file name: not ours, leave it.
                kept_other_owner.append(fname)
                continue
            with contextlib.suppress(OSError):
                os.remove(fpath)
                deleted.append(fname)

    reg = load_sync_registry()
    registry_entry_removed = reg.get("accounts", {}).pop(account_email, None) is not None
    if registry_entry_removed:
        save_sync_registry(reg)

    RAM_PAYLOAD_CACHE.clear()
    if isinstance(LAST_LIVE_SCAN_RESULT, dict) and (LAST_LIVE_SCAN_RESULT.get("auth") or {}).get("activeAccount") == account_email:
        LAST_LIVE_SCAN_RESULT = None

    return {
        "success": True,
        "account": account_email,
        "deletedFiles": len(deleted),
        "registryEntryRemoved": registry_entry_removed,
        "skippedOtherAccountFiles": len(kept_other_owner)
    }


def load_best_cached_payload_for_account(account_email: str, preferred_days: int = 30) -> dict | None:
    if not account_email:
        return None
    candidate_days = [preferred_days, 30, 90, 14, 7, 60, 180, 365]
    seen = set()
    for d in candidate_days:
        if d in seen:
            continue
        seen.add(d)
        p_path = get_account_cache_path(account_email, d)
        if os.path.exists(p_path):
            with contextlib.suppress(OSError, ValueError, TypeError):
                with open(p_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("projects") and data.get("auth", {}).get("activeAccount") == account_email:
                    return data
    return None


def update_registry_entry_from_project(acc_projects: dict, p: dict, scanned_at: str, is_new: bool = False, preserve_manual: bool = True, force_auto_rule: bool = False) -> dict:
    pid = p.get("projectId", "")
    existing = acc_projects.get(pid, {})
    is_err = p.get("scanStatus") == "ERROR"
    has_data = project_has_ai_data(p)
    reason = get_project_data_reason(p)

    # If a transient scan error occurred, preserve previous API/data status instead of disabling the project
    if is_err and existing:
        if existing.get("scanStatus") == "SKIPPED_NO_AI_API" and not existing.get("aiActive", False):
            has_data = False
            reason = "No AI APIs enabled"
        else:
            has_data = bool(existing.get("hasAiData", False) or existing.get("aiActive", False) or (existing.get("enabledApisCount", 0) or 0) > 0)
            reason = existing.get("dataReason") or reason
    elif is_err and p.get("transientError"):
        # New project that Google rate-limited: include it so the next scan verifies it, never auto-exclude on a 429
        has_data = True
        reason = "Check not completed (Google request limit): will retry on the next scan"

    existing_rule = existing.get("scanRule", "")
    is_manual = existing_rule in ("MANUAL_INCLUDE", "MANUAL_EXCLUDE") and preserve_manual and not force_auto_rule

    if is_manual:
        scan_enabled = existing.get("scanEnabled", has_data)
        scan_rule = existing_rule
    else:
        scan_enabled = True if has_data else False
        scan_rule = "AUTO_INCLUDE_HAS_DATA" if has_data else "AUTO_EXCLUDE_NO_DATA"

    enabled_apis = p.get("enabledAiApis", []) or []
    if p.get("scanStatus") == "SKIPPED_NO_AI_API" and not p.get("aiActive"):
        apis_cnt = sum(1 for a in enabled_apis if (a.get("service") if isinstance(a, dict) else str(a)) in CORE_AI_SERVICE_NAMES)
    else:
        apis_cnt = len(enabled_apis) or (existing.get("enabledApisCount", 0) if is_err else 0)

    entry = {
        "projectId": pid,
        "name": p.get("name") or existing.get("name") or pid,
        "hasAiData": has_data,
        "scanEnabled": bool(scan_enabled),
        "scanRule": scan_rule,
        "dataReason": reason,
        "isNewProject": bool(is_new or existing.get("isNewProject", False)),
        "firstSeenAt": existing.get("firstSeenAt") or scanned_at,
        "lastScannedAt": scanned_at,
        "billingEnabled": bool(existing.get("billingEnabled", False)) if (is_err and existing) else bool(p.get("billingEnabled", existing.get("billingEnabled", False))),
        "skippedNoBilling": bool(existing.get("skippedNoBilling", False)) if (is_err and existing) else bool(p.get("skippedNoBilling", existing.get("skippedNoBilling", False))),
        "aiActive": bool(p.get("aiActive", False) or (is_err and existing.get("aiActive", False))),
        "scanStatus": (existing.get("scanStatus") if (is_err and existing and existing.get("scanStatus") not in (None, "", "ERROR")) else p.get("scanStatus", "OK")),
        "estimatedCostUsd": round(p.get("estimatedCostUsd", 0.0) or 0.0, 4),
        "totalBillCostUsd": round(p.get("totalBillCostUsd", p.get("estimatedCostUsd", 0.0)) or 0.0, 4),
        "inferenceRequests": int(p.get("inferenceRequests", 0) or 0),
        "totalRequests": int(p.get("totalRequests", 0) or 0),
        "totalTokens": int(p.get("totalTokens", 0) or 0),
        "modelsCount": len(p.get("models", []) or []),
        "usersCount": len(p.get("usersUsage", []) or []),
        "resourcesCount": len(p.get("deployedAiResources", []) or []),
        "apiKeysCount": len(p.get("apiKeys", []) or []),
        "serviceAccountsCount": len(p.get("serviceAccounts", []) or []),
        "enabledApisCount": apis_cnt
    }
    acc_projects[pid] = entry
    return entry


def ensure_account_sync_registry(account_email: str) -> dict:
    reg = load_sync_registry()
    if not account_email:
        return reg
    acc_reg = reg.setdefault("accounts", {}).setdefault(account_email, {
        "account": account_email,
        "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
        "lastSyncAt": None,
        "newProjectsDetected": [],
        "projects": {}
    })
    changed = False
    # Bootstrap or enrich from existing 90d and 30d caches if empty
    if not acc_reg.get("projects"):
        for d in (90, 30, 14, 7):
            c_path = get_account_cache_path(account_email, d)
            if os.path.exists(c_path):
                with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                    with open(c_path, "r", encoding="utf-8") as f:
                        c_data = json.load(f)
                    scanned_at = c_data.get("scannedAt") or datetime.now(timezone.utc).isoformat()
                    for p in c_data.get("projects", []):
                        pid = p.get("projectId")
                        if not pid:
                            continue
                        prev = acc_reg["projects"].get(pid)
                        if not prev or (not prev.get("hasAiData") and project_has_ai_data(p)):
                            update_registry_entry_from_project(
                                acc_reg["projects"], p, scanned_at, is_new=False, preserve_manual=True
                            )
                            changed = True
                    if not acc_reg.get("lastSyncAt"):
                        acc_reg["lastSyncAt"] = scanned_at
    else:
        cached_clean_by_pid = {}
        for d in (30, 90, 14, 7):
            c_path = get_account_cache_path(account_email, d)
            if os.path.exists(c_path):
                with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                    with open(c_path, "r", encoding="utf-8") as f:
                        c_data = json.load(f)
                    for cp in (c_data.get("projects") or []):
                        cp_id = cp.get("projectId")
                        if cp_id and cp_id not in cached_clean_by_pid and cp.get("scanStatus") != "ERROR" and not cp.get("transientError"):
                            cached_clean_by_pid[cp_id] = cp

        # Self-heal registry entries:
        # 1) Heal transient ERROR entries using clean cached project data
        # 2) Demote SKIPPED_NO_AI_API projects that only had support APIs (e.g. iap.googleapis.com)
        # 3) Ensure real AI-active projects stay included even with 0 traffic in a short window
        for _pid, entry in list(acc_reg.get("projects", {}).items()):
            if entry.get("scanStatus") == "ERROR" and _pid in cached_clean_by_pid:
                entry = update_registry_entry_from_project(
                    acc_reg["projects"],
                    cached_clean_by_pid[_pid],
                    entry.get("lastScannedAt") or datetime.now(timezone.utc).isoformat(),
                    is_new=False,
                    preserve_manual=True
                )
                changed = True

            is_skipped_no_ai = (
                entry.get("scanStatus") == "SKIPPED_NO_AI_API"
                and not entry.get("aiActive", False)
                and (entry.get("estimatedCostUsd", 0.0) or 0.0) == 0
                and (entry.get("inferenceRequests", 0) or 0) == 0
                and (entry.get("resourcesCount", 0) or 0) == 0
                and (entry.get("modelsCount", 0) or 0) == 0
            )
            if is_skipped_no_ai:
                if entry.get("hasAiData") or (entry.get("enabledApisCount", 0) or 0) > 0 or entry.get("scanRule") == "AUTO_INCLUDE_HAS_DATA":
                    entry["enabledApisCount"] = 0
                    entry["hasAiData"] = False
                    entry["dataReason"] = "No AI APIs enabled"
                    if entry.get("scanRule") == "AUTO_INCLUDE_HAS_DATA":
                        entry["scanEnabled"] = False
                        entry["scanRule"] = "AUTO_EXCLUDE_NO_DATA"
                    changed = True
                continue

            has_apis_or_data = bool(
                entry.get("hasAiData", False)
                or entry.get("aiActive", False)
                or (entry.get("enabledApisCount", 0) or 0) > 0
                or (entry.get("apiKeysCount", 0) or 0) > 0
                or (entry.get("resourcesCount", 0) or 0) > 0
                or (entry.get("estimatedCostUsd", 0.0) or 0.0) > 0
                or (entry.get("inferenceRequests", 0) or 0) > 0
            )
            if has_apis_or_data and not entry.get("hasAiData"):
                entry["hasAiData"] = True
                if entry.get("scanRule") == "AUTO_EXCLUDE_NO_DATA":
                    entry["scanEnabled"] = True
                    entry["scanRule"] = "AUTO_INCLUDE_HAS_DATA"
                if entry.get("dataReason") in (None, "", "No AI data detected (0 costs, 0 tokens, 0 resources)"):
                    api_cnt = int(entry.get("enabledApisCount", 0) or 0)
                    entry["dataReason"] = f"{api_cnt} AI APIs enabled (0 traffic in the period)" if api_cnt > 0 else "AI APIs enabled on project (0 traffic in the period)"
                changed = True
    if changed:
        save_sync_registry(reg)
    return reg


def build_sync_summary_for_account(account_email: str, reg: dict = None) -> dict:
    if reg is None:
        reg = ensure_account_sync_registry(account_email)
    acc_reg = reg.get("accounts", {}).get(account_email, {})
    projects_map = acc_reg.get("projects", {})
    projects_list = list(projects_map.values())
    projects_list.sort(
        key=lambda x: (
            bool(x.get("isNewProject", False)),
            bool(x.get("scanEnabled", False)),
            bool(x.get("hasAiData", False)),
            x.get("estimatedCostUsd", 0.0),
            x.get("totalTokens", 0),
            x.get("inferenceRequests", 0),
            x.get("projectId", "")
        ),
        reverse=True
    )
    included = [p for p in projects_list if p.get("scanEnabled")]
    excluded = [p for p in projects_list if not p.get("scanEnabled")]
    with_data = [p for p in projects_list if p.get("hasAiData")]
    without_data = [p for p in projects_list if not p.get("hasAiData")]
    manual_overrides = [p for p in projects_list if str(p.get("scanRule", "")).startswith("MANUAL_")]
    new_projects = [p for p in projects_list if p.get("isNewProject")]

    return {
        "account": account_email,
        "lastSyncAt": acc_reg.get("lastSyncAt"),
        "totalSynchronized": len(projects_list),
        "includedToScanCount": len(included),
        "excludedFromScanCount": len(excluded),
        "withAiDataCount": len(with_data),
        "withoutAiDataCount": len(without_data),
        "manualOverridesCount": len(manual_overrides),
        "newProjectsCount": len(new_projects),
        "newProjectsDetected": acc_reg.get("newProjectsDetected", []),
        "projects": projects_list
    }


def sort_inspected_projects(inspected: list[dict]):
    inspected.sort(
        key=lambda x: (
            not x.get("skippedNoBilling", False),
            bool(x.get("aiActive", False)),
            x.get("scanStatus") != "NO_PERMISSIONS_403",
            x.get("estimatedCostUsd", 0.0),
            x.get("totalTokens", 0),
            x.get("inferenceRequests", 0),
            len(x.get("deployedAiResources", [])),
            bool(x.get("modelArmorEnabled", False)),
            x.get("totalRequests", 0),
            len(x.get("apiKeys", [])),
            x.get("projectId", "")
        ),
        reverse=True
    )


def build_scan_payload_from_projects(
    inspected: list[dict],
    days: int,
    auth: dict,
    elapsed_seconds: float,
    scanned_at: str = None,
    sync_meta: dict = None
) -> dict:
    sort_inspected_projects(inspected)

    total_vertex_reqs = sum(p.get("vertexRequests", 0) for p in inspected)
    total_gemini_reqs = sum(p.get("geminiApiRequests", 0) for p in inspected)
    total_inf_reqs = sum(p.get("inferenceRequests", 0) for p in inspected)
    total_sys_reqs = sum(p.get("systemRequests", 0) for p in inspected)
    total_reqs = sum(p.get("totalRequests", 0) for p in inspected)
    total_429 = sum(p.get("errors429", 0) for p in inspected)
    total_tokens = sum(p.get("totalTokens", 0) for p in inspected)
    total_input_tokens = sum(p.get("inputTokens", 0) for p in inspected)
    total_output_tokens = sum(p.get("outputTokens", 0) for p in inspected)
    total_cached_tokens = sum(p.get("cachedTokens", 0) for p in inspected)
    total_thinking_tokens = sum(p.get("thinkingTokens", 0) for p in inspected)
    total_vertex_gross_cost = round(sum(p.get("vertexGrossCostUsd", p.get("vertexCostUsd", 0.0)) for p in inspected), 4)
    total_vertex_cache_savings = round(sum(p.get("vertexCacheSavingsUsd", 0.0) for p in inspected), 4)
    total_vertex_cost = round(sum(p.get("vertexCostUsd", 0.0) for p in inspected), 4)
    total_gemini_gross_cost = round(sum(p.get("geminiGrossCostUsd", p.get("geminiCostUsd", 0.0)) for p in inspected), 4)
    total_gemini_cache_savings = round(sum(p.get("geminiCacheSavingsUsd", 0.0) for p in inspected), 4)
    total_gemini_cost = round(sum(p.get("geminiCostUsd", 0.0) for p in inspected), 4)
    total_other_ai_gross_cost = round(sum(p.get("otherAiGrossCostUsd", p.get("otherAiCostUsd", 0.0)) for p in inspected), 4)
    total_other_ai_cache_savings = round(sum(p.get("otherAiCacheSavingsUsd", 0.0) for p in inspected), 4)
    total_other_ai_cost = round(sum(p.get("otherAiCostUsd", 0.0) for p in inspected), 4)
    total_cost_usd = round(sum(p.get("estimatedCostUsd", 0.0) for p in inspected), 4)
    total_infra_gross_cost = round(sum(p.get("infraGrossCostUsd", 0.0) for p in inspected), 4)
    total_infra_savings = round(sum(p.get("infraSavingsUsd", 0.0) for p in inspected), 4)
    total_infra_cost = round(sum(p.get("infraCostUsd", 0.0) for p in inspected), 4)
    total_bill_gross_usd = round(sum(p.get("totalBillGrossUsd", p.get("estimatedCostUsd", 0.0)) for p in inspected), 4)
    total_bill_savings_usd = round(sum(p.get("totalBillSavingsUsd", 0.0) for p in inspected), 4)
    total_bill_cost_usd = round(sum(p.get("totalBillCostUsd", p.get("estimatedCostUsd", 0.0)) for p in inspected), 4)

    billed_projects_count = sum(1 for p in inspected if p.get("billingEnabled"))
    skipped_no_billing_count = sum(1 for p in inspected if p.get("skippedNoBilling"))
    ai_enabled_projects_count = sum(1 for p in inspected if p.get("aiActive"))
    no_perms_projects_count = sum(1 for p in inspected if p.get("scanStatus") == "NO_PERMISSIONS_403")
    partial_perms_projects_count = sum(
        1 for p in inspected
        if p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403" and p.get("permissions", {}).get("accessLevel") == "PARTIAL"
    )
    full_perms_projects_count = sum(
        1 for p in inspected
        if p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403" and p.get("permissions", {}).get("accessLevel") == "FULL"
    )
    billing_account_direct_access = any(
        p.get("permissions", {}).get("areas", {}).get("billingCosts", {}).get("granted", False)
        for p in inspected if p.get("billingEnabled")
    )
    hidden_no_ai_count = sum(
        1 for p in inspected
        if p.get("billingEnabled") and not p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403"
        and not p.get("transientError")
    )
    active_traffic_projects = sum(
        1 for p in inspected
        if p.get("totalRequests", 0) > 0 or p.get("totalTokens", 0) > 0
    )
    model_armor_projects_count = sum(1 for p in inspected if p.get("modelArmorEnabled"))
    total_deployed_resources = sum(len(p.get("deployedAiResources", [])) for p in inspected)
    total_api_keys = sum(len(p.get("apiKeys", [])) for p in inspected)
    total_service_accounts = sum(len(p.get("serviceAccounts", [])) for p in inspected)

    unique_users_set = set()
    total_users_cost_usd = 0.0
    total_api_keys_cost_usd = 0.0
    total_oauth_cost_usd = 0.0
    total_sa_cost_usd = 0.0
    for p in inspected:
        for u in p.get("usersUsage", []):
            if u.get("userEmail"):
                unique_users_set.add(u["userEmail"])
            total_users_cost_usd += u.get("estimatedCostUsd", 0.0)
        for c in p.get("credentialsUsage", []):
            ctype = c.get("resolvedType", "")
            ccost = c.get("estimatedCostUsd", 0.0)
            if ctype == "API_KEY":
                total_api_keys_cost_usd += ccost
            elif ctype == "SERVICE_ACCOUNT":
                total_sa_cost_usd += ccost
            else:
                total_oauth_cost_usd += ccost

    global_daily = {}
    for p in inspected:
        for day_str, d_val in p.get("dailySeries", {}).items():
            g_d = global_daily.setdefault(day_str, {"date": day_str, **empty_day_bucket()})
            for k_num in ("requests", "inferenceRequests", "systemRequests", "vertexRequests", "geminiApiRequests", "ok200", "errors429", "tokens", "inputTokens", "outputTokens", "cachedTokens", "thinkingTokens"):
                g_d[k_num] += d_val.get(k_num, 0)
            g_d["costUsd"] = round(g_d["costUsd"] + d_val.get("costUsd", 0.0), 4)
            g_d["vertexCostUsd"] = round(g_d["vertexCostUsd"] + d_val.get("vertexCostUsd", 0.0), 4)
            g_d["geminiCostUsd"] = round(g_d["geminiCostUsd"] + d_val.get("geminiCostUsd", 0.0), 4)
            g_d["otherAiCostUsd"] = round(g_d["otherAiCostUsd"] + d_val.get("otherAiCostUsd", 0.0), 4)

    timeline = [global_daily[k] for k in sorted(global_daily.keys())]

    payload = {
        "success": True,
        "scannedAt": scanned_at or datetime.now(timezone.utc).isoformat(),
        "elapsedSeconds": round(elapsed_seconds, 2),
        "days": days,
        "auth": {
            "accounts": auth.get("accounts", []),
            "activeAccount": auth.get("activeAccount"),
            "tokenValid": bool(auth.get("tokenValid", True))
        },
        "summary": {
            "totalProjects": len(inspected),
            "billedProjects": billed_projects_count,
            "skippedNoBillingProjects": skipped_no_billing_count,
            "aiEnabledProjects": ai_enabled_projects_count,
            "hiddenNoAiProjects": hidden_no_ai_count,
            "noMonitoringAccessProjects": no_perms_projects_count,
            "partialAccessProjects": partial_perms_projects_count,
            "fullAccessProjects": full_perms_projects_count,
            "billingAccountDirectAccess": billing_account_direct_access,
            "activeAiProjects": active_traffic_projects,
            "modelArmorProjects": model_armor_projects_count,
            "totalDeployedAiResources": total_deployed_resources,
            "totalRequests": total_reqs,
            "inferenceRequests": total_inf_reqs,
            "systemRequests": total_sys_reqs,
            "vertexRequests": total_vertex_reqs,
            "geminiApiRequests": total_gemini_reqs,
            "errors429": total_429,
            "totalTokens": total_tokens,
            "inputTokens": total_input_tokens,
            "outputTokens": total_output_tokens,
            "cachedTokens": total_cached_tokens,
            "thinkingTokens": total_thinking_tokens,
            "vertexGrossCostUsd": total_vertex_gross_cost,
            "vertexCacheSavingsUsd": total_vertex_cache_savings,
            "vertexCostUsd": total_vertex_cost,
            "geminiGrossCostUsd": total_gemini_gross_cost,
            "geminiCacheSavingsUsd": total_gemini_cache_savings,
            "geminiCostUsd": total_gemini_cost,
            "otherAiGrossCostUsd": total_other_ai_gross_cost,
            "otherAiCacheSavingsUsd": total_other_ai_cache_savings,
            "otherAiCostUsd": total_other_ai_cost,
            "estimatedCostUsd": total_cost_usd,
            "infraGrossCostUsd": total_infra_gross_cost,
            "infraSavingsUsd": total_infra_savings,
            "infraCostUsd": total_infra_cost,
            "totalBillGrossUsd": total_bill_gross_usd,
            "totalBillSavingsUsd": total_bill_savings_usd,
            "totalBillCostUsd": total_bill_cost_usd,
            "totalApiKeys": total_api_keys,
            "totalServiceAccounts": total_service_accounts,
            "totalActiveUsers": len(unique_users_set),
            "totalUsersCostUsd": round(total_users_cost_usd, 4),
            "totalApiKeysCostUsd": round(total_api_keys_cost_usd, 4),
            "totalOauthCostUsd": round(total_oauth_cost_usd, 4),
            "totalServiceAccountsCostUsd": round(total_sa_cost_usd, 4)
        },
        "timeline": timeline,
        "projects": inspected
    }
    if sync_meta:
        payload["sync"] = sync_meta
    enrich_scan_payload_security(payload)
    return payload


def slice_cached_payload_for_days(
    base_payload: dict,
    target_days: int,
    auth: dict,
    start_date: str = None,
    end_date: str = None,
    preset: str = None
) -> dict:
    """
    Derives a scan payload for `target_days` or an exact `[start_date, end_date]` range (`today`, `yesterday`,
    `single`, `custom`, or numeric `days`) from an existing cached payload (e.g. 30d or 90d)
    without making ANY live GCP requests, so switching period filters stays 100% instant and cached!
    Slices project dailySeries, models[].dailySeries, credentialsUsage[].dailySeries, apiKeys, usersUsage, and infraServices.
    """
    import copy

    def _share_when_net_zero(orig_series: dict, win_series: dict, keys_chain: tuple) -> float:
        """Quota della finestra quando il netto originale e' 0 ma il risparmio originale e' > 0
        (es. managedServiceSavingsPct=100: lordo pieno, netto 0, rapporto sui costi indefinito).
        Usa la prima grandezza della catena con totale originale > 0 (token, poi richieste di
        inferenza, poi richieste): sono presenti in ogni bucket giornaliero e proporzionali all'uso."""
        def _qty(bucket: dict, keys: tuple) -> float:
            # per bucket: primo alias valorizzato (es. totalTokens oppure tokens)
            for k in keys:
                val = float(bucket.get(k, 0) or 0)
                if val > 0:
                    return val
            return 0.0

        for keys in keys_chain:
            o_tot = sum(_qty(v, keys) for v in orig_series.values())
            if o_tot > 0:
                return min(1.0, sum(_qty(v, keys) for v in win_series.values()) / o_tot)
        return 0.0

    cloned_projects = copy.deepcopy(base_payload.get("projects", []))
    base_days = max(1, int(base_payload.get("days", 30) or 30))

    # Anchor cutoff_date on scannedAt first (fallback to latest date in dailySeries) so quiet recent days are included in the window
    max_date_str = None
    scanned_at_raw = str(base_payload.get("scannedAt") or "").strip()
    if len(scanned_at_raw) >= 10 and scanned_at_raw[:4].isdigit():
        max_date_str = scanned_at_raw[:10]
    for p in cloned_projects:
        for d_k in (p.get("dailySeries") or {}).keys():
            if not max_date_str or d_k > max_date_str:
                max_date_str = d_k
    if not max_date_str:
        for t_item in (base_payload.get("timeline") or []):
            d_k = t_item.get("date")
            if d_k and (not max_date_str or d_k > max_date_str):
                max_date_str = d_k
    try:
        if max_date_str:
            anchor_dt = datetime.strptime(max_date_str[:10], "%Y-%m-%d")
        else:
            anchor_dt = datetime.now()
    except Exception:
        anchor_dt = datetime.now()

    preset_clean = (preset or "").strip().lower()
    if preset_clean == "today" and not start_date:
        t_str = datetime.now().strftime("%Y-%m-%d")
        start_date = t_str
        end_date = t_str
    elif preset_clean == "yesterday" and not start_date:
        y_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = y_str
        end_date = y_str

    if start_date or end_date:
        s_clean = str(start_date or end_date).strip()[:10]
        e_clean = str(end_date or start_date).strip()[:10]
        if s_clean > e_clean:
            s_clean, e_clean = e_clean, s_clean
        cutoff_date = s_clean
        end_date_str = e_clean
        try:
            s_dt = datetime.strptime(cutoff_date, "%Y-%m-%d")
            e_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
            target_days = max(1, (e_dt - s_dt).days + 1)
        except Exception:
            target_days = max(1, int(target_days or 1))
    else:
        target_days = max(1, int(target_days or 30))
        cutoff_date = (anchor_dt - timedelta(days=max(0, target_days - 1))).strftime("%Y-%m-%d")
        end_date_str = anchor_dt.strftime("%Y-%m-%d")

    for p in cloned_projects:
        p["scanDays"] = target_days
        orig_reqs = int(p.get("totalRequests", 0) or 0)
        orig_inf_reqs = int(p.get("inferenceRequests", 0) or 0)
        orig_toks = int(p.get("totalTokens", 0) or 0)
        orig_cost = float(p.get("estimatedCostUsd", 0.0) or 0.0)
        orig_v_cost = float(p.get("vertexCostUsd", 0.0) or 0.0)
        orig_v_sav = float(p.get("vertexCacheSavingsUsd", 0.0) or 0.0)
        orig_g_cost = float(p.get("geminiCostUsd", 0.0) or 0.0)
        orig_g_sav = float(p.get("geminiCacheSavingsUsd", 0.0) or 0.0)
        orig_o_cost = float(p.get("otherAiCostUsd", 0.0) or 0.0)
        orig_o_sav = float(p.get("otherAiCacheSavingsUsd", 0.0) or 0.0)

        ds = p.get("dailySeries", {})
        if ds:
            orig_ds_all = dict(ds)
            filtered_ds = {k: v for k, v in ds.items() if cutoff_date <= k <= end_date_str}
            p["dailySeries"] = filtered_ds
            p["totalRequests"] = sum(v.get("requests", 0) for v in filtered_ds.values())
            p["inferenceRequests"] = sum(v.get("inferenceRequests", 0) for v in filtered_ds.values())
            p["systemRequests"] = sum(v.get("systemRequests", 0) for v in filtered_ds.values())
            p["vertexRequests"] = sum(v.get("vertexRequests", 0) for v in filtered_ds.values())
            p["geminiApiRequests"] = sum(v.get("geminiApiRequests", 0) for v in filtered_ds.values())
            p["errors429"] = sum(v.get("errors429", 0) for v in filtered_ds.values())
            p["totalTokens"] = sum(v.get("tokens", 0) for v in filtered_ds.values())
            p["inputTokens"] = sum(v.get("inputTokens", 0) for v in filtered_ds.values())
            p["outputTokens"] = sum(v.get("outputTokens", 0) for v in filtered_ds.values())
            p["cachedTokens"] = sum(v.get("cachedTokens", 0) for v in filtered_ds.values())
            p["thinkingTokens"] = sum(v.get("thinkingTokens", 0) for v in filtered_ds.values())
            p["vertexCostUsd"] = round(sum(v.get("vertexCostUsd", 0.0) for v in filtered_ds.values()), 4)
            p["geminiCostUsd"] = round(sum(v.get("geminiCostUsd", 0.0) for v in filtered_ds.values()), 4)
            p["otherAiCostUsd"] = round(sum(v.get("otherAiCostUsd", 0.0) for v in filtered_ds.values()), 4)
            p["estimatedCostUsd"] = round(sum(v.get("costUsd", 0.0) for v in filtered_ds.values()), 4)

            # Netto originale 0 ma risparmio > 0: quota da richieste del bucket (vertex/gemini) o token/inferenze (other)
            v_ratio = (p["vertexCostUsd"] / orig_v_cost) if orig_v_cost > 0 else (
                _share_when_net_zero(orig_ds_all, filtered_ds, (("vertexRequests",), ("tokens",), ("inferenceRequests",))) if orig_v_sav > 0 else 0.0)
            g_ratio = (p["geminiCostUsd"] / orig_g_cost) if orig_g_cost > 0 else (
                _share_when_net_zero(orig_ds_all, filtered_ds, (("geminiApiRequests",), ("tokens",), ("inferenceRequests",))) if orig_g_sav > 0 else 0.0)
            o_ratio = (p["otherAiCostUsd"] / orig_o_cost) if orig_o_cost > 0 else (
                _share_when_net_zero(orig_ds_all, filtered_ds, (("tokens",), ("inferenceRequests",), ("requests",))) if orig_o_sav > 0 else 0.0)
            p["vertexCacheSavingsUsd"] = round(orig_v_sav * v_ratio, 4)
            p["vertexGrossCostUsd"] = round(p["vertexCostUsd"] + p["vertexCacheSavingsUsd"], 4)
            p["geminiCacheSavingsUsd"] = round(orig_g_sav * g_ratio, 4)
            p["geminiGrossCostUsd"] = round(p["geminiCostUsd"] + p["geminiCacheSavingsUsd"], 4)
            p["otherAiCacheSavingsUsd"] = round(orig_o_sav * o_ratio, 4)
            p["otherAiGrossCostUsd"] = round(p["otherAiCostUsd"] + p["otherAiCacheSavingsUsd"], 4)

        win_ratio = min(1.0, float(target_days) / float(base_days))
        cost_ratio = (p.get("estimatedCostUsd", 0.0) / orig_cost) if orig_cost > 0 else (0.0 if ds else win_ratio)
        req_ratio = (p.get("totalRequests", 0) / orig_reqs) if orig_reqs > 0 else (0.0 if ds else win_ratio)
        inf_ratio = (p.get("inferenceRequests", 0) / orig_inf_reqs) if orig_inf_reqs > 0 else req_ratio
        tok_ratio = (p.get("totalTokens", 0) / orig_toks) if orig_toks > 0 else cost_ratio

        if req_ratio < 0.999:
            for err_k in ("errors403", "errors400", "errors5xx", "errorsOther", "ok200", "adminWriteEvents", "securityEvents"):
                if p.get(err_k, 0) > 0:
                    p[err_k] = int(round(float(p.get(err_k, 0) or 0) * req_ratio))
            p.pop("httpStatusBreakdown", None)

        if req_ratio < 0.999 or inf_ratio < 0.999:
            for vf in (p.get("vertexFeatures") or []):
                if vf.get("requests", 0) > 0:
                    vf["requests"] = int(round(vf.get("requests", 0) * req_ratio))
                if vf.get("inferenceRequests", 0) > 0:
                    vf["inferenceRequests"] = int(round(vf.get("inferenceRequests", 0) * inf_ratio))

        # Slice models[].dailySeries (note: dailySeries buckets use inferenceRequests/requests and tokens)
        for m_obj in (p.get("models") or []):
            m_ds = m_obj.get("dailySeries") or {}
            if m_ds:
                orig_m_cost = float(m_obj.get("costUsd", 0.0) or 0.0)
                orig_m_sav = float(m_obj.get("cacheSavingsUsd", 0.0) or 0.0)
                f_mds = {k: v for k, v in m_ds.items() if cutoff_date <= k <= end_date_str}
                orig_m_ds_all = m_ds
                m_obj["dailySeries"] = f_mds
                if any(v.get("tokensEstimatedFromBytes") for v in f_mds.values()):
                    m_obj["tokensEstimatedFromBytes"] = True
                else:
                    m_obj.pop("tokensEstimatedFromBytes", None)
                m_obj["invocations"] = sum(v.get("invocations", v.get("inferenceRequests", v.get("requests", 0))) for v in f_mds.values())
                m_obj["inputTokens"] = sum(v.get("inputTokens", 0) for v in f_mds.values())
                m_obj["outputTokens"] = sum(v.get("outputTokens", 0) for v in f_mds.values())
                m_obj["cachedTokens"] = sum(v.get("cachedTokens", 0) for v in f_mds.values())
                m_obj["thinkingTokens"] = sum(v.get("thinkingTokens", 0) for v in f_mds.values())
                m_obj["totalTokens"] = sum(v.get("totalTokens", v.get("tokens", 0)) for v in f_mds.values())
                m_obj["costUsd"] = round(sum(v.get("costUsd", 0.0) for v in f_mds.values()), 4)
                m_rat = (m_obj["costUsd"] / orig_m_cost) if orig_m_cost > 0 else (
                    _share_when_net_zero(orig_m_ds_all, f_mds, (("totalTokens", "tokens"), ("invocations", "inferenceRequests", "requests"))) if orig_m_sav > 0 else 0.0)
                m_obj["cacheSavingsUsd"] = round(orig_m_sav * m_rat, 4)
                m_obj["grossCostUsd"] = round(m_obj["costUsd"] + m_obj["cacheSavingsUsd"], 4)
        if p.get("models"):
            p["models"].sort(key=lambda x: (x.get("costUsd", 0.0), x.get("totalTokens", 0), x.get("invocations", 0)), reverse=True)

        # Slice credentialsUsage[].dailySeries and sync apiKeys
        sliced_creds_by_id = {}
        for c_obj in (p.get("credentialsUsage") or []):
            c_ds = c_obj.get("dailySeries") or {}
            if c_ds:
                orig_c_cost = float(c_obj.get("estimatedCostUsd", 0.0) or 0.0)
                orig_c_sav = float(c_obj.get("cacheSavingsUsd", 0.0) or 0.0)
                f_cds = {k: v for k, v in c_ds.items() if cutoff_date <= k <= end_date_str}
                orig_c_ds_all = c_ds
                c_obj["dailySeries"] = f_cds
                if any(v.get("tokensEstimatedFromBytes") for v in f_cds.values()):
                    c_obj["tokensEstimatedFromBytes"] = True
                else:
                    c_obj.pop("tokensEstimatedFromBytes", None)
                c_obj["requests"] = sum(v.get("requests", 0) for v in f_cds.values())
                c_obj["inferenceRequests"] = sum(v.get("inferenceRequests", 0) for v in f_cds.values())
                c_obj["systemRequests"] = sum(v.get("systemRequests", 0) for v in f_cds.values())
                c_obj["ok200"] = sum(v.get("ok200", 0) for v in f_cds.values())
                c_obj["errors429"] = sum(v.get("errors429", 0) for v in f_cds.values())
                c_obj["ok200Inference"] = min(c_obj["inferenceRequests"], c_obj["ok200"])
                c_obj["failedInference"] = max(0, c_obj["inferenceRequests"] - c_obj["ok200Inference"])
                c_obj["totalTokens"] = sum(v.get("tokens", v.get("totalTokens", 0)) for v in f_cds.values())
                c_obj["inputTokens"] = sum(v.get("inputTokens", 0) for v in f_cds.values())
                c_obj["outputTokens"] = sum(v.get("outputTokens", 0) for v in f_cds.values())
                c_obj["cachedTokens"] = sum(v.get("cachedTokens", 0) for v in f_cds.values())
                c_obj["estimatedCostUsd"] = round(sum(v.get("costUsd", 0.0) for v in f_cds.values()), 4)
                c_rat = (c_obj["estimatedCostUsd"] / orig_c_cost) if orig_c_cost > 0 else (
                    _share_when_net_zero(orig_c_ds_all, f_cds, (("tokens", "totalTokens"), ("inferenceRequests",), ("requests",))) if orig_c_sav > 0 else 0.0)
                c_obj["cacheSavingsUsd"] = round(orig_c_sav * c_rat, 4)
                c_obj["grossCostUsd"] = round(c_obj["estimatedCostUsd"] + c_obj["cacheSavingsUsd"], 4)
            sliced_creds_by_id[c_obj.get("credentialId", "")] = c_obj

        if p.get("credentialsUsage"):
            p["credentialsUsage"].sort(key=lambda x: (x.get("estimatedCostUsd", 0.0), x.get("inferenceRequests", 0), x.get("requests", 0)), reverse=True)

        for k_obj in (p.get("apiKeys") or []):
            c_match = sliced_creds_by_id.get(f"apikey:{k_obj.get('uid', '')}")
            if c_match:
                k_obj["requests"] = c_match.get("requests", 0)
                k_obj["inferenceRequests"] = c_match.get("inferenceRequests", 0)
                k_obj["ok200Inference"] = c_match.get("ok200Inference", c_match.get("inferenceRequests", 0))
                k_obj["failedInference"] = c_match.get("failedInference", 0)
                k_obj["totalTokens"] = c_match.get("totalTokens", 0)
                k_obj["inputTokens"] = c_match.get("inputTokens", 0)
                k_obj["outputTokens"] = c_match.get("outputTokens", 0)
                k_obj["cachedTokens"] = c_match.get("cachedTokens", 0)
                k_obj["estimatedCostUsd"] = c_match.get("estimatedCostUsd", 0.0)
                k_obj["grossCostUsd"] = c_match.get("grossCostUsd", 0.0)
                k_obj["cacheSavingsUsd"] = c_match.get("cacheSavingsUsd", 0.0)
                if k_obj.get("requestBytes", 0) > 0 and tok_ratio < 0.999:
                    k_obj["requestBytes"] = int(round(float(k_obj.get("requestBytes", 0) or 0) * tok_ratio))
                if k_obj.get("responseBytes", 0) > 0 and tok_ratio < 0.999:
                    k_obj["responseBytes"] = int(round(float(k_obj.get("responseBytes", 0) or 0) * tok_ratio))

        # Accurately slice usersUsage metrics using exact sliced_creds_by_id for OAuth Clients & API Keys,
        # and proportional Discovery Engine / Code Assist scaling for pool users
        pool_scale_cost = (p["otherAiCostUsd"] / orig_o_cost) if (ds and orig_o_cost > 0) else win_ratio
        pool_scale_tok = win_ratio
        pool_scale_calls = win_ratio
        for u_obj in (p.get("usersUsage") or []):
            orig_u_oauth = float(u_obj.get("oauthCostUsd", 0.0) or 0.0)
            orig_u_vo = float(u_obj.get("vertexOauthCostUsd", 0.0) or 0.0)
            orig_pool_oauth = max(0.0, orig_u_oauth - orig_u_vo)

            # 1. Exact slice for Vertex OAuth Clients
            if u_obj.get("oauthClientsDetails"):
                vo_c_sum = 0
                vo_in_sum = 0
                vo_out_sum = 0
                vo_cache_sum = 0
                vo_tok_sum = 0
                vo_cost_sum = 0.0
                vo_gross_sum = 0.0
                vo_sav_sum = 0.0
                for oc_item in (u_obj.get("oauthClientsDetails") or []):
                    if not isinstance(oc_item, dict):
                        continue
                    c_match = sliced_creds_by_id.get(oc_item.get("credentialId", ""))
                    if c_match:
                        oc_calls = int(c_match.get("inferenceRequests", 0) or c_match.get("requests", 0) or 0)
                        oc_item["calls"] = oc_calls
                        oc_item["ok200Calls"] = int(c_match.get("ok200Inference", oc_calls) or 0)
                        oc_item["errors429"] = int(c_match.get("errors429", 0) or 0)
                        oc_item["inputTokens"] = int(c_match.get("inputTokens", 0) or 0)
                        oc_item["outputTokens"] = int(c_match.get("outputTokens", 0) or 0)
                        oc_item["cachedTokens"] = int(c_match.get("cachedTokens", 0) or 0)
                        oc_item["totalTokens"] = int(c_match.get("totalTokens", 0) or 0)
                        oc_item["costUsd"] = round(float(c_match.get("estimatedCostUsd", 0.0) or 0.0), 4)
                        oc_item["grossCostUsd"] = round(float(c_match.get("grossCostUsd", oc_item["costUsd"]) or 0.0), 4)
                        oc_item["cacheSavingsUsd"] = round(float(c_match.get("cacheSavingsUsd", 0.0) or 0.0), 4)
                    vo_c_sum += int(oc_item.get("calls", 0) or 0)
                    vo_in_sum += int(oc_item.get("inputTokens", 0) or 0)
                    vo_out_sum += int(oc_item.get("outputTokens", 0) or 0)
                    vo_cache_sum += int(oc_item.get("cachedTokens", 0) or 0)
                    vo_tok_sum += int(oc_item.get("totalTokens", 0) or 0)
                    vo_cost_sum += float(oc_item.get("costUsd", 0.0) or 0.0)
                    vo_gross_sum += float(oc_item.get("grossCostUsd", 0.0) or 0.0)
                    vo_sav_sum += float(oc_item.get("cacheSavingsUsd", 0.0) or 0.0)
                u_obj["vertexOauthCalls"] = vo_c_sum
                u_obj["vertexOauthInputTokens"] = vo_in_sum
                u_obj["vertexOauthOutputTokens"] = vo_out_sum
                u_obj["vertexOauthCachedTokens"] = vo_cache_sum
                u_obj["vertexOauthTokens"] = vo_tok_sum
                u_obj["vertexOauthCostUsd"] = round(vo_cost_sum, 4)
                u_obj["vertexOauthGrossCostUsd"] = round(vo_gross_sum, 4)
                u_obj["vertexOauthCacheSavingsUsd"] = round(vo_sav_sum, 4)

            # 2. Exact slice for API Keys
            if u_obj.get("apiKeysDetails"):
                ak_c_sum = 0
                ak_in_sum = 0
                ak_out_sum = 0
                ak_cache_sum = 0
                ak_tok_sum = 0
                ak_cost_sum = 0.0
                ak_gross_sum = 0.0
                ak_sav_sum = 0.0
                for kd_item in (u_obj.get("apiKeysDetails") or []):
                    if not isinstance(kd_item, dict):
                        continue
                    c_match = sliced_creds_by_id.get(f"apikey:{kd_item.get('uid', '')}")
                    if c_match:
                        kc_calls = int(c_match.get("inferenceRequests", 0) or c_match.get("requests", 0) or 0)
                        kd_item["calls"] = kc_calls
                        kd_item["ok200Calls"] = int(c_match.get("ok200Inference", kc_calls) or 0)
                        kd_item["inputTokens"] = int(c_match.get("inputTokens", 0) or 0)
                        kd_item["outputTokens"] = int(c_match.get("outputTokens", 0) or 0)
                        kd_item["totalTokens"] = int(c_match.get("totalTokens", 0) or 0)
                        kd_item["costUsd"] = round(float(c_match.get("estimatedCostUsd", 0.0) or 0.0), 4)
                        kd_item["grossCostUsd"] = round(float(c_match.get("grossCostUsd", kd_item["costUsd"]) or 0.0), 4)
                        kd_item["cacheSavingsUsd"] = round(float(c_match.get("cacheSavingsUsd", 0.0) or 0.0), 4)
                    ak_c_sum += int(kd_item.get("calls", 0) or 0)
                    ak_in_sum += int(kd_item.get("inputTokens", 0) or 0)
                    ak_out_sum += int(kd_item.get("outputTokens", 0) or 0)
                    ak_tok_sum += int(kd_item.get("totalTokens", 0) or 0)
                    ak_cost_sum += float(kd_item.get("costUsd", 0.0) or 0.0)
                    ak_gross_sum += float(kd_item.get("grossCostUsd", 0.0) or 0.0)
                    ak_sav_sum += float(kd_item.get("cacheSavingsUsd", 0.0) or 0.0)
                u_obj["apiKeysCalls"] = ak_c_sum
                u_obj["apiKeysInputTokens"] = ak_in_sum
                u_obj["apiKeysOutputTokens"] = ak_out_sum
                u_obj["apiKeysCachedTokens"] = ak_cache_sum
                u_obj["apiKeysTotalTokens"] = ak_tok_sum
                u_obj["apiKeysCostUsd"] = round(ak_cost_sum, 4)
                u_obj["apiKeysGrossCostUsd"] = round(ak_gross_sum, 4)
                u_obj["apiKeysCacheSavingsUsd"] = round(ak_sav_sum, 4)
                if "Google AI Studio" in (u_obj.get("toolsUsed") or []):
                    u_obj["aiStudioCalls"] = ak_c_sum

            # 3. Scale Discovery Engine / Code Assist pool metrics
            if pool_scale_cost < 0.999 or pool_scale_calls < 0.999 or pool_scale_tok < 0.999:
                for tk_field in ("loggedTotalTokens", "loggedInputTokens", "loggedOutputTokens", "loggedCachedTokens"):
                    if u_obj.get(tk_field, 0) > 0:
                        u_obj[tk_field] = int(round(float(u_obj.get(tk_field, 0) or 0) * pool_scale_tok))
                for call_field in (
                    "assistTurns", "searchQueries", "codeAssistCalls",
                    "notebookLmCalls", "colabCalls", "fileOps", "otherCalls", "queriesCount", "conversationsCount"
                ):
                    orig_val = int(u_obj.get(call_field, 0) or 0)
                    if orig_val > 0:
                        u_obj[call_field] = int(round(float(orig_val) * pool_scale_calls))
                for eng in (u_obj.get("engines") or []):
                    if isinstance(eng, dict) and eng.get("calls", 0) > 0:
                        eng["calls"] = max(1 if pool_scale_calls > 0 else 0, int(round(float(eng.get("calls", 0) or 0) * pool_scale_calls)))
                for ds_item in (u_obj.get("dataStores") or []):
                    if isinstance(ds_item, dict) and ds_item.get("calls", 0) > 0:
                        ds_item["calls"] = max(1 if pool_scale_calls > 0 else 0, int(round(float(ds_item.get("calls", 0) or 0) * pool_scale_calls)))

            scaled_pool_oauth = round(orig_pool_oauth * pool_scale_cost, 4)
            u_obj["oauthCostUsd"] = round(scaled_pool_oauth + float(u_obj.get("vertexOauthCostUsd", 0.0) or 0.0), 4)
            u_obj["directCostUsd"] = round(u_obj["oauthCostUsd"] + float(u_obj.get("apiKeysCostUsd", 0.0) or 0.0), 4)
            u_obj["estimatedCostUsd"] = u_obj["directCostUsd"]
            u_obj["attributedTokens"] = (
                int(u_obj.get("loggedTotalTokens", 0) or 0) +
                int(u_obj.get("vertexOauthTokens", 0) or 0) +
                int(u_obj.get("apiKeysTotalTokens", 0) or 0)
            )
            u_obj["totalInteractions"] = (
                int(u_obj.get("assistTurns", 0) or 0) +
                int(u_obj.get("searchQueries", 0) or 0) +
                int(u_obj.get("codeAssistCalls", 0) or 0) +
                int(u_obj.get("notebookLmCalls", 0) or 0) +
                int(u_obj.get("fileOps", 0) or 0) +
                int(u_obj.get("otherCalls", 0) or 0) +
                int(u_obj.get("vertexOauthCalls", 0) or 0)
            )

        if p.get("usersUsage"):
            p["usersUsage"].sort(key=lambda x: (x.get("estimatedCostUsd", 0.0), x.get("attributedTokens", 0), x.get("totalInteractions", 0)), reverse=True)

        # Scale infraServices proportionally to window ratio, excluding non-AI services (e.g. Cloud SQL) from infraCostUsd
        infra_ratio = min(1.0, float(target_days) / float(base_days))
        if p.get("infraServices"):
            if infra_ratio < 0.999:
                import re as _re_infra
                for inf_s in p["infraServices"]:
                    # Gross defaults to the ORIGINAL net cost when missing
                    if "grossCostUsd" not in inf_s:
                        inf_s["grossCostUsd"] = inf_s.get("costUsd", 0.0)
                    # Scale every monetary field of the row with the same window ratio
                    for money_k in ("costUsd", "grossCostUsd", "savingsUsd", "negotiatedSavingsUsd",
                                    "cudSavingsUsd", "unroundedEur", "netCostUsd"):
                        if inf_s.get(money_k) is not None:
                            inf_s[money_k] = round(float(inf_s.get(money_k) or 0.0) * infra_ratio, 4)
                    if inf_s.get("activeDays") is not None:
                        inf_s["activeDays"] = min(int(target_days), int(inf_s.get("activeDays") or 0))
                    if isinstance(inf_s.get("details"), str):
                        # Replace only the first "<N> days" occurrence with the window length ("gg" = rows saved before the English UI)
                        inf_s["details"] = _re_infra.sub(
                            r"\b\d+ (days|gg)\b", lambda m: f"{int(target_days)} {m.group(1)}", inf_s["details"], count=1)
            ai_infra = [x for x in p["infraServices"] if not x.get("excludedNonAi", False)]
            p["infraCostUsd"] = round(sum(float(x.get("costUsd", 0.0) or 0.0) for x in ai_infra), 4)
            p["infraGrossCostUsd"] = round(sum(float(x.get("grossCostUsd", x.get("costUsd", 0.0)) or 0.0) for x in ai_infra), 4)
            p["infraSavingsUsd"] = round(max(0.0, p["infraGrossCostUsd"] - p["infraCostUsd"]), 4)
            if p.get("nonAiInfraCostUsd") is not None and infra_ratio < 0.999:
                p["nonAiInfraCostUsd"] = round(float(p.get("nonAiInfraCostUsd", 0.0) or 0.0) * infra_ratio, 4)

        ai_gross_t = round(p.get("vertexGrossCostUsd", 0.0) + p.get("geminiGrossCostUsd", 0.0) + p.get("otherAiGrossCostUsd", 0.0), 4)
        ai_sav_t = round(p.get("vertexCacheSavingsUsd", 0.0) + p.get("geminiCacheSavingsUsd", 0.0) + p.get("otherAiCacheSavingsUsd", 0.0), 4)
        p["totalBillGrossUsd"] = round(ai_gross_t + (p.get("infraGrossCostUsd", 0.0) or 0.0), 4)
        p["totalBillSavingsUsd"] = round(ai_sav_t + (p.get("infraSavingsUsd", 0.0) or 0.0), 4)
        p["totalBillCostUsd"] = round(p.get("estimatedCostUsd", 0.0) + (p.get("infraCostUsd", 0.0) or 0.0), 4)

        # Clear pre-computed 30d telemetry dicts so enrich_scan_payload_security recomputes them for target_days
        for k_stale in ("dataResidency", "finopsExtended", "aiToolsSummary", "agentspaceTelemetry", "aiLogForensics", "aiSecurityPosture"):
            p.pop(k_stale, None)

    active_acc = auth.get("activeAccount")
    sync_meta = build_sync_summary_for_account(active_acc) if active_acc else None
    sliced = build_scan_payload_from_projects(
        cloned_projects, days=target_days, auth=auth,
        elapsed_seconds=base_payload.get("elapsedSeconds", 0.1),
        scanned_at=base_payload.get("scannedAt"), sync_meta=sync_meta
    )
    if not sliced.get("timeline"):
        sliced["timeline"] = [{"date": cutoff_date, **empty_day_bucket()}]
        if end_date_str != cutoff_date:
            sliced["timeline"].append({"date": end_date_str, **empty_day_bucket()})
    sliced["fromCache"] = True
    sliced["slicedFromDays"] = base_payload.get("days", 30)
    sliced["periodStart"] = cutoff_date
    sliced["periodEnd"] = end_date_str
    sliced["periodRange"] = {
        "days": target_days,
        "startDate": cutoff_date,
        "endDate": end_date_str,
        "preset": preset_clean or str(target_days)
    }
    return sliced


def make_unscanned_project_placeholder(p_raw: dict) -> dict:
    return {
        "projectId": p_raw["projectId"],
        "name": p_raw.get("name") or p_raw["projectId"],
        "billingEnabled": False,
        "skippedNoBilling": True,
        "aiActive": False,
        "scanStatus": "SKIPPED_BY_SYNC_RULE",
        "totalRequests": 0,
        "inferenceRequests": 0,
        "systemRequests": 0,
        "totalTokens": 0,
        "vertexCostUsd": 0.0,
        "geminiCostUsd": 0.0,
        "otherAiCostUsd": 0.0,
        "estimatedCostUsd": 0.0,
        "enabledAiApis": [],
        "vertexFeatures": [],
        "deployedAiResources": [],
        "modelArmor": {"enabled": False, "status": "DISABLED", "statusLabel": "Not Enabled", "templates": []},
        "models": [],
        "credentialsUsage": [],
        "usersUsage": [],
        "apiKeys": [],
        "serviceAccounts": [],
        "dailySeries": {},
        "permissions": {
            "accessLevel": "SKIPPED",
            "badgeLabel": "⏸️ Excluded from Scan (No AI Data)",
            "iamGrantedCount": 0,
            "iamTotalCount": len(PROJECT_IAM_PERMISSIONS_TO_CHECK),
            "grantedIamPermissions": [],
            "missingIamPermissions": [],
            "missingSummary": [],
            "areas": {}
        }
    }


def get_first_accessible_project_id(
    active_acc: str | None,
    reg: dict | None = None,
    raw_projects: list | None = None,
) -> str | None:
    """
    Restituisce il primo projectId accessibile dall'account attivo (preferendo scanEnabled=True
    nel sync registry, altrimenti il primo nel registry o in raw_projects). Mai hardcoded.
    """
    if active_acc:
        with contextlib.suppress(Exception):
            if reg is None:
                reg = ensure_account_sync_registry(active_acc)
            acc_projects = ((reg or {}).get("accounts") or {}).get(active_acc, {}).get("projects") or {}
            for pid, p_meta in acc_projects.items():
                if pid and isinstance(p_meta, dict) and p_meta.get("scanEnabled"):
                    return str(pid)
            for pid in acc_projects:
                if pid:
                    return str(pid)
    if raw_projects:
        for p_raw in raw_projects:
            if isinstance(p_raw, dict) and p_raw.get("projectId"):
                return str(p_raw["projectId"])
    return None


def get_quota_project_candidates(
    active_acc: str | None,
    reg: dict | None = None,
    raw_projects: list | None = None,
    limit: int = 4,
) -> list[str]:
    """Ordered quota-project candidates for APIs that need one: projects with AI data first (highest
    estimated cost first), then other scan-enabled projects, then any known project. Never hardcoded."""
    ranked: list[tuple[int, float, str]] = []
    if active_acc:
        with contextlib.suppress(Exception):
            if reg is None:
                reg = ensure_account_sync_registry(active_acc)
            acc_projects = ((reg or {}).get("accounts") or {}).get(active_acc, {}).get("projects") or {}
            for pid, meta in acc_projects.items():
                if not pid or not isinstance(meta, dict):
                    continue
                tier = 0 if (meta.get("scanEnabled") and meta.get("hasAiData")) else (1 if meta.get("scanEnabled") else 2)
                ranked.append((tier, -float(meta.get("estimatedCostUsd") or 0.0), str(pid)))
    ranked.sort()
    out = [pid for _t, _c, pid in ranked]
    for p_raw in raw_projects or []:
        if isinstance(p_raw, dict) and p_raw.get("projectId") and str(p_raw["projectId"]) not in out:
            out.append(str(p_raw["projectId"]))
    return out[: max(1, int(limit))]


def scan_all_projects(
    days: int = 30,
    requested_account: str = None,
    browser_accounts: list[str] = None,
    scan_mode: str = "smart",
    force_project_ids: list[str] = None,
    session_id: str = None,
    start_date: str = None,
    end_date: str = None,
    preset: str = None
) -> dict:
    """
    Scans GCP projects with intelligent synchronization & selective scanning:
    - First time (when registry is empty): scans all projects, puts projects with AI data into
      'Da Scansionare' (scanEnabled=True) and projects without AI data into 'Non Scansionare' (scanEnabled=False).
    - Subsequent 'smart' scans:
      1. Lists all accessible GCP projects via Resource Manager.
      2. Detects any NEW projects not yet in `projects_sync_registry.json`, flags them as `isNewProject=True`,
         scans them automatically, and applies the data/no-data rule.
      3. Scans ONLY projects marked `scanEnabled=True` (plus any new projects or `force_project_ids`),
         reusing cached project entries for excluded (`scanEnabled=False`) projects.
    - 'full' scan mode: scans all projects from scratch and updates the registry.
    - Supports exact single-date or custom range (`start_date` .. `end_date` / `preset`) so only the requested
      date(s) are queried from GCP Cloud Monitoring and Cloud Logging.
    """
    auth = get_auth_status_for_browser(requested_account, browser_accounts, session_id=session_id)
    if not auth["tokenValid"] or not auth["accessToken"]:
        return {
            "success": False,
            "needsLogin": True,
            "auth": {
                "accounts": auth["accounts"],
                "activeAccount": auth["activeAccount"],
                "tokenValid": False,
                "tokenError": auth["tokenError"]
            },
            "error": auth["tokenError"] or "Google authentication required in this browser."
        }

    active_acc = auth["activeAccount"]
    token = auth["accessToken"]
    budgets = load_budgets()
    t0 = time.time()

    preset_clean = (preset or "").strip().lower()
    if preset_clean == "today" and not start_date:
        t_str = datetime.now().strftime("%Y-%m-%d")
        start_date = t_str
        end_date = t_str
    elif preset_clean == "yesterday" and not start_date:
        y_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = y_str
        end_date = y_str

    s_clean = None
    e_clean = None
    if start_date or end_date:
        s_clean = str(start_date or end_date).strip()[:10]
        e_clean = str(end_date or start_date).strip()[:10]
        if s_clean > e_clean:
            s_clean, e_clean = e_clean, s_clean
        try:
            s_dt = datetime.strptime(s_clean, "%Y-%m-%d")
            e_dt = datetime.strptime(e_clean, "%Y-%m-%d")
            days = max(1, (e_dt - s_dt).days + 1)
        except Exception:
            days = max(1, int(days or 1))

    update_scan_progress(
        active=True,
        startedAt=t0,
        mode=scan_mode,
        days=days,
        totalProjects=0,
        completedProjects=0,
        currentPhase="Phase 1/4",
        currentStep="Listing accessible Google Cloud projects and checking sync...",
        lastCompletedProject=""
    )

    reg = ensure_account_sync_registry(active_acc)
    acc_reg = reg.setdefault("accounts", {}).setdefault(active_acc, {
        "account": active_acc,
        "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
        "lastSyncAt": None,
        "newProjectsDetected": [],
        "projects": {}
    })
    reg_projects = acc_reg.setdefault("projects", {})

    # Load previous cache for this account to reuse data for excluded projects
    prev_cache = load_best_cached_payload_for_account(active_acc, preferred_days=days)
    prev_projects_by_id = {}
    if prev_cache and prev_cache.get("projects"):
        for cp in prev_cache["projects"]:
            if cp.get("projectId"):
                prev_projects_by_id[cp["projectId"]] = cp

    # Previous data can stand in for a rate-limited project only if it covers the same period
    prev_range = (prev_cache or {}).get("periodRange") or {}
    prev_same_period = bool(prev_cache) and int((prev_cache or {}).get("days") or 0) == int(days) and (
        not (s_clean and e_clean) or (prev_range.get("startDate") == s_clean and prev_range.get("endDate") == e_clean)
    )

    raw_projects = list_all_accessible_projects(token)
    force_set = set(force_project_ids or [])

    # Sync models & pricing from GCP APIs at most once per day (non-blocking on error)
    with contextlib.suppress(Exception):
        mp_cfg = load_models_pricing_config()
        last_sync_iso = str(((mp_cfg.get("lastApiSync") or {}).get("syncedAt")) or "")
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if last_sync_iso[:10] not in (today_utc, get_today_date_str()):
            quota_cands = get_quota_project_candidates(active_acc, reg=reg, raw_projects=raw_projects)
            if MODELS_PRICING_SYNC_LOCK.acquire(blocking=False):
                try:
                    sync_models_and_pricing_from_gcp_api(
                        token, user_project=(quota_cands[0] if quota_cands else None), quota_candidates=quota_cands
                    )
                finally:
                    MODELS_PRICING_SYNC_LOCK.release()

    # Detect new projects vs existing registry
    had_existing_registry = len(reg_projects) > 0
    newly_detected_ids = []
    projects_to_scan_live = []
    reused_projects = []

    for p_raw in raw_projects:
        pid = p_raw["projectId"]
        in_reg = pid in reg_projects
        if not in_reg and had_existing_registry:
            newly_detected_ids.append({
                "projectId": pid,
                "name": p_raw.get("name") or pid,
                "detectedAt": datetime.now(timezone.utc).isoformat()
            })

        if scan_mode == "full" or not had_existing_registry or (not in_reg) or (pid in force_set):
            projects_to_scan_live.append(p_raw)
        else:
            reg_entry = reg_projects[pid]
            if reg_entry.get("scanEnabled", False):
                projects_to_scan_live.append(p_raw)
            else:
                # Reuse cached project data (or placeholder) without hitting slow GCP APIs
                cached_p = prev_projects_by_id.get(pid)
                if cached_p:
                    reused_projects.append(cached_p)
                else:
                    reused_projects.append(make_unscanned_project_placeholder(p_raw))

    total_live = len(projects_to_scan_live)
    update_scan_progress(
        totalProjects=total_live,
        completedProjects=0,
        currentPhase="Phase 2/4",
        currentStep=f"Parallel scan of {total_live} active AI projects (Cloud Monitoring, Vertex Resources, IAM and Logs)..."
    )

    ba_cache = {}
    live_inspected = []
    max_workers = min(4, max(1, total_live))  # fewer parallel projects: avoids Google 429 bursts
    if projects_to_scan_live:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    inspect_single_project,
                    p, token, days, budgets, ba_cache,
                    prev_projects_by_id.get(p["projectId"]),
                    s_clean, e_clean
                ): p
                for p in projects_to_scan_live
            }
            for fut in as_completed(futures):
                p_meta = futures[fut]
                p_id_done = p_meta.get("projectId", "")
                try:
                    res = fut.result()
                    prev_p = prev_projects_by_id.get(p_id_done)
                    if (res.get("transientError") and prev_p
                            and prev_p.get("scanStatus") not in NOT_REUSABLE_SCAN_STATUSES):
                        # Google rate-limited this project: show the previous scan's data (sliced if period differs), flagged, instead of "denied"
                        if prev_same_period:
                            fallback_p = prev_p
                        else:
                            try:
                                sliced_wrap = slice_cached_payload_for_days(
                                    {
                                        "projects": [prev_p],
                                        "days": (prev_cache or {}).get("days", 30),
                                        "scannedAt": (prev_cache or {}).get("scannedAt")
                                    },
                                    days, auth, start_date=s_clean, end_date=e_clean, preset=preset_clean
                                )
                                fallback_p = (sliced_wrap.get("projects") or [prev_p])[0]
                            except Exception:
                                fallback_p = prev_p
                        res = dict(fallback_p, staleFromPreviousScan=True, transientError=res["transientError"],
                                   transientErrorStep=res.get("transientErrorStep"), error=res.get("error"))
                    live_inspected.append(res)
                except Exception as e:
                    p = p_meta
                    live_inspected.append({
                        "projectId": p["projectId"],
                        "name": p["name"],
                        "billingEnabled": False,
                        "skippedNoBilling": True,
                        "aiActive": False,
                        "scanStatus": "ERROR",
                        "error": str(e),
                        "totalRequests": 0,
                        "inferenceRequests": 0,
                        "systemRequests": 0,
                        "totalTokens": 0,
                        "vertexCostUsd": 0.0,
                        "geminiCostUsd": 0.0,
                        "otherAiCostUsd": 0.0,
                        "estimatedCostUsd": 0.0,
                        "enabledAiApis": [],
                        "vertexFeatures": [],
                        "deployedAiResources": [],
                        "modelArmor": {"enabled": False, "status": "DISABLED", "statusLabel": "Not Enabled", "templates": []},
                        "models": [],
                        "credentialsUsage": [],
                        "apiKeys": [],
                        "serviceAccounts": [],
                        "dailySeries": {},
                        "permissions": {
                            "accessLevel": "DENIED",
                            "badgeLabel": f"❌ Scan Error: {str(e)[:40]}",
                            "iamGrantedCount": 0,
                            "iamTotalCount": len(PROJECT_IAM_PERMISSIONS_TO_CHECK),
                            "grantedIamPermissions": [],
                            "missingIamPermissions": list(PROJECT_IAM_PERMISSIONS_TO_CHECK),
                            "missingSummary": ["Scan error"],
                            "areas": {}
                        }
                    })
                done_cnt = len(live_inspected)
                update_scan_progress(
                    completedProjects=done_cnt,
                    lastCompletedProject=p_id_done,
                    currentPhase="Phase 3/4" if done_cnt >= max(1, total_live // 2) else "Phase 2/4",
                    currentStep=f"Completed {done_cnt}/{total_live} projects (last: {p_id_done})..."
                )

    update_scan_progress(
        currentPhase="Phase 4/4",
        currentStep="Aggregating FinOps TCO, Data Residency and saving cache..."
    )

    scanned_at_iso = datetime.now(timezone.utc).isoformat()
    new_pids_set = {x["projectId"] for x in newly_detected_ids}
    newly_classified = []

    # Clear previous isNewProject flags if doing a fresh scan, then mark any newly detected in this scan
    for existing_entry in reg_projects.values():
        if existing_entry.get("projectId") not in new_pids_set:
            existing_entry["isNewProject"] = False

    for p_res in live_inspected:
        pid = p_res.get("projectId")
        is_new = pid in new_pids_set
        updated_entry = update_registry_entry_from_project(
            reg_projects, p_res, scanned_at_iso, is_new=is_new, preserve_manual=True
        )
        if is_new:
            newly_classified.append({
                "projectId": pid,
                "name": updated_entry["name"],
                "hasAiData": updated_entry["hasAiData"],
                "scanEnabled": updated_entry["scanEnabled"],
                "scanRule": updated_entry["scanRule"],
                "dataReason": updated_entry["dataReason"],
                "estimatedCostUsd": updated_entry["estimatedCostUsd"]
            })

    # Ensure reused projects are also in registry
    for p_reused in reused_projects:
        pid = p_reused.get("projectId")
        if pid and pid not in reg_projects:
            update_registry_entry_from_project(
                reg_projects, p_reused, scanned_at_iso, is_new=False, preserve_manual=True
            )

    acc_reg["lastSyncAt"] = scanned_at_iso
    acc_reg["newProjectsDetected"] = newly_classified
    save_sync_registry(reg)

    all_inspected = live_inspected + reused_projects
    # Register any models observed in Cloud Monitoring without making network calls
    with contextlib.suppress(Exception):
        observed_mods = [
            m.get("modelId")
            for p_obj in all_inspected
            for m in (p_obj.get("models") or [])
            if isinstance(m, dict) and m.get("modelId")
        ]
        if observed_mods:
            register_observed_models_in_pricing_config(observed_mods)
    # Annotate each project with its sync registry metadata for the frontend
    for p_obj in all_inspected:
        pid = p_obj.get("projectId")
        if pid in reg_projects:
            r_meta = reg_projects[pid]
            p_obj["syncMeta"] = {
                "scanEnabled": r_meta.get("scanEnabled", False),
                "hasAiData": r_meta.get("hasAiData", False),
                "scanRule": r_meta.get("scanRule", "AUTO_EXCLUDE_NO_DATA"),
                "dataReason": r_meta.get("dataReason", ""),
                "isNewProject": r_meta.get("isNewProject", False),
                "lastScannedAt": r_meta.get("lastScannedAt", scanned_at_iso),
                "scannedLiveInLastRun": pid in {x.get("projectId") for x in live_inspected}
            }

    sync_summary = build_sync_summary_for_account(active_acc, reg)
    sync_summary["lastScanMode"] = scan_mode
    sync_summary["scannedLiveCount"] = len(live_inspected)
    sync_summary["reusedFromCacheCount"] = len(reused_projects)
    sync_summary["newProjectsDetected"] = newly_classified

    elapsed = round(time.time() - t0, 2)
    payload = build_scan_payload_from_projects(
        all_inspected,
        days=days,
        auth=auth,
        elapsed_seconds=elapsed,
        scanned_at=scanned_at_iso,
        sync_meta=sync_summary
    )
    payload["fromCache"] = False
    payload["scanMode"] = scan_mode
    if s_clean and e_clean:
        payload["periodStart"] = s_clean
        payload["periodEnd"] = e_clean
        payload["periodRange"] = {
            "days": days,
            "startDate": s_clean,
            "endDate": e_clean,
            "preset": preset_clean or ("single" if s_clean == e_clean else "custom")
        }
        if not payload.get("timeline"):
            payload["timeline"] = [{"date": s_clean, **empty_day_bucket()}]
            if e_clean != s_clean:
                payload["timeline"].append({"date": e_clean, **empty_day_bucket()})

    with contextlib.suppress(OSError, ValueError, TypeError):
        if s_clean and e_clean:
            range_cache = get_account_cache_path(active_acc, f"range_{s_clean}_{e_clean}")
            with open(range_cache, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            # Also merge scanned dailySeries buckets into the 30d master cache if it exists
            cache_30_path = get_account_cache_path(active_acc, 30)
            if os.path.exists(cache_30_path):
                with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                    with open(cache_30_path, "r", encoding="utf-8") as f30:
                        c30 = json.load(f30)
                    live_by_pid = {p.get("projectId"): p for p in live_inspected if p.get("projectId")}
                    for p30 in c30.get("projects", []):
                        pid30 = p30.get("projectId")
                        if pid30 in live_by_pid:
                            ds30 = p30.setdefault("dailySeries", {})
                            for k_d in list(ds30.keys()):
                                if s_clean <= k_d <= e_clean:
                                    ds30.pop(k_d, None)
                            for k_d, v_d in (live_by_pid[pid30].get("dailySeries") or {}).items():
                                ds30[k_d] = v_d
                    c30["scannedAt"] = scanned_at_iso
                    with open(cache_30_path, "w", encoding="utf-8") as f30w:
                        json.dump(c30, f30w, indent=2, ensure_ascii=False)
        else:
            acc_cache = get_account_cache_path(active_acc, days)
            with open(acc_cache, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

    RAM_PAYLOAD_CACHE.clear()

    update_scan_progress(
        active=False,
        completedProjects=total_live,
        currentPhase="Completed",
        currentStep=f"Scan completed in {elapsed}s"
    )
    with SCAN_PROGRESS_LOCK:
        SCAN_PROGRESS["lastScannedAt"] = scanned_at_iso
        SCAN_PROGRESS["lastElapsedSeconds"] = elapsed

    return payload


def start_or_join_live_scan(
    days: int = 30,
    requested_account: str = None,
    browser_accounts: list[str] = None,
    scan_mode: str = "smart",
    async_mode: bool = False,
    session_id: str = None,
    start_date: str = None,
    end_date: str = None,
    preset: str = None
) -> dict:
    """
    Single-Flight Live Scan Coordinator:
    - Guarantees that at most ONE live scan runs at any time on the server.
    - If a scan is already running (even if triggered before an F5 reload or from another tab),
      it NEVER launches a duplicate scan in parallel; instead it attaches to the active scan.
    - Runs the scan inside a dedicated background daemon thread so an F5 page refresh or closed
      HTTP socket never aborts or loses the scan progress.
    """
    global LAST_LIVE_SCAN_RESULT
    already_running = False
    with SCAN_PROGRESS_LOCK:
        if SCAN_PROGRESS.get("active"):
            already_running = True
        else:
            SCAN_PROGRESS["active"] = True
            SCAN_PROGRESS["scanId"] = int(SCAN_PROGRESS.get("scanId", 0)) + 1
            SCAN_PROGRESS["account"] = requested_account
            SCAN_PROGRESS["mode"] = scan_mode
            SCAN_PROGRESS["days"] = days
            SCAN_PROGRESS["startedAt"] = time.time()
            SCAN_PROGRESS["completedProjects"] = 0
            SCAN_PROGRESS["totalProjects"] = 0
            SCAN_PROGRESS["pct"] = 8
            SCAN_PROGRESS["stepIndex"] = 1
            SCAN_PROGRESS["stepBadge"] = "Phase 1/4"
            SCAN_PROGRESS["currentPhase"] = "Phase 1/4"
            SCAN_PROGRESS["stepDesc"] = "Checking Google Cloud projects and sync..."
            SCAN_PROGRESS["currentStep"] = "Checking Google Cloud projects and sync..."
            SCAN_PROGRESS["lastError"] = None
            LIVE_SCAN_EVENT.clear()

    if not already_running:
        def _bg_scan_worker():
            global LAST_LIVE_SCAN_RESULT
            try:
                res = scan_all_projects(
                    days=days, requested_account=requested_account,
                    browser_accounts=browser_accounts,
                    scan_mode=scan_mode, session_id=session_id,
                    start_date=start_date, end_date=end_date, preset=preset
                )
                LAST_LIVE_SCAN_RESULT = res
                if not res.get("success"):
                    with SCAN_PROGRESS_LOCK:
                        SCAN_PROGRESS["active"] = False
                        SCAN_PROGRESS["lastError"] = res.get("error") or "Scan error"
            except Exception as ex:
                LAST_LIVE_SCAN_RESULT = {"success": False, "error": str(ex)}
                with SCAN_PROGRESS_LOCK:
                    SCAN_PROGRESS["active"] = False
                    SCAN_PROGRESS["lastError"] = str(ex)
            finally:
                with SCAN_PROGRESS_LOCK:
                    SCAN_PROGRESS["active"] = False
                RAM_PAYLOAD_CACHE.clear()
                LIVE_SCAN_EVENT.set()

        t = threading.Thread(target=_bg_scan_worker, daemon=True)
        t.start()

    if async_mode:
        return {
            "success": True,
            "scanInProgress": True,
            "alreadyRunning": already_running,
            "progress": get_scan_progress_snapshot(requested_account)
        }

    LIVE_SCAN_EVENT.wait(timeout=240.0)
    if LAST_LIVE_SCAN_RESULT:
        res_acc = (LAST_LIVE_SCAN_RESULT.get("auth") or {}).get("activeAccount")
        if not res_acc or not requested_account or res_acc == requested_account:
            res_copy = dict(LAST_LIVE_SCAN_RESULT)
            res_copy["scanProgress"] = get_scan_progress_snapshot(requested_account)
            return res_copy
    return {"success": False, "error": "Live scan timeout", "scanProgress": get_scan_progress_snapshot(requested_account)}


def force_scan_single_project(
    project_id: str,
    days: int = 30,
    requested_account: str = None,
    browser_accounts: list[str] = None,
    session_id: str = None
) -> dict:
    """
    Forces an immediate live scan of a single project (even if it was in 'Non Scansionare'),
    updates its entry in the sync registry & current cached payload, and returns the updated payload.
    """
    auth = get_auth_status_for_browser(requested_account, browser_accounts, session_id=session_id)
    if not auth["tokenValid"] or not auth["accessToken"]:
        return {
            "success": False,
            "needsLogin": True,
            "error": auth["tokenError"] or "Google authentication required."
        }

    active_acc = auth["activeAccount"]
    token = auth["accessToken"]
    budgets = load_budgets()
    t0 = time.time()

    reg = ensure_account_sync_registry(active_acc)
    acc_reg = reg.setdefault("accounts", {}).setdefault(active_acc, {
        "account": active_acc,
        "bootstrappedAt": datetime.now(timezone.utc).isoformat(),
        "lastSyncAt": None,
        "newProjectsDetected": [],
        "projects": {}
    })
    reg_projects = acc_reg.setdefault("projects", {})
    existing_entry = reg_projects.get(project_id, {})
    proj_name = existing_entry.get("name") or project_id

    p_raw = {"projectId": project_id, "name": proj_name}
    ba_cache = {}
    scanned_proj = inspect_single_project(p_raw, token, days, budgets, ba_cache)
    scanned_at_iso = datetime.now(timezone.utc).isoformat()

    # Update registry: if the forced scan discovered data, auto-enable it; otherwise keep its rule or update metrics
    updated_entry = update_registry_entry_from_project(
        reg_projects, scanned_proj, scanned_at_iso, is_new=False, preserve_manual=True
    )
    if updated_entry["hasAiData"] and not updated_entry["scanEnabled"]:
        updated_entry["scanEnabled"] = True
        updated_entry["scanRule"] = "AUTO_INCLUDE_HAS_DATA"

    save_sync_registry(reg)

    # Merge into existing cached payload for this account
    base_cache = load_best_cached_payload_for_account(active_acc, preferred_days=days)
    projects_list = []
    replaced = False
    if base_cache and base_cache.get("projects"):
        for cp in base_cache["projects"]:
            if cp.get("projectId") == project_id:
                projects_list.append(scanned_proj)
                replaced = True
            else:
                projects_list.append(cp)
    if not replaced:
        projects_list.append(scanned_proj)

    for p_obj in projects_list:
        pid = p_obj.get("projectId")
        if pid in reg_projects:
            r_meta = reg_projects[pid]
            p_obj["syncMeta"] = {
                "scanEnabled": r_meta.get("scanEnabled", False),
                "hasAiData": r_meta.get("hasAiData", False),
                "scanRule": r_meta.get("scanRule", "AUTO_EXCLUDE_NO_DATA"),
                "dataReason": r_meta.get("dataReason", ""),
                "isNewProject": r_meta.get("isNewProject", False),
                "lastScannedAt": r_meta.get("lastScannedAt", scanned_at_iso),
                "scannedLiveInLastRun": (pid == project_id)
            }

    sync_summary = build_sync_summary_for_account(active_acc, reg)
    sync_summary["lastScanMode"] = f"force_single:{project_id}"
    sync_summary["scannedLiveCount"] = 1
    sync_summary["reusedFromCacheCount"] = max(0, len(projects_list) - 1)

    elapsed = round(time.time() - t0, 2)
    payload = build_scan_payload_from_projects(
        projects_list,
        days=days,
        auth=auth,
        elapsed_seconds=elapsed,
        scanned_at=scanned_at_iso,
        sync_meta=sync_summary
    )
    payload["fromCache"] = False
    payload["forcedProjectId"] = project_id
    payload["forcedProjectResult"] = updated_entry

    with contextlib.suppress(OSError, ValueError, TypeError):
        acc_cache = get_account_cache_path(active_acc, days)
        with open(acc_cache, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    update_scan_progress(
        active=False,
        completedProjects=1,
        currentPhase="Completed",
        currentStep=f"Scan of project {project_id} completed in {elapsed}s"
    )

    return payload


