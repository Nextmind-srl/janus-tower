def _new_model_usage_entry(model_id: str, service: str = "aiplatform.googleapis.com") -> dict:
    return {
        "modelId": model_id,
        "service": service,
        "locations": set(),
        "invocations": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cachedTokens": 0,
        "thinkingTokens": 0,
        "totalTokens": 0,
        "grossCostUsd": 0.0,
        "cacheSavingsUsd": 0.0,
        "costUsd": 0.0,
        "dailySeries": {}
    }


def _extract_fallback_apikey_owners(prev_proj: dict) -> dict:
    fallback_owners = {}
    if not isinstance(prev_proj, dict):
        return fallback_owners
    for pk in (prev_proj.get("apiKeys") or []):
        p_uid = pk.get("uid")
        p_own = pk.get("ownerEmail")
        if p_uid and p_own:
            fallback_owners[p_uid] = {
                "uid": p_uid,
                "ownerEmail": str(p_own).strip().lower(),
                "displayName": pk.get("displayName") or "",
                "createdAt": pk.get("createTime") or "",
                "method": "CreateKey(cached)"
            }
    for pc in (prev_proj.get("credentialsUsage") or []):
        c_id_prev = str(pc.get("credentialId") or "")
        p_own = pc.get("ownerEmail")
        if c_id_prev.startswith("apikey:") and p_own:
            p_uid = c_id_prev.split(":", 1)[1]
            if p_uid and p_uid not in fallback_owners:
                fallback_owners[p_uid] = {
                    "uid": p_uid,
                    "ownerEmail": str(p_own).strip().lower(),
                    "displayName": str(pc.get("resolvedName") or "").replace("API Key: ", "").strip(),
                    "createdAt": "",
                    "method": "CreateKey(cached)"
                }
    return fallback_owners


def _init_project_inspection_dict(proj: dict, budgets: dict) -> dict:
    pid = proj["projectId"]
    return {
        "projectId": pid,
        "name": proj["name"],
        "projectNumber": proj.get("projectNumber"),
        "createTime": proj.get("createTime"),
        "billingEnabled": False,
        "billingAccountName": None,
        "skippedNoBilling": False,
        "aiActive": False,
        "scanStatus": "SCANNED",
        "vertexEnabled": False,
        "geminiApiEnabled": False,
        "geminiFreeTierDetected": False,
        "modelArmorEnabled": False,
        "enabledAiApis": [],
        "vertexFeatures": [],
        "deployedAiResources": [],
        "modelArmor": {
            "enabled": False,
            "permissionGranted": True,
            "status": "DISABLED",
            "statusLabel": "Not Enabled",
            "totalRequests": 0,
            "sanitizeRequests": 0,
            "methodsCalled": [],
            "activeLocations": [],
            "floorSetting": None,
            "templates": []
        },
        "permissions": {},
        "vertexRequests": 0,
        "vertexInferenceRequests": 0,
        "geminiApiRequests": 0,
        "geminiInferenceRequests": 0,
        "inferenceRequests": 0,
        "systemRequests": 0,
        "totalRequests": 0,
        "errors429": 0,
        "errors5xx": 0,
        "httpStatusBreakdown": {"200": 0, "400": 0, "403": 0, "404": 0, "429": 0, "500": 0, "other": 0},
        "avgLatencyMs": 0.0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cachedTokens": 0,
        "thinkingTokens": 0,
        "totalTokens": 0,
        "vertexGrossCostUsd": 0.0,
        "vertexCacheSavingsUsd": 0.0,
        "vertexCostUsd": 0.0,
        "geminiGrossCostUsd": 0.0,
        "geminiCacheSavingsUsd": 0.0,
        "geminiCostUsd": 0.0,
        "geminiRequestBytes": 0,
        "geminiResponseBytes": 0,
        "otherAiGrossCostUsd": 0.0,
        "otherAiCacheSavingsUsd": 0.0,
        "otherAiCostUsd": 0.0,
        "estimatedCostUsd": 0.0,
        "costUsd": 0.0,
        "models": {},
        "credentialsUsage": {},
        "usersUsage": [],
        "apiKeys": [],
        "serviceAccounts": [],
        "dailySeries": {},
        "pricingAtomsVersion": 1,
        "pricingAtoms": {
            "vertex": [],
            "gemini": [],
            "managed": [],
            "dialogflow": [],
        },
        "budgetUsd": budgets.get("projects", {}).get(pid, {}).get("budgetUsd", 100.0),
        "blocked": budgets.get("projects", {}).get(pid, {}).get("blocked", False)
    }


def _ensure_project_pricing_atoms(result: dict) -> dict:
    result.setdefault("pricingAtomsVersion", 1)
    atoms = result.setdefault("pricingAtoms", {"vertex": [], "gemini": [], "managed": [], "dialogflow": []})
    if not isinstance(atoms, dict):
        atoms = {"vertex": [], "gemini": [], "managed": [], "dialogflow": []}
        result["pricingAtoms"] = atoms
    else:
        for k in ("vertex", "gemini", "managed", "dialogflow"):
            if not isinstance(atoms.get(k), list):
                atoms[k] = []
    return atoms


def _mark_transient_scan_error(result: dict, step: str, status: int | None):
    """Google did not answer (429 / 5xx / network) even after retries: the project is NOT denied, just not verified."""
    result["scanStatus"] = "ERROR"
    result["transientError"] = "RATE_LIMITED" if status == 429 else "NOT_VERIFIED"
    result["transientErrorStep"] = step
    detail = f"HTTP {status}" if status else ("network error" if status == 0 else "HTTP 429/5xx or network error")
    result["error"] = f"{step}: {detail} (check not completed, retry)"
    result["skippedNoBilling"] = False
    # Same shape as the other early exits: the UI iterates these as lists
    result["models"] = []
    result["credentialsUsage"] = []


def _check_billing_and_enabled_services(proj: dict, pid: str, token: str, ba_cache: dict, result: dict, prev_proj: dict = None):
    bill_url = f"https://cloudbilling.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/billingInfo"
    b_status, b_data = gcp_api_get(bill_url, token, timeout=6)
    prev_ok = (
        isinstance(prev_proj, dict)
        and not prev_proj.get("transientError")
        and prev_proj.get("scanStatus") not in ("ERROR", "SKIPPED_BY_SYNC_RULE", "BILLING_PERMISSION_DENIED")
    )
    if b_status == 0 or b_status in GCP_RETRY_STATUSES:
        if prev_ok and "billingEnabled" in prev_proj:
            b_status = 200
            result["billingEnabled"] = bool(prev_proj.get("billingEnabled", False))
            result["billingAccountName"] = prev_proj.get("billingAccountName", "")
        else:
            _mark_transient_scan_error(result, "billingInfo", b_status)
            return True, b_status, False, 0, set(), set(), set()
    elif b_status == 200:
        result["billingEnabled"] = bool(b_data.get("billingEnabled", False))
        result["billingAccountName"] = b_data.get("billingAccountName", "")
    else:
        result["billingEnabled"] = False

    pid_low = pid.lower()
    name_low = (proj.get("name") or "").lower()
    is_ai_studio_candidate = (
        pid_low.startswith("gen-lang-client-") or
        any(k in pid_low or k in name_low for k in ("gemini", "aistudio", "ai-studio", "generative"))
    )
    result["isAiStudioProject"] = pid_low.startswith("gen-lang-client-") or ("aistudio" in pid_low) or ("gemini api" in name_low)

    if not result["billingEnabled"]:
        if not is_ai_studio_candidate:
            result["skippedNoBilling"] = True
            result["scanStatus"] = "SKIPPED_NO_BILLING" if b_status == 200 else "BILLING_PERMISSION_DENIED"
            result["models"] = []
            result["credentialsUsage"] = []
            result["permissions"] = build_project_permissions_summary(
                b_status=b_status,
                billing_enabled=False,
                ba_granted=False,
                su_status=0,
                granted_perms={"resourcemanager.projects.get"},
                k_status=0,
                sa_status=0
            )
            return True, b_status, False, 0, set(), set(), set()
        result["skippedNoBilling"] = False
        result["freeTierNoBilling"] = True

    su_url = f"https://serviceusage.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/services?filter=state:ENABLED&pageSize=200"
    with ThreadPoolExecutor(max_workers=3) as step1_pool:
        fut_ba = step1_pool.submit(check_billing_account_access, result["billingAccountName"], token, ba_cache) if result["billingEnabled"] else None
        fut_su = step1_pool.submit(gcp_api_get, su_url, token, 8)
        fut_iam = step1_pool.submit(check_project_iam_permissions, pid, token)
        ba_granted = fut_ba.result() if fut_ba else False
        su_status, su_data = fut_su.result()
        granted_perms_raw = fut_iam.result()

    if granted_perms_raw is None:
        prev_perms = (prev_proj.get("permissions") or {}).get("grantedIamPermissions") if prev_ok else None
        if prev_perms:
            granted_perms_raw = set(prev_perms)
        else:
            _mark_transient_scan_error(result, "testIamPermissions", None)
            return True, b_status, ba_granted, su_status, set(), set(), set()
    if su_status == 0 or su_status in GCP_RETRY_STATUSES:
        if prev_ok and prev_proj.get("scanStatus") not in ("NO_PERMISSIONS_403", "PARTIAL_NO_SERVICEUSAGE") and isinstance(prev_proj.get("enabledAiApis"), list):
            su_status = 200
            su_data = {
                "services": [
                    {"config": {"name": (a.get("service") if isinstance(a, dict) else str(a))}}
                    for a in prev_proj.get("enabledAiApis", [])
                    if a
                ]
            }
        else:
            # Without the enabled-API list we cannot tell whether the project uses AI: not verified, not "AI active"
            _mark_transient_scan_error(result, "serviceusage", su_status)
            return True, b_status, ba_granted, su_status, set(), set(), set()

    enabled_services_set = set()
    all_enabled_services = set()
    if su_status == 200:
        for s_item in su_data.get("services", []):
            s_name = s_item.get("config", {}).get("name", "")
            if s_name:
                all_enabled_services.add(s_name)
            if s_name in AI_SERVICES_CATALOG:
                enabled_services_set.add(s_name)
                cat_info = AI_SERVICES_CATALOG[s_name]
                result["enabledAiApis"].append({
                    "service": s_name,
                    "label": cat_info["label"],
                    "category": cat_info["category"],
                    "icon": cat_info["icon"],
                    "description": cat_info["description"]
                })

    has_core_ai_api = any(s in CORE_AI_SERVICE_NAMES for s in enabled_services_set)
    if "aiplatform.googleapis.com" in enabled_services_set:
        result["vertexEnabled"] = True
    if "generativelanguage.googleapis.com" in enabled_services_set:
        result["geminiApiEnabled"] = True
    if "modelarmor.googleapis.com" in enabled_services_set:
        result["modelArmorEnabled"] = True

    if su_status == 200 and not has_core_ai_api:
        result["aiActive"] = False
        result["enabledAiApis"] = []
        result["scanStatus"] = "SKIPPED_NO_AI_API"
        result["models"] = []
        result["credentialsUsage"] = []
        result["permissions"] = build_project_permissions_summary(
            b_status=b_status,
            billing_enabled=True,
            ba_granted=ba_granted,
            su_status=su_status,
            granted_perms=set(PROJECT_IAM_PERMISSIONS_TO_CHECK),
            k_status=200,
            sa_status=200,
            enabled_ai_apis_count=0
        )
        return True, b_status, ba_granted, su_status, set(), enabled_services_set, all_enabled_services

    granted_perms = set(granted_perms_raw)
    granted_perms.add("resourcemanager.projects.get")
    if su_status == 200:
        granted_perms.add("serviceusage.services.list")

    result["aiActive"] = True
    if su_status != 200 and "monitoring.timeSeries.list" not in granted_perms:
        result["scanStatus"] = "NO_PERMISSIONS_403"
    elif su_status != 200:
        result["scanStatus"] = "PARTIAL_NO_SERVICEUSAGE"

    return False, b_status, ba_granted, su_status, granted_perms, enabled_services_set, all_enabled_services


# Base minima: serie gemini_in_tok, gemini_in_tok_2, gemini_in_tok_3 (sempre richieste)
GEMINI_BASE_TIER_SUFFIXES = ("", "_2", "_3")
GEMINI_MAX_TIER_SUFFIXES = 8
_GEMINI_TIER_TYPE_RE = re.compile(
    r"^generativelanguage\.googleapis\.com/quota/generate_content_paid_tier(_[0-9]{1,2})?_input_token_count/usage$"
)
_GEMINI_IN_TOK_KEY_RE = re.compile(r"^gemini_in_tok(_[0-9]{1,2})?$")


def _discover_gemini_tier_suffixes(pid: str, token: str, result: dict) -> list:
    """Suffissi delle fasce paid-tier di input token Gemini API: base minima (3 attuali) piu' quelle
    trovate nei metricDescriptors (sola lettura). Qualsiasi errore -> solo la base. Una chiamata per scansione."""
    cached = result.get("_geminiTierSfx")
    if isinstance(cached, list):
        return cached
    found = set(GEMINI_BASE_TIER_SUFFIXES)
    read_ok = False
    try:
        flt = 'metric.type=starts_with("generativelanguage.googleapis.com/quota/generate_content_paid_tier")'
        url = (
            f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(pid)}/metricDescriptors?"
            + urllib.parse.urlencode({"filter": flt, "pageSize": 200})
        )
        status, data = gcp_api_get(url, token, timeout=15)
        if status == 200 and isinstance(data, dict):
            read_ok = True
            for d in data.get("metricDescriptors") or []:
                m = _GEMINI_TIER_TYPE_RE.match(str((d or {}).get("type") or ""))
                if m:
                    found.add(m.group(1) or "")
    except Exception:
        found = set(GEMINI_BASE_TIER_SUFFIXES)
        read_ok = False
    result["_geminiTierOk"] = read_ok
    extra = sorted((x for x in found if x not in GEMINI_BASE_TIER_SUFFIXES), key=lambda x: int(x[1:]))
    out = (list(GEMINI_BASE_TIER_SUFFIXES) + extra)[:GEMINI_MAX_TIER_SUFFIXES]
    result["_geminiTierSfx"] = out
    return out


GEMINI_MAX_FREE_TIER_METRICS = 8
_GEMINI_FREE_TIER_PREFIX = "generativelanguage.googleapis.com/quota/generate_content_free_tier"
_GEMINI_FREE_TIER_SUFFIX = "_input_token_count/usage"
_GEMINI_FREE_IN_TOK_KEY_RE = re.compile(r"^gemini_free_in_tok_[0-9]{1,2}$")


def _discover_gemini_free_tier_metric_types(pid: str, token: str) -> list:
    """Free-tier input token quota metric types of the Gemini API, read only from the metricDescriptors
    (no invented names). Any error or nothing found -> empty list (behaviour unchanged)."""
    out = []
    try:
        flt = f'metric.type=starts_with("{_GEMINI_FREE_TIER_PREFIX}")'
        url = (
            f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(pid)}/metricDescriptors?"
            + urllib.parse.urlencode({"filter": flt, "pageSize": 200})
        )
        status, data = gcp_api_get(url, token, timeout=15)
        if status == 200 and isinstance(data, dict):
            for d in data.get("metricDescriptors") or []:
                t = str((d or {}).get("type") or "")
                if t.startswith(_GEMINI_FREE_TIER_PREFIX) and t.endswith(_GEMINI_FREE_TIER_SUFFIX) and t not in out:
                    out.append(t)
    except Exception:
        return []
    return sorted(out)[:GEMINI_MAX_FREE_TIER_METRICS]


def _prefetch_project_monitoring_metrics(
    pid: str, token: str, start_iso: str, end_iso: str,
    can_read_monitoring: bool, su_status: int,
    enabled_services_set: set, all_enabled_services: set, result: dict
) -> dict:
    if not can_read_monitoring:
        return {}
    monitored_services = [
        "aiplatform.googleapis.com",
        "generativelanguage.googleapis.com",
        "modelarmor.googleapis.com",
        "discoveryengine.googleapis.com",
        "dialogflow.googleapis.com",
        "ces.googleapis.com",
        "contactcenterinsights.googleapis.com",
        "agentregistry.googleapis.com",
        "notebooks.googleapis.com",
        "documentai.googleapis.com",
        "vision.googleapis.com",
        "visionai.googleapis.com",
        "speech.googleapis.com",
        "texttospeech.googleapis.com",
        "translate.googleapis.com",
        "cloudaicompanion.googleapis.com",
        "geminicloudassist.googleapis.com"
    ]
    svc_or_clause = " OR ".join(f'resource.labels.service="{s}"' for s in monitored_services)
    req_filter = f'metric.type="serviceruntime.googleapis.com/api/request_count" AND ({svc_or_clause})'
    lat_filter = f'metric.type="serviceruntime.googleapis.com/api/request_latencies" AND ({svc_or_clause})'
    req_b_filter = 'metric.type="serviceruntime.googleapis.com/api/request_sizes" AND resource.labels.service="generativelanguage.googleapis.com"'
    resp_b_filter = 'metric.type="serviceruntime.googleapis.com/api/response_sizes" AND resource.labels.service="generativelanguage.googleapis.com"'
    grp_b = ["resource.label.credential_id", "resource.label.method", "resource.label.location"]
    tok_filter = 'metric.type="aiplatform.googleapis.com/publisher/online_serving/token_count"'
    inv_filter = 'metric.type="aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"'
    df_multi_filter = 'metric.type="dialogflow.googleapis.com/quota/ConversationalAgentMultiRegionLLMTokenConsumption/usage"'
    df_loc_filter = 'metric.type="dialogflow.googleapis.com/quota/ConversationalAgentLLMTokenConsumption/usage"'

    mon_specs = {
        "req_count": (
            req_filter,
            [
                "resource.label.service",
                "resource.label.method",
                "resource.label.credential_id",
                "resource.label.location",
                "metric.label.response_code"
            ],
            "ALIGN_SUM"
        ),
        "req_lat": (lat_filter, ["resource.label.service"], "ALIGN_DELTA"),
    }
    if result["geminiApiEnabled"] or result.get("isAiStudioProject") or su_status != 200:
        mon_specs["gemini_req_b"] = (req_b_filter, grp_b, "ALIGN_SUM")
        mon_specs["gemini_resp_b"] = (resp_b_filter, grp_b, "ALIGN_SUM")
        mon_specs["gemini_out_tok"] = (
            'metric.type="generativelanguage.googleapis.com/generate_content_usage_output_token_count"',
            ["metric.label.model"],
            "ALIGN_SUM"
        )
        # Monitoring accepts a single metric.type per query: one spec per paid quota tier
        for tier_sfx in _discover_gemini_tier_suffixes(pid, token, result):
            mon_specs[f"gemini_in_tok{tier_sfx}"] = (
                f'metric.type="generativelanguage.googleapis.com/quota/generate_content_paid_tier{tier_sfx}_input_token_count/usage"',
                ["metric.label.model"],
                "ALIGN_SUM"
            )
        # Free-tier input tokens: one spec per discovered metric type (empty list -> nothing added)
        free_types = _discover_gemini_free_tier_metric_types(pid, token)
        for i_ft, ft_type in enumerate(free_types):
            mon_specs[f"gemini_free_in_tok_{i_ft}"] = (f'metric.type="{ft_type}"', ["metric.label.model"], "ALIGN_SUM")
        result["geminiFreeTierDetected"] = bool(free_types)
        # helper cache is dropped; the discovered tiers stay as a plain diagnostic field (which quota tiers were read)
        result["geminiQuotaDiscovery"] = "ok" if result.pop("_geminiTierOk", False) else "fallback"
        result["geminiQuotaTiers"] = [("tier1" if not x else "tier" + x.lstrip("_")) for x in (result.pop("_geminiTierSfx", None) or [])]
    if result["vertexEnabled"] or su_status != 200:
        mon_specs["vertex_tok"] = (
            tok_filter,
            ["resource.label.model_user_id", "resource.label.location", "metric.label.type"],
            "ALIGN_SUM"
        )
        mon_specs["vertex_inv"] = (
            inv_filter,
            ["resource.label.model_user_id", "resource.label.location"],
            "ALIGN_SUM"
        )
    if "dialogflow.googleapis.com" in enabled_services_set or "ces.googleapis.com" in enabled_services_set or su_status != 200:
        mon_specs["df_multi"] = (df_multi_filter, ["metric.label.base_model", "resource.label.multi_region"], "ALIGN_SUM")
        mon_specs["df_loc"] = (df_loc_filter, ["metric.label.base_model", "resource.label.location"], "ALIGN_SUM")

    mon_results = {}
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(mon_specs)))) as mon_pool:
        mon_futs = {
            mon_pool.submit(
                fetch_monitoring_timeseries,
                pid, token, m_flt, start_iso, end_iso,
                group_by_fields=m_grp,
                aligner=m_alg
            ): m_key
            for m_key, (m_flt, m_grp, m_alg) in mon_specs.items()
        }
        for fut in as_completed(mon_futs):
            m_key = mon_futs[fut]
            try:
                mon_results[m_key] = fut.result()
            except Exception:
                mon_results[m_key] = []
    return mon_results


def managed_call_price(service: str, method: str, calls: int) -> tuple[float, float, int, int, str, str]:
    """(gross USD, savings USD, input tokens, output tokens, model label, cost source) for per-call managed AI services."""
    unit_cost, unit_in_tok, unit_out_tok, svc_model_id, svc_cost_src = estimate_service_call_cost(service, method)
    if unit_cost <= 0 and unit_in_tok <= 0:
        return (0.0, 0.0, 0, 0, "", "")
    n = int(calls)
    est_in = n * unit_in_tok
    est_out = n * unit_out_tok
    est_gross = n * unit_cost
    if service in (
        "discoveryengine.googleapis.com",
        "cloudaicompanion.googleapis.com",
        "geminicloudassist.googleapis.com",
        "dialogflow.googleapis.com",
        "ces.googleapis.com",
    ):
        bs_ms = get_billing_settings()
        sav_ratio = max(0.0, min(1.0, float(bs_ms.get("managedServiceSavingsPct", 0.0) or 0.0) / 100.0))
        est_sav = est_gross * sav_ratio
    else:
        est_sav = 0.0
    return (est_gross, est_sav, est_in, est_out, svc_model_id, svc_cost_src)


def _apply_managed_ai_service_point(
    result: dict, c_entry: dict, p_day: dict, c_day: dict,
    service: str, method: str, loc: str, end_t: str, val: int
):
    atoms = _ensure_project_pricing_atoms(result)
    est_gross, est_sav, est_in, est_out, svc_model_id, svc_cost_src = managed_call_price(service, method, val)
    if not svc_model_id and est_gross <= 0 and est_in <= 0:
        return
    if val > 0:
        cred_id = str(c_entry.get("credentialId") or "unknown")
        loc_clean = loc or "global"
        day_clean = str(end_t or "")[:10]
        m_list = atoms["managed"]
        for rec in m_list:
            if (
                rec.get("c") == cred_id
                and rec.get("svc") == service
                and rec.get("meth") == method
                and rec.get("loc") == loc_clean
                and rec.get("d") == day_clean
            ):
                rec["n"] += int(val)
                break
        else:
            m_list.append({
                "c": cred_id,
                "svc": service,
                "meth": method,
                "loc": loc_clean,
                "d": day_clean,
                "n": int(val),
            })
    est_tot = est_in + est_out
    # Per-call services are billed per request: no cached-token share is estimated for them
    est_cache_tok = 0
    est_cost = est_gross - est_sav

    for bucket in (p_day, c_day):
        bucket["inputTokens"] += est_in
        bucket["outputTokens"] += est_out
        bucket["cachedTokens"] += est_cache_tok
        bucket["tokens"] += est_tot
        bucket["otherAiCostUsd"] += est_cost
        bucket["costUsd"] += est_cost

    c_entry["inputTokens"] += est_in
    c_entry["outputTokens"] += est_out
    c_entry["cachedTokens"] += est_cache_tok
    c_entry["totalTokens"] += est_tot
    c_entry["grossCostUsd"] += est_gross
    c_entry["cacheSavingsUsd"] += est_sav
    c_entry["estimatedCostUsd"] += est_cost
    if c_entry["costSource"] == "NONE":
        c_entry["costSource"] = svc_cost_src

    result["inputTokens"] += est_in
    result["outputTokens"] += est_out
    result["cachedTokens"] += est_cache_tok
    result["totalTokens"] += est_tot
    result["otherAiGrossCostUsd"] += est_gross
    result["otherAiCacheSavingsUsd"] += est_sav
    result["otherAiCostUsd"] += est_cost
    result["estimatedCostUsd"] += est_cost

    sm_entry = result["models"].setdefault(svc_model_id, _new_model_usage_entry(svc_model_id, service=service))
    sm_entry["locations"].add(loc or "global")
    sm_entry["invocations"] += val
    sm_entry["inputTokens"] += est_in
    sm_entry["outputTokens"] += est_out
    sm_entry["cachedTokens"] += est_cache_tok
    sm_entry["totalTokens"] += est_tot
    sm_entry["grossCostUsd"] = sm_entry.get("grossCostUsd", 0.0) + est_gross
    sm_entry["cacheSavingsUsd"] = sm_entry.get("cacheSavingsUsd", 0.0) + est_sav
    sm_entry["costUsd"] += est_cost
    sm_day = sm_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
    sm_day["requests"] += val
    sm_day["inferenceRequests"] += val
    sm_day["inputTokens"] += est_in
    sm_day["outputTokens"] += est_out
    sm_day["cachedTokens"] += est_cache_tok
    sm_day["tokens"] += est_tot
    sm_day["otherAiCostUsd"] += est_cost
    sm_day["costUsd"] += est_cost


def _process_serviceruntime_requests_and_latencies(
    mon_results: dict, can_read_monitoring: bool, result: dict,
    features_map: dict, active_locations_seen: set, ma_metrics: dict
) -> dict:
    gemini_ok_calls_map = {}
    req_series = mon_results.get("req_count", []) if can_read_monitoring else []

    for ts in req_series:
        r_labels = ts.get("resource", {}).get("labels", {})
        m_labels = ts.get("metric", {}).get("labels", {})
        service = r_labels.get("service", "")
        method = r_labels.get("method", "")
        cred_id = r_labels.get("credential_id", "unknown")
        loc = r_labels.get("location", "global")
        resp_code = str(m_labels.get("response_code", "200"))
        is_inf = is_inference_method(method)
        short_m = method.split(".")[-1] if method else "unknown"

        if loc:
            active_locations_seen.add(loc)

        c_entry = result["credentialsUsage"].setdefault(cred_id, {
            "credentialId": cred_id,
            "service": service,
            "services": set(),
            "requests": 0,
            "inferenceRequests": 0,
            "vertexInferenceRequests": 0,
            "systemRequests": 0,
            "ok200": 0,
            "ok200Inference": 0,
            "errors429": 0,
            "otherErrors": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "cachedTokens": 0,
            "totalTokens": 0,
            "requestBytes": 0,
            "responseBytes": 0,
            "grossCostUsd": 0.0,
            "cacheSavingsUsd": 0.0,
            "estimatedCostUsd": 0.0,
            "costSource": "NONE",
            "methods": set(),
            "inferenceMethods": set(),
            "systemMethods": set(),
            "dailySeries": {}
        })
        if service:
            c_entry["services"].add(service)
            if c_entry["service"] != "generativelanguage.googleapis.com" and service == "generativelanguage.googleapis.com":
                c_entry["service"] = service

        pts_sum = 0
        for pt in ts.get("points", []):
            val = int(pt.get("value", {}).get("int64Value", 0) or 0)
            if val <= 0:
                continue
            pts_sum += val
            end_t = pt.get("interval", {}).get("endTime", "")[:10]
            if not end_t:
                continue
            p_day = result["dailySeries"].setdefault(end_t, empty_day_bucket())
            c_day = c_entry["dailySeries"].setdefault(end_t, empty_day_bucket())

            p_day["requests"] += val
            c_day["requests"] += val
            if is_inf:
                p_day["inferenceRequests"] += val
                c_day["inferenceRequests"] += val
                if service == "aiplatform.googleapis.com":
                    p_day["vertexInferenceRequests"] += val
                    c_day["vertexInferenceRequests"] += val
            else:
                p_day["systemRequests"] += val
                c_day["systemRequests"] += val

            if service == "aiplatform.googleapis.com":
                p_day["vertexRequests"] += val
                c_day["vertexRequests"] += val
            elif service == "generativelanguage.googleapis.com":
                p_day["geminiApiRequests"] += val
                c_day["geminiApiRequests"] += val

            if resp_code == "200":
                p_day["ok200"] += val
                c_day["ok200"] += val
                if is_inf:
                    p_day["ok200Inference"] += val
                    c_day["ok200Inference"] += val
            elif resp_code == "429":
                p_day["errors429"] += val
                c_day["errors429"] += val

            if service == "generativelanguage.googleapis.com" and is_inf and resp_code == "200":
                g_key = (cred_id, short_m, loc or "global", end_t)
                gemini_ok_calls_map[g_key] = gemini_ok_calls_map.get(g_key, 0) + val
            elif service not in ("aiplatform.googleapis.com", "generativelanguage.googleapis.com") and is_inf and resp_code == "200":
                _apply_managed_ai_service_point(result, c_entry, p_day, c_day, service, method, loc, end_t, val)

        if pts_sum <= 0:
            continue

        if service == "modelarmor.googleapis.com":
            result["modelArmorEnabled"] = True
            ma_metrics["totalRequests"] += pts_sum
            if "sanitize" in short_m.lower():
                ma_metrics["sanitizeRequests"] += pts_sum
            if short_m:
                ma_metrics["methods"].add(short_m)
            if loc:
                ma_metrics["locations"].add(loc)

        subf = classify_vertex_subfeature(service, method)
        if subf:
            f_entry = features_map.setdefault(subf["id"], {
                "id": subf["id"],
                "name": subf["name"],
                "service": service,
                "category": subf["category"],
                "icon": subf["icon"],
                "description": subf["description"],
                "status": "ACTIVE_TRAFFIC",
                "requests": 0,
                "inferenceRequests": 0,
                "methods": set(),
                "locations": set()
            })
            f_entry["status"] = "ACTIVE_TRAFFIC"
            f_entry["requests"] += pts_sum
            if is_inf:
                f_entry["inferenceRequests"] += pts_sum
            if short_m:
                f_entry["methods"].add(short_m)
            if loc:
                f_entry["locations"].add(loc)

        if service == "aiplatform.googleapis.com":
            result["vertexEnabled"] = True
            result["vertexRequests"] += pts_sum
            if is_inf:
                result["vertexInferenceRequests"] += pts_sum
                c_entry["vertexInferenceRequests"] += pts_sum
        elif service == "generativelanguage.googleapis.com":
            result["geminiApiEnabled"] = True
            result["geminiApiRequests"] += pts_sum
            if is_inf:
                result["geminiInferenceRequests"] += pts_sum

        result["totalRequests"] += pts_sum
        if is_inf:
            result["inferenceRequests"] += pts_sum
            c_entry["inferenceRequests"] += pts_sum
            c_entry["inferenceMethods"].add(short_m)
        else:
            result["systemRequests"] += pts_sum
            c_entry["systemRequests"] += pts_sum
            c_entry["systemMethods"].add(short_m)

        if resp_code == "429":
            result["errors429"] += pts_sum
        elif resp_code.startswith("5"):
            result["errors5xx"] += pts_sum

        hb = result.setdefault("httpStatusBreakdown", {"200": 0, "400": 0, "403": 0, "404": 0, "429": 0, "500": 0, "other": 0})
        if resp_code in hb:
            hb[resp_code] += pts_sum
        elif resp_code.startswith("5"):
            hb["500"] += pts_sum
        else:
            hb["other"] += pts_sum

        c_entry["requests"] += pts_sum
        if resp_code == "200":
            c_entry["ok200"] += pts_sum
            if is_inf:
                c_entry["ok200Inference"] += pts_sum
        elif resp_code == "429":
            c_entry["errors429"] += pts_sum
        else:
            c_entry["otherErrors"] += pts_sum
        if method:
            c_entry["methods"].add(short_m)

    if can_read_monitoring and result["totalRequests"] > 0:
        with contextlib.suppress(KeyError, TypeError, ValueError, ZeroDivisionError):
            lat_series = mon_results.get("req_lat", [])
            lat_weighted_sum = 0.0
            lat_total_cnt = 0
            for lts in lat_series:
                for pt in lts.get("points", []):
                    dist = pt.get("value", {}).get("distributionValue", {})
                    cnt = int(dist.get("count", 0) or 0)
                    mean_val = float(dist.get("mean", 0.0) or 0.0)
                    if cnt > 0 and mean_val > 0:
                        ms_val = (mean_val / 1000.0) if mean_val > 50000 else mean_val
                        lat_weighted_sum += (ms_val * cnt)
                        lat_total_cnt += cnt
            if lat_total_cnt > 0:
                result["avgLatencyMs"] = round(lat_weighted_sum / lat_total_cnt, 1)

    return gemini_ok_calls_map

def _gemini_api_credit_discount_ratio() -> float:
    """Billing credit discount applied to Gemini API (AI Studio) estimates, from billingSettings (default 0)."""
    try:
        pct = float(get_billing_settings().get("geminiApiBillingCreditDiscountPct", 0.0) or 0.0)
    except (TypeError, ValueError):
        pct = 0.0
    return max(0.0, min(0.95, pct / 100.0))


# Model whose rates price the Gemini API fallbacks (payload bytes / per-call estimate), where the model is unknown
GEMINI_API_FALLBACK_MODEL = "gemini-2.5-flash"


def gemini_api_token_price(model_lbl: str, in_tok: int, out_tok: int) -> tuple[int, float, float]:
    """(cached input tokens, gross USD, credit savings USD) for paid Gemini API tokens.

    Same formula for the token-metric path and both fallbacks, and reused by the instant repricing:
    the configured implicit cache share of the input is billed at the cached-input rate.
    """
    rates = get_gemini_api_rates(model_lbl)
    cached_tok = int(round(in_tok * (float(rates.get("cacheHitRatioPct", 0.0) or 0.0) / 100.0)))
    gross_usd = (
        (in_tok - cached_tok) * rates["input"]
        + cached_tok * rates["cache_read_input"]
        + out_tok * rates["output"]
    ) / 1_000_000.0
    return cached_tok, gross_usd, gross_usd * _gemini_api_credit_discount_ratio()


GEMINI_API_UNATTRIBUTED_ID = "gemini-api:unattributed"
GEMINI_API_UNATTRIBUTED_LABEL = "Gemini API — usage not attributable to a credential"


def _process_gemini_api_payload_bytes(
    mon_results: dict, pid: str, token: str, start_iso: str, end_iso: str,
    can_read_monitoring: bool, gemini_ok_calls_map: dict, result: dict
):
    atoms = _ensure_project_pricing_atoms(result)
    if not can_read_monitoring or (result["geminiApiRequests"] <= 0 and len(gemini_ok_calls_map) == 0):
        return
    req_b_filter = 'metric.type="serviceruntime.googleapis.com/api/request_sizes" AND resource.labels.service="generativelanguage.googleapis.com"'
    resp_b_filter = 'metric.type="serviceruntime.googleapis.com/api/response_sizes" AND resource.labels.service="generativelanguage.googleapis.com"'
    grp_b = ["resource.label.credential_id", "resource.label.method", "resource.label.location"]

    req_b_series = mon_results.get("gemini_req_b") if "gemini_req_b" in mon_results else fetch_monitoring_timeseries(pid, token, req_b_filter, start_iso, end_iso, group_by_fields=grp_b)
    resp_b_series = mon_results.get("gemini_resp_b") if "gemini_resp_b" in mon_results else fetch_monitoring_timeseries(pid, token, resp_b_filter, start_iso, end_iso, group_by_fields=grp_b)

    req_bytes_map = {}
    req_cnt_map = {}
    resp_bytes_map = {}

    for ts in req_b_series:
        r_lbl = ts.get("resource", {}).get("labels", {})
        c_id = r_lbl.get("credential_id", "unknown")
        raw_m = r_lbl.get("method", "")
        if not is_inference_method(raw_m):
            continue
        s_m = raw_m.split(".")[-1] if raw_m else "GenerateContent"
        loc = r_lbl.get("location", "global") or "global"
        for pt in ts.get("points", []):
            end_t = pt.get("interval", {}).get("endTime", "")[:10]
            if not end_t:
                continue
            d_val = pt.get("value", {}).get("distributionValue", {}) or {}
            cnt = int(d_val.get("count", 0) or 0)
            mean = float(d_val.get("mean", 0.0) or 0.0)
            b_tot = int(round(cnt * mean))
            if b_tot > 0 or cnt > 0:
                g_key = (c_id, s_m, loc, end_t)
                req_bytes_map[g_key] = req_bytes_map.get(g_key, 0) + b_tot
                req_cnt_map[g_key] = req_cnt_map.get(g_key, 0) + cnt

    for ts in resp_b_series:
        r_lbl = ts.get("resource", {}).get("labels", {})
        c_id = r_lbl.get("credential_id", "unknown")
        raw_m = r_lbl.get("method", "")
        if not is_inference_method(raw_m):
            continue
        s_m = raw_m.split(".")[-1] if raw_m else "GenerateContent"
        loc = r_lbl.get("location", "global") or "global"
        for pt in ts.get("points", []):
            end_t = pt.get("interval", {}).get("endTime", "")[:10]
            if not end_t:
                continue
            d_val = pt.get("value", {}).get("distributionValue", {}) or {}
            cnt = int(d_val.get("count", 0) or 0)
            mean = float(d_val.get("mean", 0.0) or 0.0)
            b_tot = int(round(cnt * mean))
            if b_tot > 0:
                g_key = (c_id, s_m, loc, end_t)
                resp_bytes_map[g_key] = resp_bytes_map.get(g_key, 0) + b_tot

    all_g_keys = sorted(set(gemini_ok_calls_map.keys()) | set(req_bytes_map.keys()) | set(resp_bytes_map.keys()))

    # Exact per-model token counts from Cloud Monitoring: output metric + paid-tier input quota metrics.
    # (Cached tokens are NOT separated by Google: they come from geminiApiCacheHitRatioPct settings.)
    # Slots per (day, model): [paid input, output, free-tier input].
    tok_by_day_model: dict = {}
    in_tok_keys = sorted((k for k in mon_results if _GEMINI_IN_TOK_KEY_RE.match(str(k))), key=str)[:GEMINI_MAX_TIER_SUFFIXES]
    free_tok_keys = sorted((k for k in mon_results if _GEMINI_FREE_IN_TOK_KEY_RE.match(str(k))), key=str)[:GEMINI_MAX_FREE_TIER_METRICS]
    for idx, series_key in [(0, k) for k in in_tok_keys] + [(1, "gemini_out_tok")] + [(2, k) for k in free_tok_keys]:
        for ts in (mon_results.get(series_key) or []):
            model_lbl = str(((ts.get("metric") or {}).get("labels") or {}).get("model") or "").strip().lower()
            if not model_lbl:
                continue
            for pt in ts.get("points", []):
                end_t = pt.get("interval", {}).get("endTime", "")[:10]
                val = int(pt.get("value", {}).get("int64Value", 0) or 0)
                if end_t and val > 0:
                    tok_by_day_model.setdefault(end_t, {}).setdefault(model_lbl, [0, 0, 0])[idx] += val

    def _key_calls(k) -> int:
        return gemini_ok_calls_map.get(k, 0) or req_cnt_map.get(k, 0)

    def _key_bytes(k) -> int:
        return req_bytes_map.get(k, 0) + resp_bytes_map.get(k, 0)

    def _day_weights(day_keys: list) -> dict:
        # One unit per day: bytes only if EVERY credential of the day has them, otherwise calls for all (no mixed units).
        if day_keys and all(_key_bytes(k) > 0 for k in day_keys):
            return {k: _key_bytes(k) for k in day_keys}
        return {k: _key_calls(k) for k in day_keys}

    keys_by_day: dict = {}
    for g_key in all_g_keys:
        keys_by_day.setdefault(g_key[3], []).append(g_key)
    for day_t in tok_by_day_model:
        if day_t not in keys_by_day:
            synth = (GEMINI_API_UNATTRIBUTED_ID, "GenerateContent", "global", day_t)
            keys_by_day[day_t] = [synth]
            all_g_keys.append(synth)

    entries = []
    for g_key in all_g_keys:
        cred_id, short_m, loc, end_t = g_key
        calls = _key_calls(g_key)
        req_b = req_bytes_map.get(g_key, 0)
        resp_b = resp_bytes_map.get(g_key, 0)
        day_models = tok_by_day_model.get(end_t)
        if day_models:
            day_keys = keys_by_day.get(end_t) or [g_key]
            weights = _day_weights(day_keys)
            w_tot = sum(weights.values())
            share = (weights.get(g_key, 0) / w_tot) if w_tot > 0 else (1.0 / len(day_keys))
            out_day_tot = sum(v[1] for v in day_models.values())
            for model_lbl, (m_in, m_out, m_free_in) in day_models.items():
                # Free tier only when free-tier input exists and paid-tier input is zero for that (day, model)
                is_free = m_free_in > 0 and m_in <= 0
                in_tok = int(round((m_free_in if is_free else m_in) * share))
                out_tok = int(round(m_out * share))
                if in_tok <= 0 and out_tok <= 0:
                    continue
                m_share = (m_out / out_day_tot) if out_day_tot > 0 else (1.0 / len(day_models))
                if is_free:
                    cached_tok = 0
                    gross_usd = 0.0
                    _sav = 0.0
                    result["geminiFreeTierDetected"] = True
                else:
                    cached_tok, gross_usd, _sav = gemini_api_token_price(model_lbl, in_tok, out_tok)
                entries.append({
                    "cred_id": cred_id, "short_m": short_m, "loc": loc, "end_t": end_t,
                    "calls": int(round(calls * m_share)),
                    "req_b": int(round(req_b * m_share)), "resp_b": int(round(resp_b * m_share)),
                    "in_tok": in_tok, "out_tok": out_tok, "cached_tok": cached_tok,
                    "gross_usd": gross_usd, "cache_sav_usd": _sav,
                    "gm_id": f"{model_lbl} (Gemini API)",
                    "price_model": model_lbl,
                    "cost_src": "GEMINI_API_FREE_TIER" if is_free else "GEMINI_API_TOKEN_METRICS",
                    "free_tier": is_free,
                })
            continue

        # Fallback (no token metrics for that day): estimate from payload bytes / call counts
        if calls <= 0 and req_b <= 0 and resp_b <= 0:
            continue
        if req_b > 0 or resp_b > 0:
            # Neutral estimate: ~4 bytes per token on both request and response, rates and implicit cache
            # share of the default model (no fixed multipliers). On streams the response bytes include the
            # SSE/JSON framing of every chunk, so the output estimate is an upper bound.
            in_tok = int(round(req_b / 4.0))
            if "stream" in short_m.lower():
                out_tok = int(round(resp_b / 4.0)) if resp_b > 0 else int(calls * GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL)
                gm_id = "gemini-2.5-pro / flash — StreamGenerateContent (Gemini API Stream)"
            else:
                out_tok = int(round(resp_b / 4.0))
                gm_id = "gemini-2.5-flash / pro — GenerateContent (AI Studio API Key)"
            cached_tok, gross_usd, cache_sav_usd = gemini_api_token_price(GEMINI_API_FALLBACK_MODEL, in_tok, out_tok)
            cost_src = "GEMINI_API_PAYLOAD_BYTES"
        else:
            in_tok = calls * GEMINI_API_EST_INPUT_TOKENS_PER_CALL
            out_tok = calls * GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL
            cached_tok, gross_usd, cache_sav_usd = gemini_api_token_price(GEMINI_API_FALLBACK_MODEL, in_tok, out_tok)
            gm_id = "gemini-2.5-flash (AI Studio API Key)"
            cost_src = "AI_STUDIO_ESTIMATE"
        entries.append({
            "cred_id": cred_id, "short_m": short_m, "loc": loc, "end_t": end_t, "calls": calls,
            "req_b": req_b, "resp_b": resp_b, "in_tok": in_tok, "out_tok": out_tok, "cached_tok": cached_tok,
            "gross_usd": gross_usd, "cache_sav_usd": cache_sav_usd, "gm_id": gm_id,
            "price_model": GEMINI_API_FALLBACK_MODEL, "cost_src": cost_src,
            "free_tier": False,
        })

    g_list = atoms["gemini"]
    for e in entries:
        cred_id, short_m, loc, end_t = e["cred_id"], e["short_m"], e["loc"], e["end_t"]
        calls, req_b, resp_b = e["calls"], e["req_b"], e["resp_b"]
        in_tok, out_tok, cached_tok = e["in_tok"], e["out_tok"], e["cached_tok"]
        gross_usd, cache_sav_usd = e["gross_usd"], e["cache_sav_usd"]
        gm_id, cost_src = e["gm_id"], e["cost_src"]
        price_model = e["price_model"]
        free_tier = bool(e.get("free_tier"))
        for rec in g_list:
            if (
                rec.get("c") == cred_id
                and rec.get("m") == price_model
                and rec.get("gm") == gm_id
                and rec.get("loc") == loc
                and rec.get("sm") == short_m
                and rec.get("d") == end_t
                and bool(rec.get("free")) == free_tier
                and rec.get("src") == cost_src
            ):
                rec["i"] += int(in_tok)
                rec["o"] += int(out_tok)
                rec["calls"] += int(calls)
                rec["rb"] += int(req_b)
                rec["rsb"] += int(resp_b)
                break
        else:
            g_list.append({
                "c": cred_id,
                "m": price_model,
                "gm": gm_id,
                "loc": loc,
                "sm": short_m,
                "d": end_t,
                "i": int(in_tok),
                "o": int(out_tok),
                "calls": int(calls),
                "rb": int(req_b),
                "rsb": int(resp_b),
                "free": free_tier,
                "src": cost_src,
            })
        net_usd = gross_usd - cache_sav_usd
        tot_tok = in_tok + out_tok
        from_bytes = cost_src == "GEMINI_API_PAYLOAD_BYTES"

        c_entry = result["credentialsUsage"].setdefault(cred_id, {
            "credentialId": cred_id,
            "service": "generativelanguage.googleapis.com",
            "services": {"generativelanguage.googleapis.com"},
            "requests": calls,
            "inferenceRequests": calls,
            "vertexInferenceRequests": 0,
            "systemRequests": 0,
            "ok200": calls,
            "ok200Inference": calls,
            "errors429": 0,
            "otherErrors": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "cachedTokens": 0,
            "totalTokens": 0,
            "requestBytes": 0,
            "responseBytes": 0,
            "grossCostUsd": 0.0,
            "cacheSavingsUsd": 0.0,
            "estimatedCostUsd": 0.0,
            "costSource": cost_src,
            "methods": {short_m},
            "inferenceMethods": {short_m},
            "systemMethods": set(),
            "dailySeries": {}
        })
        if cred_id == GEMINI_API_UNATTRIBUTED_ID:
            c_entry["resolvedName"] = GEMINI_API_UNATTRIBUTED_LABEL
            c_entry["resolvedType"] = "API_KEY"

        p_day = result["dailySeries"].setdefault(end_t, empty_day_bucket())
        c_day = c_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
        if from_bytes:
            # Token counts of this day come from payload bytes, not from exact Cloud Monitoring metrics.
            c_entry["tokensEstimatedFromBytes"] = True
            c_day["tokensEstimatedFromBytes"] = True
        if free_tier:
            c_entry["freeTier"] = True
            c_day["freeTier"] = True
        for bucket in (p_day, c_day):
            bucket["inputTokens"] += in_tok
            bucket["outputTokens"] += out_tok
            bucket["cachedTokens"] += cached_tok
            bucket["tokens"] += tot_tok
            bucket["geminiCostUsd"] += net_usd
            bucket["costUsd"] += net_usd

        c_entry["inputTokens"] += in_tok
        c_entry["outputTokens"] += out_tok
        c_entry["cachedTokens"] += cached_tok
        c_entry["totalTokens"] += tot_tok
        c_entry["requestBytes"] += req_b
        c_entry["responseBytes"] += resp_b
        c_entry["grossCostUsd"] += gross_usd
        c_entry["cacheSavingsUsd"] += cache_sav_usd
        c_entry["estimatedCostUsd"] += net_usd
        c_entry["costSource"] = cost_src

        result["inputTokens"] += in_tok
        result["outputTokens"] += out_tok
        result["cachedTokens"] += cached_tok
        result["totalTokens"] += tot_tok
        result["geminiRequestBytes"] += req_b
        result["geminiResponseBytes"] += resp_b
        result["geminiGrossCostUsd"] += gross_usd
        result["geminiCacheSavingsUsd"] += cache_sav_usd
        result["geminiCostUsd"] += net_usd
        result["estimatedCostUsd"] += net_usd

        gm_entry = result["models"].setdefault(gm_id, _new_model_usage_entry(gm_id, service="generativelanguage.googleapis.com"))
        gm_entry["locations"].add(f"{loc} (AI Studio)" if loc and loc != "global" else "global (AI Studio)")
        gm_entry["invocations"] += calls
        gm_entry["inputTokens"] += in_tok
        gm_entry["outputTokens"] += out_tok
        gm_entry["cachedTokens"] += cached_tok
        gm_entry["totalTokens"] += tot_tok
        gm_entry["grossCostUsd"] = gm_entry.get("grossCostUsd", 0.0) + gross_usd
        gm_entry["cacheSavingsUsd"] = gm_entry.get("cacheSavingsUsd", 0.0) + cache_sav_usd
        gm_entry["costUsd"] += net_usd
        gm_day = gm_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
        if from_bytes:
            gm_entry["tokensEstimatedFromBytes"] = True
            gm_day["tokensEstimatedFromBytes"] = True
        if free_tier:
            gm_entry["freeTier"] = True
            gm_day["freeTier"] = True
        gm_day["requests"] += calls
        gm_day["inferenceRequests"] += calls
        gm_day["inputTokens"] += in_tok
        gm_day["outputTokens"] += out_tok
        gm_day["cachedTokens"] += cached_tok
        gm_day["tokens"] += tot_tok
        gm_day["geminiCostUsd"] += net_usd
        gm_day["costUsd"] += net_usd


def _apply_vertex_token_share_to_credential(c: dict, c_day: dict, v_day: dict, share: float):
    add_in = int(round(v_day["inputTokens"] * share))
    add_out = int(round((v_day["outputTokens"] + v_day["thinkingTokens"]) * share))
    add_cache = int(round(v_day["cachedTokens"] * share))
    add_tot = int(round(v_day["totalTokens"] * share))
    add_gross = v_day.get("grossCostUsd", v_day["costUsd"]) * share
    add_sav = v_day.get("cacheSavingsUsd", 0.0) * share
    add_cost = v_day["costUsd"] * share

    c_day["inputTokens"] += add_in
    c_day["outputTokens"] += add_out
    c_day["cachedTokens"] += add_cache
    c_day["tokens"] += add_tot
    c_day["vertexCostUsd"] += add_cost
    c_day["costUsd"] += add_cost

    c["inputTokens"] += add_in
    c["outputTokens"] += add_out
    c["cachedTokens"] += add_cache
    c["totalTokens"] += add_tot
    c["grossCostUsd"] = c.get("grossCostUsd", 0.0) + add_gross
    c["cacheSavingsUsd"] = c.get("cacheSavingsUsd", 0.0) + add_sav
    c["vertexCostUsd"] = c.get("vertexCostUsd", 0.0) + add_cost
    c["estimatedCostUsd"] += add_cost
    c["costSource"] = "VERTEX_TOKENS" if c["costSource"] in ("NONE", "VERTEX_TOKENS") else "VERTEX_AND_MANAGED_AI"


def vertex_token_price(
    model_id: str, location: str, tok_type: str, val: int, rates: dict = None
) -> tuple[float, float, int]:
    """(gross USD, credit savings USD, cached tokens) for a Vertex AI token_count sample."""
    if rates is None:
        rates = get_model_rates(model_id, location=location)
    cache_ratio = max(0.0, min(0.98, float(rates.get("implicitCacheHitRatioPct", 0.0)) / 100.0))
    credit_disc_ratio = max(0.0, min(0.95, float(rates.get("billingCreditDiscountPct", 0.0)) / 100.0))
    tt = (tok_type or "input").lower()
    if "cache" in tt:
        gross = (val / 1_000_000.0) * rates["cache_read_input"]
        cached_tok = int(val)
    elif "output" in tt or "candidate" in tt:
        gross = (val / 1_000_000.0) * rates["output"]
        cached_tok = 0
    elif "think" in tt:
        gross = (val / 1_000_000.0) * rates["thinking"]
        cached_tok = 0
    else:
        cached_tok = int(round(val * cache_ratio))
        uncached_tok = max(0, int(val) - cached_tok)
        gross = (
            ((uncached_tok / 1_000_000.0) * rates["input"]) +
            ((cached_tok / 1_000_000.0) * rates["cache_read_input"])
        )
    savings = gross * credit_disc_ratio
    return (gross, savings, cached_tok)


def _process_vertex_tokens_and_invocations(
    mon_results: dict, pid: str, token: str, start_iso: str, end_iso: str,
    can_read_monitoring: bool, su_status: int, active_locations_seen: set, result: dict
):
    atoms = _ensure_project_pricing_atoms(result)
    vertex_daily_tokens = {}
    if can_read_monitoring and (result["vertexEnabled"] or su_status != 200):
        tok_filter = 'metric.type="aiplatform.googleapis.com/publisher/online_serving/token_count"'
        inv_filter = 'metric.type="aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"'
        tok_series = mon_results.get("vertex_tok") if "vertex_tok" in mon_results else fetch_monitoring_timeseries(
            pid, token, tok_filter, start_iso, end_iso,
            group_by_fields=["resource.label.model_user_id", "resource.label.location", "metric.label.type"]
        )

        has_ew3 = ("europe-west3" in active_locations_seen)
        vertex_atoms_agg: dict[tuple[str, str, str, str, str], int] = {}
        for ts in tok_series:
            r_labels = ts.get("resource", {}).get("labels", {})
            m_labels = ts.get("metric", {}).get("labels", {})
            model_id = r_labels.get("model_user_id", "unknown-model")
            location = r_labels.get("location", "global")
            tok_type = m_labels.get("type", "input").lower()

            if location:
                active_locations_seen.add(location)

            loc_display = "eu (europe-west3 Regional)" if (location == "eu" and has_ew3) else location
            rates = get_model_rates(model_id, location=location)
            pts_sum = 0

            m_entry = result["models"].setdefault(model_id, _new_model_usage_entry(model_id))
            m_entry["locations"].add(loc_display)
            if rates.get("isEstimated"):
                m_entry["isEstimated"] = True

            for pt in ts.get("points", []):
                val = int(pt.get("value", {}).get("int64Value", 0) or 0)
                if val <= 0:
                    continue
                pts_sum += val
                end_t = pt.get("interval", {}).get("endTime", "")[:10]
                v_atom_k = (model_id, location, loc_display, tok_type, end_t)
                vertex_atoms_agg[v_atom_k] = vertex_atoms_agg.get(v_atom_k, 0) + val
                pt_gross, pt_sav, pt_cache_tok = vertex_token_price(
                    model_id, location, tok_type, val, rates=rates
                )
                pt_cost = pt_gross - pt_sav

                if end_t:
                    p_day = result["dailySeries"].setdefault(end_t, empty_day_bucket())
                    m_day = m_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
                    v_day = vertex_daily_tokens.setdefault(end_t, {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "cachedTokens": 0,
                        "thinkingTokens": 0,
                        "totalTokens": 0,
                        "grossCostUsd": 0.0,
                        "cacheSavingsUsd": 0.0,
                        "costUsd": 0.0
                    })

                    p_day["tokens"] += val
                    p_day["vertexCostUsd"] += pt_cost
                    p_day["costUsd"] += pt_cost
                    m_day["tokens"] += val
                    m_day["costUsd"] += pt_cost

                    v_day["totalTokens"] += val
                    v_day["grossCostUsd"] += pt_gross
                    v_day["cacheSavingsUsd"] += pt_sav
                    v_day["costUsd"] += pt_cost

                    for b_tok in (p_day, m_day, v_day):
                        if "cache" in tok_type:
                            b_tok["cachedTokens"] += val
                        elif "output" in tok_type or "candidate" in tok_type:
                            b_tok["outputTokens"] += val
                        elif "think" in tok_type:
                            b_tok["thinkingTokens"] += val
                        else:
                            b_tok["inputTokens"] += val
                            b_tok["cachedTokens"] += pt_cache_tok

            if pts_sum <= 0:
                continue

            gross_piece, sav_piece, est_cached_sum = vertex_token_price(
                model_id, location, tok_type, pts_sum, rates=rates
            )
            cost_piece = gross_piece - sav_piece

            if "cache" in tok_type:
                m_entry["cachedTokens"] += est_cached_sum
                result["cachedTokens"] += est_cached_sum
            elif "output" in tok_type or "candidate" in tok_type:
                m_entry["outputTokens"] += pts_sum
                result["outputTokens"] += pts_sum
            elif "think" in tok_type:
                m_entry["thinkingTokens"] += pts_sum
                result["thinkingTokens"] += pts_sum
            else:
                m_entry["inputTokens"] += pts_sum
                m_entry["cachedTokens"] += est_cached_sum
                result["inputTokens"] += pts_sum
                result["cachedTokens"] += est_cached_sum

            m_entry["totalTokens"] += pts_sum
            m_entry["grossCostUsd"] = m_entry.get("grossCostUsd", 0.0) + gross_piece
            m_entry["cacheSavingsUsd"] = m_entry.get("cacheSavingsUsd", 0.0) + sav_piece
            m_entry["costUsd"] += cost_piece
            result["totalTokens"] += pts_sum
            result["vertexGrossCostUsd"] += gross_piece
            result["vertexCacheSavingsUsd"] += sav_piece
            result["vertexCostUsd"] += cost_piece
            result["estimatedCostUsd"] += cost_piece

        v_list = atoms["vertex"]
        for (v_m, v_loc, v_ld, v_t, v_d), val_sum in vertex_atoms_agg.items():
            for rec in v_list:
                if (
                    rec.get("m") == v_m
                    and rec.get("loc") == v_loc
                    and rec.get("ld") == v_ld
                    and rec.get("t") == v_t
                    and rec.get("d") == v_d
                ):
                    rec["v"] += int(val_sum)
                    break
            else:
                v_list.append({
                    "m": v_m,
                    "loc": v_loc,
                    "ld": v_ld,
                    "t": v_t,
                    "d": v_d,
                    "v": int(val_sum),
                })

        inv_series = mon_results.get("vertex_inv") if "vertex_inv" in mon_results else fetch_monitoring_timeseries(
            pid, token, inv_filter, start_iso, end_iso,
            group_by_fields=["resource.label.model_user_id", "resource.label.location"]
        )
        for ts in inv_series:
            r_labels = ts.get("resource", {}).get("labels", {})
            model_id = r_labels.get("model_user_id", "unknown-model")
            location = r_labels.get("location", "global")
            if location:
                active_locations_seen.add(location)
            loc_display = "eu (europe-west3 Regional)" if (location == "eu" and ("europe-west3" in active_locations_seen)) else location
            pts_sum = 0
            m_entry = result["models"].setdefault(model_id, _new_model_usage_entry(model_id))
            m_entry["locations"].add(loc_display)
            for pt in ts.get("points", []):
                val = int(pt.get("value", {}).get("int64Value", 0) or 0)
                if val <= 0:
                    continue
                pts_sum += val
                end_t = pt.get("interval", {}).get("endTime", "")[:10]
                if end_t:
                    m_day = m_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
                    m_day["requests"] += val
                    m_day["inferenceRequests"] += val
            if pts_sum > 0:
                m_entry["invocations"] += pts_sum

    has_explicit_vertex_inf = True
    vertex_inf_creds = [
        c for c in result["credentialsUsage"].values()
        if c.get("vertexInferenceRequests", 0) > 0
    ]
    if not vertex_inf_creds:
        has_explicit_vertex_inf = False
        vertex_inf_creds = [
            c for c in result["credentialsUsage"].values()
            if "aiplatform.googleapis.com" in c.get("services", set()) and c.get("inferenceRequests", 0) > 0
        ]
    req_field = "vertexInferenceRequests" if has_explicit_vertex_inf else "inferenceRequests"
    total_proj_vertex_inf = sum(
        c.get(req_field, 0)
        for c in vertex_inf_creds
    )

    for day_str, v_day in vertex_daily_tokens.items():
        if v_day["totalTokens"] <= 0 and v_day["costUsd"] <= 0:
            continue
        day_active = [
            c for c in vertex_inf_creds
            if c["dailySeries"].get(day_str, {}).get(req_field, 0) > 0
        ]
        if day_active:
            day_inf_sum = sum(
                c["dailySeries"][day_str].get(req_field, 0)
                for c in day_active
            )
            for c in day_active:
                c_day = c["dailySeries"][day_str]
                c_w = c_day.get(req_field, 0)
                _apply_vertex_token_share_to_credential(c, c_day, v_day, c_w / float(day_inf_sum))
        elif vertex_inf_creds and total_proj_vertex_inf > 0:
            for c in vertex_inf_creds:
                c_day = c["dailySeries"].setdefault(day_str, empty_day_bucket())
                c_w = c.get(req_field, 0)
                _apply_vertex_token_share_to_credential(c, c_day, v_day, c_w / float(total_proj_vertex_inf))


def dialogflow_token_price(base_model: str, val: int) -> tuple[float, float, int, int]:
    """(gross USD, managed savings USD, input tokens, output tokens) for Dialogflow CX LLM tokens."""
    bm = base_model or "gemini-2.5-flash"
    rates = get_model_rates(bm)
    blended_rate_per_1m = (0.82 * rates["input"]) + (0.18 * rates["output"])
    bs_df = get_billing_settings()
    sav_ratio = max(0.0, min(1.0, float(bs_df.get("managedServiceSavingsPct", 0.0) or 0.0) / 100.0))
    in_tok = int(round(val * 0.82))
    out_tok = int(val) - in_tok
    gross = (val / 1_000_000.0) * blended_rate_per_1m
    savings = gross * sav_ratio
    return (gross, savings, in_tok, out_tok)


def _process_dialogflow_llm_tokens(
    mon_results: dict, pid: str, token: str, start_iso: str, end_iso: str,
    can_read_monitoring: bool, enabled_services_set: set, su_status: int,
    active_locations_seen: set, features_map: dict, result: dict
):
    atoms = _ensure_project_pricing_atoms(result)
    if not can_read_monitoring or not ("dialogflow.googleapis.com" in enabled_services_set or "ces.googleapis.com" in enabled_services_set or su_status != 200):
        return
    df_tok_metrics = [
        (
            "df_multi",
            'metric.type="dialogflow.googleapis.com/quota/ConversationalAgentMultiRegionLLMTokenConsumption/usage"',
            ["metric.label.base_model", "resource.label.multi_region"],
            "multi_region"
        ),
        (
            "df_loc",
            'metric.type="dialogflow.googleapis.com/quota/ConversationalAgentLLMTokenConsumption/usage"',
            ["metric.label.base_model", "resource.label.location"],
            "location"
        )
    ]
    df_daily_tokens = {}
    df_atoms_agg: dict[tuple[str, str, str, str], int] = {}

    for m_key_df, m_filter, grp_fields, loc_key in df_tok_metrics:
        df_series = mon_results.get(m_key_df) if m_key_df in mon_results else fetch_monitoring_timeseries(
            pid, token, m_filter, start_iso, end_iso, group_by_fields=grp_fields
        )
        for ts in df_series:
            r_labels = ts.get("resource", {}).get("labels", {})
            m_labels = ts.get("metric", {}).get("labels", {})
            base_model = m_labels.get("base_model") or "gemini-2.5-flash"
            loc = r_labels.get(loc_key) or "eu"
            if loc:
                active_locations_seen.add(loc)

            df_model_label = f"{base_model} (Dialogflow CX Playbook LLM)"

            m_entry = result["models"].setdefault(
                df_model_label, _new_model_usage_entry(df_model_label, service="dialogflow.googleapis.com")
            )
            m_entry["locations"].add(loc)

            pts_sum = 0
            for pt in ts.get("points", []):
                val = int(pt.get("value", {}).get("int64Value", 0) or 0)
                if val <= 0:
                    continue
                pts_sum += val
                end_t = pt.get("interval", {}).get("endTime", "")[:10]
                df_atom_k = (m_key_df, base_model, loc, end_t)
                df_atoms_agg[df_atom_k] = df_atoms_agg.get(df_atom_k, 0) + val
                pt_gross, pt_sav, in_tok, out_tok = dialogflow_token_price(base_model, val)
                pt_cost = pt_gross - pt_sav
                pt_cache = 0  # per-call billing: no cached-token share
                est_calls = max(1, int(round(val / 3500.0)))

                if end_t:
                    p_day = result["dailySeries"].setdefault(end_t, empty_day_bucket())
                    m_day = m_entry["dailySeries"].setdefault(end_t, empty_day_bucket())
                    d_day = df_daily_tokens.setdefault(end_t, {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "totalTokens": 0,
                        "cachedTokens": 0,
                        "grossCostUsd": 0.0,
                        "costUsd": 0.0
                    })

                    p_day["inputTokens"] += in_tok
                    p_day["outputTokens"] += out_tok
                    p_day["cachedTokens"] += pt_cache
                    p_day["tokens"] += val
                    p_day["otherAiCostUsd"] += pt_cost
                    p_day["costUsd"] += pt_cost

                    m_day["requests"] += est_calls
                    m_day["inferenceRequests"] += est_calls
                    m_day["inputTokens"] += in_tok
                    m_day["outputTokens"] += out_tok
                    m_day["cachedTokens"] += pt_cache
                    m_day["tokens"] += val
                    m_day["otherAiCostUsd"] += pt_cost
                    m_day["costUsd"] += pt_cost

                    d_day["inputTokens"] += in_tok
                    d_day["outputTokens"] += out_tok
                    d_day["totalTokens"] += val
                    d_day["cachedTokens"] += pt_cache
                    d_day["grossCostUsd"] += pt_gross
                    d_day["costUsd"] += pt_cost

            if pts_sum <= 0:
                continue

            tot_gross, tot_sav, tot_in, tot_out = dialogflow_token_price(base_model, pts_sum)
            tot_cost = tot_gross - tot_sav
            tot_cache = 0
            tot_est_calls = max(1, int(round(pts_sum / 3500.0)))

            m_entry["invocations"] += tot_est_calls
            m_entry["inputTokens"] += tot_in
            m_entry["outputTokens"] += tot_out
            m_entry["cachedTokens"] += tot_cache
            m_entry["totalTokens"] += pts_sum
            m_entry["grossCostUsd"] = m_entry.get("grossCostUsd", 0.0) + tot_gross
            m_entry["cacheSavingsUsd"] = m_entry.get("cacheSavingsUsd", 0.0) + tot_sav
            m_entry["costUsd"] += tot_cost

            result["inputTokens"] += tot_in
            result["outputTokens"] += tot_out
            result["cachedTokens"] += tot_cache
            result["totalTokens"] += pts_sum
            result["otherAiGrossCostUsd"] += tot_gross
            result["otherAiCacheSavingsUsd"] += tot_sav
            result["otherAiCostUsd"] += tot_cost
            result["grossCostUsd"] = result.get("grossCostUsd", 0.0) + tot_gross
            result["estimatedCostUsd"] += tot_cost

            df_llm_feat = features_map.setdefault("dialogflow_playbook_llm", {
                "id": "dialogflow_playbook_llm",
                "name": "Dialogflow CX Playbooks & Generators (LLM Tokens)",
                "service": "dialogflow.googleapis.com",
                "category": "Conversational AI",
                "icon": "🧠",
                "description": f"LLM token usage ({base_model}) in Dialogflow CX Playbooks and Generators",
                "status": "ACTIVE_TRAFFIC",
                "requests": 0,
                "inferenceRequests": 0,
                "methods": set(),
                "locations": set()
            })
            df_llm_feat["status"] = "ACTIVE_TRAFFIC"
            df_llm_feat["requests"] += tot_est_calls
            df_llm_feat["inferenceRequests"] += tot_est_calls
            df_llm_feat["methods"].add(f"LLM:{base_model}")
            df_llm_feat["locations"].add(loc)

    if not df_daily_tokens and not df_atoms_agg:
        return
    df_creds = [
        c for c in result["credentialsUsage"].values()
        if "dialogflow.googleapis.com" in c.get("services", set()) and c.get("inferenceRequests", 0) > 0
    ] or [
        c for c in result["credentialsUsage"].values()
        if "dialogflow.googleapis.com" in c.get("services", set())
    ]
    if not df_creds:
        synth_id = "dialogflow-cx:playbook-llm-runtime"
        synth_c = result["credentialsUsage"].setdefault(synth_id, {
            "credentialId": synth_id,
            "resolvedName": "Dialogflow CX Playbook / Console Simulator (LLM Runtime)",
            "resolvedType": "OAUTH_CLIENT",
            "service": "dialogflow.googleapis.com",
            "services": {"dialogflow.googleapis.com"},
            "requests": 0,
            "inferenceRequests": 0,
            "vertexInferenceRequests": 0,
            "systemRequests": 0,
            "ok200": 0,
            "ok200Inference": 0,
            "errors429": 0,
            "otherErrors": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "cachedTokens": 0,
            "totalTokens": 0,
            "estimatedCostUsd": 0.0,
            "costSource": "DIALOGFLOW_LLM_TOKENS",
            "methods": {"PlaybookLLM"},
            "inferenceMethods": {"PlaybookLLM"},
            "systemMethods": set(),
            "dailySeries": {}
        })
        df_creds = [synth_c]

    total_df_reqs = sum(max(1, c.get("inferenceRequests", 0) or c.get("requests", 0)) for c in df_creds)
    df_list = atoms["dialogflow"]
    for (m_key_df, base_model, loc, end_t), val_sum in df_atoms_agg.items():
        for c in df_creds:
            cred_id = str(c.get("credentialId") or "dialogflow-cx:playbook-llm-runtime")
            weight = max(1, c.get("inferenceRequests", 0) or c.get("requests", 0)) / float(total_df_reqs)
            for rec in df_list:
                if (
                    rec.get("c") == cred_id
                    and rec.get("m") == base_model
                    and rec.get("loc") == loc
                    and rec.get("mk") == m_key_df
                    and rec.get("d") == end_t
                ):
                    rec["v"] += int(val_sum)
                    rec["w"] = float(weight)
                    break
            else:
                df_list.append({
                    "c": cred_id,
                    "m": base_model,
                    "loc": loc,
                    "mk": m_key_df,
                    "d": end_t,
                    "v": int(val_sum),
                    "w": float(weight),
                })

    for day_str, d_day in df_daily_tokens.items():
        for c in df_creds:
            weight = max(1, c.get("inferenceRequests", 0) or c.get("requests", 0)) / float(total_df_reqs)
            add_in = int(round(d_day["inputTokens"] * weight))
            add_out = int(round(d_day["outputTokens"] * weight))
            add_tot = int(round(d_day["totalTokens"] * weight))
            add_cache = int(round(d_day["cachedTokens"] * weight))
            add_gross = d_day["grossCostUsd"] * weight
            add_cost = d_day["costUsd"] * weight
            add_sav = add_gross - add_cost

            c_day = c["dailySeries"].setdefault(day_str, empty_day_bucket())
            c_day["inputTokens"] += add_in
            c_day["outputTokens"] += add_out
            c_day["cachedTokens"] += add_cache
            c_day["tokens"] += add_tot
            c_day["otherAiCostUsd"] += add_cost
            c_day["costUsd"] += add_cost

            c["inputTokens"] += add_in
            c["outputTokens"] += add_out
            c["cachedTokens"] += add_cache
            c["totalTokens"] += add_tot
            c["grossCostUsd"] = c.get("grossCostUsd", 0.0) + add_gross
            c["cacheSavingsUsd"] = c.get("cacheSavingsUsd", 0.0) + add_sav
            c["estimatedCostUsd"] += add_cost
            c["costSource"] = "DIALOGFLOW_CX_AND_LLM"


def _build_apikey_telemetry_record(
    uid: str, name_path: str, display_name: str, owner_email: str,
    status_str: str, create_time: str, targets: list, is_aistudio_key: bool,
    svcs_sorted: list, cred_usage: dict, today_str_proj: str, yesterday_str_proj: str
) -> dict:
    inf_reqs = cred_usage.get("inferenceRequests", 0)
    ok200_inf = cred_usage.get("ok200Inference", 0)
    est_cost = round(cred_usage.get("estimatedCostUsd", 0.0), 4)
    gross_cost = round(cred_usage.get("grossCostUsd", est_cost), 4)
    cache_sav = round(cred_usage.get("cacheSavingsUsd", 0.0), 4)
    d_ser = cred_usage.get("dailySeries") or {}
    t_b = d_ser.get(today_str_proj) or {}
    y_b = d_ser.get(yesterday_str_proj) or {}
    return {
        "uid": uid,
        "name": name_path,
        "displayName": display_name,
        "ownerEmail": owner_email,
        "status": status_str,
        "createTime": create_time,
        "restrictions": targets,
        "apiTargets": targets,
        "isAiStudioKey": is_aistudio_key,
        "services": svcs_sorted,
        "requests": cred_usage.get("requests", 0),
        "inferenceRequests": inf_reqs,
        "ok200Inference": ok200_inf,
        "failedInference": max(0, inf_reqs - ok200_inf),
        "systemRequests": cred_usage.get("systemRequests", 0),
        "ok200": cred_usage.get("ok200", 0),
        "errors429": cred_usage.get("errors429", 0),
        "otherErrors": cred_usage.get("otherErrors", 0),
        "inputTokens": cred_usage.get("inputTokens", 0),
        "outputTokens": cred_usage.get("outputTokens", 0),
        "cachedTokens": cred_usage.get("cachedTokens", 0),
        "totalTokens": cred_usage.get("totalTokens", 0),
        "requestBytes": cred_usage.get("requestBytes", 0),
        "responseBytes": cred_usage.get("responseBytes", 0),
        "grossCostUsd": gross_cost,
        "cacheSavingsUsd": cache_sav,
        "estimatedCostUsd": est_cost,
        "todayDate": today_str_proj,
        "todayCalls": int(t_b.get("inferenceRequests", 0) or t_b.get("requests", 0) or 0),
        "todayTokens": int(t_b.get("tokens", 0) or 0),
        "todayCostUsd": round(float(t_b.get("costUsd", 0.0) or 0.0), 4),
        "yesterdayDate": yesterday_str_proj,
        "yesterdayCalls": int(y_b.get("inferenceRequests", 0) or y_b.get("requests", 0) or 0),
        "yesterdayTokens": int(y_b.get("tokens", 0) or 0),
        "yesterdayCostUsd": round(float(y_b.get("costUsd", 0.0) or 0.0), 4),
        "costSource": cred_usage.get("costSource", "NONE"),
        "methods": sorted(list(cred_usage.get("methods", []))),
        "inferenceMethods": sorted(list(cred_usage.get("inferenceMethods", [])))
    }


def _fetch_apikeys_and_owners(
    pid: str, token: str, granted_perms: set, fallback_owners: dict, result: dict
) -> tuple:
    keys_list = []
    k_st = 403
    if "serviceusage.apiKeys.list" in granted_perms:
        k_page_tok = None
        for _ in range(5):
            keys_url = f"https://apikeys.googleapis.com/v2/projects/{urllib.parse.quote(pid)}/locations/global/keys?pageSize=300"
            if k_page_tok:
                keys_url += f"&pageToken={urllib.parse.quote(k_page_tok)}"
            st_k, d_k = gcp_api_get(keys_url, token, timeout=8, user_project=None)
            if st_k == 200:
                k_st = 200
                keys_list.extend(d_k.get("keys", []))
                k_page_tok = d_k.get("nextPageToken")
                if not k_page_tok:
                    break
            else:
                if k_st != 200:
                    k_st = st_k
                break
    has_any_k = (k_st == 200 and len(keys_list) > 0) or any(
        c_id.startswith("apikey:") for c_id in result["credentialsUsage"].keys()
    )
    owners_map = (
        fetch_project_apikey_owners(pid, token, keys_list=keys_list, fallback_owners=fallback_owners)
        if (has_any_k and "logging.logEntries.list" in granted_perms)
        else dict(fallback_owners)
    )
    return k_st, keys_list, owners_map


def _parallel_fetch_project_io(
    pid: str, token: str, start_dt: datetime, now: datetime, days: int,
    granted_perms: set, enabled_services_set: set, active_locations_seen: set,
    ma_metrics: dict, fallback_owners: dict, result: dict
) -> tuple:
    can_read_ma = (
        "modelarmor.floorSettings.get" in granted_perms or
        "modelarmor.templates.list" in granted_perms
    )
    can_read_any_ai_res = any(
        perm in granted_perms for perm in (
            "aiplatform.endpoints.list",
            "aiplatform.reasoningEngines.list",
            "dialogflow.agents.list",
            "discoveryengine.engines.list"
        )
    )
    eff_enabled_services = set(enabled_services_set)
    if result["vertexEnabled"]:
        eff_enabled_services.add("aiplatform.googleapis.com")
    snap_active_locs = set(active_locations_seen)

    with ThreadPoolExecutor(max_workers=5) as io_pool:
        fut_keys = io_pool.submit(_fetch_apikeys_and_owners, pid, token, granted_perms, fallback_owners, result)
        fut_sa = io_pool.submit(
            gcp_api_get,
            f"https://iam.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/serviceAccounts",
            token, 8, None
        ) if "iam.serviceAccounts.list" in granted_perms else None
        fut_ma = io_pool.submit(
            inspect_model_armor, pid, token, True, ma_metrics, can_read_ma
        ) if result["modelArmorEnabled"] else None
        fut_vres = io_pool.submit(
            discover_active_vertex_resources, pid, token, eff_enabled_services, snap_active_locs
        ) if can_read_any_ai_res else None
        should_prefetch_ulogs = "logging.logEntries.list" in granted_perms and (
            result["totalRequests"] > 0 or result["totalTokens"] > 0 or result["aiActive"] or result.get("isAiStudioProject")
        )
        fut_ulogs = io_pool.submit(
            prefetch_project_user_activity_entries, pid, token, start_dt, now, days
        ) if should_prefetch_ulogs else None

        k_status, all_proj_keys, apikey_owners = fut_keys.result()
        sa_status, sa_data = fut_sa.result() if fut_sa else (403, {})
        prefetched_ma = fut_ma.result() if fut_ma else None
        prefetched_vres = fut_vres.result() if fut_vres else []
        prefetched_user_entries = fut_ulogs.result() if fut_ulogs else None

    return k_status, all_proj_keys, apikey_owners, sa_status, sa_data, prefetched_ma, prefetched_vres, prefetched_user_entries


def _reconcile_apikeys_and_service_accounts(
    pid: str, now: datetime, k_status: int, all_proj_keys: list, apikey_owners: dict,
    sa_status: int, sa_data: dict, result: dict
):
    seen_apikey_creds = set()
    today_str_proj = now.strftime("%Y-%m-%d")
    yesterday_str_proj = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    if k_status == 200:
        for k in all_proj_keys:
            uid = k.get("uid", "")
            name_path = k.get("name", "")
            display_name = k.get("displayName") or name_path.split("/")[-1]
            targets = [t.get("service", "") for t in k.get("restrictions", {}).get("apiTargets", [])]
            cred_lookup_1 = f"apikey:{uid}"
            seen_apikey_creds.add(cred_lookup_1)
            cred_usage = result["credentialsUsage"].get(cred_lookup_1, {})
            owner_info = apikey_owners.get(uid, {})
            owner_email = owner_info.get("ownerEmail")
            svcs_sorted = sorted(list(cred_usage.get("services", set(targets))))
            is_aistudio_key = (
                "generativelanguage.googleapis.com" in svcs_sorted or
                "generativelanguage.googleapis.com" in targets or
                any(x in (display_name or "").lower() for x in ("aistudio", "generative language", "gemini"))
            )
            result["apiKeys"].append(_build_apikey_telemetry_record(
                uid, name_path, display_name, owner_email, "ACTIVE", k.get("createTime"),
                targets, is_aistudio_key, svcs_sorted, cred_usage, today_str_proj, yesterday_str_proj
            ))
            if cred_lookup_1 in result["credentialsUsage"]:
                result["credentialsUsage"][cred_lookup_1]["resolvedName"] = f"API Key: {display_name}"
                result["credentialsUsage"][cred_lookup_1]["resolvedType"] = "API_KEY"
                result["credentialsUsage"][cred_lookup_1]["ownerEmail"] = owner_email
            else:
                result["credentialsUsage"][cred_lookup_1] = {
                    "credentialId": cred_lookup_1,
                    "resolvedName": f"API Key: {display_name}",
                    "resolvedType": "API_KEY",
                    "ownerEmail": owner_email,
                    "service": ", ".join(targets) if targets else "All APIs",
                    "services": set(targets),
                    "requests": 0,
                    "inferenceRequests": 0,
                    "vertexInferenceRequests": 0,
                    "systemRequests": 0,
                    "ok200": 0,
                    "ok200Inference": 0,
                    "errors429": 0,
                    "otherErrors": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cachedTokens": 0,
                    "totalTokens": 0,
                    "requestBytes": 0,
                    "responseBytes": 0,
                    "grossCostUsd": 0.0,
                    "cacheSavingsUsd": 0.0,
                    "estimatedCostUsd": 0.0,
                    "costSource": "NONE",
                    "methods": set(),
                    "inferenceMethods": set(),
                    "systemMethods": set(),
                    "dailySeries": {}
                }

    for c_id, cred_usage in list(result["credentialsUsage"].items()):
        if c_id.startswith("apikey:") and c_id not in seen_apikey_creds:
            uid = c_id.split(":", 1)[1]
            svcs_list = sorted(list(cred_usage.get("services", set())))
            owner_info = apikey_owners.get(uid, {})
            owner_email = owner_info.get("ownerEmail")
            disp_hist = owner_info.get("displayName")
            is_first_party_console = uid.isdigit() and len(uid) <= 4
            if is_first_party_console:
                disp = f"Console GCP / Colab Enterprise UI (First-Party Key #{uid})"
                k_status_str = "GCP_CONSOLE_FIRST_PARTY"
                cred_usage["resolvedName"] = disp
                cred_usage["resolvedType"] = "GCP_CONSOLE_UI"
            else:
                disp = f"{disp_hist} (Deleted)" if disp_hist else f"Deleted / External API Key ({uid[:8]}...)"
                k_status_str = "DELETED_OR_EXTERNAL"
                cred_usage["resolvedName"] = f"API Key: {disp}"
                cred_usage["resolvedType"] = "API_KEY"
            cred_usage["ownerEmail"] = owner_email
            is_aistudio_key = (not is_first_party_console) and (
                "generativelanguage.googleapis.com" in svcs_list or
                any(x in (disp or "").lower() for x in ("aistudio", "generative language", "gemini"))
            )
            result["apiKeys"].append(_build_apikey_telemetry_record(
                uid, f"projects/{pid}/locations/global/keys/{uid}", disp, owner_email,
                k_status_str, owner_info.get("createdAt"), svcs_list, is_aistudio_key,
                svcs_list, cred_usage, today_str_proj, yesterday_str_proj
            ))

    result["apiKeys"].sort(key=lambda x: (x.get("estimatedCostUsd", 0.0), x.get("requests", 0), x.get("status") == "ACTIVE"), reverse=True)

    if sa_status == 200:
        for sa in sa_data.get("accounts", []):
            unique_id = sa.get("uniqueId", "")
            email = sa.get("email", "")
            display_name = sa.get("displayName") or email.split("@")[0]
            disabled = bool(sa.get("disabled", False))
            cred_lookup = f"serviceaccount:{unique_id}"
            cred_usage = result["credentialsUsage"].get(cred_lookup, {})
            result["serviceAccounts"].append({
                "uniqueId": unique_id,
                "email": email,
                "displayName": display_name,
                "disabled": disabled,
                "requests": cred_usage.get("requests", 0),
                "inferenceRequests": cred_usage.get("inferenceRequests", 0),
                "systemRequests": cred_usage.get("systemRequests", 0),
                "ok200": cred_usage.get("ok200", 0),
                "errors429": cred_usage.get("errors429", 0),
                "totalTokens": cred_usage.get("totalTokens", 0),
                "estimatedCostUsd": round(cred_usage.get("estimatedCostUsd", 0.0), 4),
                "methods": sorted(list(cred_usage.get("methods", [])))
            })
            if cred_lookup in result["credentialsUsage"]:
                result["credentialsUsage"][cred_lookup]["resolvedName"] = f"SA: {email}"
                result["credentialsUsage"][cred_lookup]["resolvedType"] = "SERVICE_ACCOUNT"


def _register_deployed_resources_and_model_armor(
    prefetched_ma: dict, prefetched_vres: list, features_map: dict, result: dict
):
    if result["modelArmorEnabled"] and prefetched_ma is not None:
        result["modelArmor"] = prefetched_ma
        ma_feat = features_map.setdefault("svc_modelarmor", {
            "id": "svc_modelarmor",
            "name": "Google Cloud Model Armor",
            "service": "modelarmor.googleapis.com",
            "category": "AI_SECURITY",
            "icon": "🛡️",
            "description": "Prompt Injection, Jailbreak, RAI Filter, DLP/SDP and Malicious URI protection",
            "status": result["modelArmor"]["status"],
            "requests": result["modelArmor"]["totalRequests"],
            "inferenceRequests": result["modelArmor"]["sanitizeRequests"],
            "methods": set(result["modelArmor"]["methodsCalled"]),
            "locations": set(result["modelArmor"]["activeLocations"] or ["global"])
        })
        ma_feat["status"] = result["modelArmor"]["status"]

    result["deployedAiResources"] = prefetched_vres
    res_feature_specs = {
        "REASONING_ENGINE": ("vertex_agent_engine", "Vertex AI Agent Engine (Reasoning Engines / ADK)", "aiplatform.googleapis.com", "Vertex AI Agents", "🤖", "AI Agents deployed on Vertex AI Reasoning Engine", False),
        "VERTEX_ENDPOINT": ("vertex_endpoints", "Vertex AI Online Endpoints (Model Garden / Custom)", "aiplatform.googleapis.com", "Vertex AI Serving", "🔌", "Prediction endpoints registered on Vertex AI", False),
        "DIALOGFLOW_CX_AGENT": ("svc_dialogflow", "Dialogflow CX / Conversational Agents", "dialogflow.googleapis.com", "CONVERSATIONAL_AI", "💬", "Deployed conversational agents, generative Playbooks and Voicebots", True),
        "VECTOR_SEARCH_INDEX": ("vertex_vector_search", "Vertex AI Vector Search (Indexes & Endpoints)", "aiplatform.googleapis.com", "Vertex AI Knowledge & RAG", "🧭", "ANN vector indexes and Index Endpoints for RAG & Enterprise Search", False),
        "VECTOR_SEARCH_ENDPOINT": ("vertex_vector_search", "Vertex AI Vector Search (Indexes & Endpoints)", "aiplatform.googleapis.com", "Vertex AI Knowledge & RAG", "🧭", "ANN vector indexes and Index Endpoints for RAG & Enterprise Search", False),
        "AGENT_REGISTRY_AGENT": ("svc_agentregistry", "Gemini Enterprise Agent Registry (Agents & MCP Servers)", "agentregistry.googleapis.com", "AGENT_GOVERNANCE", "🗂️", "Centralized catalog of AI Agents, A2A protocols and MCP Servers", True),
        "AGENT_REGISTRY_MCP": ("svc_agentregistry", "Gemini Enterprise Agent Registry (Agents & MCP Servers)", "agentregistry.googleapis.com", "AGENT_GOVERNANCE", "🗂️", "Centralized catalog of AI Agents, A2A protocols and MCP Servers", True),
        "DLP_INSPECT_TEMPLATE": ("svc_dlp", "Sensitive Data Protection (Cloud DLP)", "dlp.googleapis.com", "AI_SECURITY", "🕵️", "De-identification, PII/SPII masking and sensitive data filtering in prompts", True),
    }
    for res_item in result["deployedAiResources"]:
        spec = res_feature_specs.get(res_item["resourceType"])
        if spec:
            f_id, f_name, f_svc, f_cat, f_icon, f_desc, upgrade_api_status = spec
            f_entry = features_map.setdefault(f_id, {
                "id": f_id,
                "name": f_name,
                "service": f_svc,
                "category": f_cat,
                "icon": f_icon,
                "description": f_desc,
                "status": "DEPLOYED_RESOURCE",
                "requests": 0,
                "inferenceRequests": 0,
                "methods": set(),
                "locations": set()
            })
            if upgrade_api_status and f_entry["status"] == "API_ENABLED":
                f_entry["status"] = "DEPLOYED_RESOURCE"
            f_entry["locations"].add(res_item["location"])


def _finalize_project_inspection_formats_and_totals(
    now: datetime, features_map: dict, b_status: int, ba_granted: list,
    su_status: int, granted_perms: set, k_status: int, sa_status: int, result: dict
):
    today_str_proj = now.strftime("%Y-%m-%d")
    yesterday_str_proj = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    if result["totalRequests"] > 0 or result["totalTokens"] > 0 or len(result["deployedAiResources"]) > 0 or any(k.get("isAiStudioKey") for k in result["apiKeys"]):
        result["aiActive"] = True

    features_list = []
    for f_id, f_obj in features_map.items():
        methods_sorted = sorted(list(f_obj.get("methods", set())))
        locs_sorted = sorted(list(f_obj.get("locations", set())))
        f_obj["methods"] = methods_sorted
        f_obj["locations"] = locs_sorted
        inf_r = int(f_obj.get("inferenceRequests", 0) or 0)
        tot_r = int(f_obj.get("requests", 0) or 0)
        is_list_only = (
            inf_r == 0 and tot_r > 0 and len(methods_sorted) > 0 and
            all(m.split(".")[-1].startswith(("List", "Get", "Fetch")) for m in methods_sorted)
        )
        f_obj["isControlPlaneOnly"] = is_list_only
        if is_list_only and f_obj.get("status") == "ACTIVE_TRAFFIC":
            f_obj["status"] = "CONTROL_PLANE_ONLY"
        features_list.append(f_obj)
    features_list.sort(key=lambda x: (not x.get("isControlPlaneOnly", False), x.get("inferenceRequests", 0), x.get("requests", 0), x["name"]), reverse=True)
    result["vertexFeatures"] = features_list

    models_list = []
    for m_id, m_obj in result["models"].items():
        m_obj["locations"] = sorted(list(m_obj["locations"]))
        m_obj["costUsd"] = round(m_obj["costUsd"], 4)
        m_obj["grossCostUsd"] = round(m_obj.get("grossCostUsd", m_obj["costUsd"]), 4)
        m_obj["cacheSavingsUsd"] = round(m_obj.get("cacheSavingsUsd", 0.0), 4)
        for d_k, d_v in m_obj.get("dailySeries", {}).items():
            d_v["costUsd"] = round(d_v.get("costUsd", 0.0), 4)
            d_v["otherAiCostUsd"] = round(d_v.get("otherAiCostUsd", 0.0), 4)
        models_list.append(m_obj)
    models_list.sort(key=lambda x: (x["costUsd"], x["totalTokens"], x["invocations"]), reverse=True)
    result["models"] = models_list

    creds_list = []
    for c_id, c_obj in result["credentialsUsage"].items():
        c_obj["services"] = sorted(list(c_obj.get("services", set())))
        c_obj["methods"] = sorted(list(c_obj.get("methods", set())))
        c_obj["inferenceMethods"] = sorted(list(c_obj.get("inferenceMethods", set())))
        c_obj["systemMethods"] = sorted(list(c_obj.get("systemMethods", set())))
        c_obj["estimatedCostUsd"] = round(c_obj.get("estimatedCostUsd", 0.0), 4)
        c_obj["grossCostUsd"] = round(c_obj.get("grossCostUsd", c_obj["estimatedCostUsd"]), 4)
        c_obj["cacheSavingsUsd"] = round(c_obj.get("cacheSavingsUsd", 0.0), 4)
        d_ser_c = c_obj.get("dailySeries") or {}
        t_bc = d_ser_c.get(today_str_proj) or {}
        y_bc = d_ser_c.get(yesterday_str_proj) or {}
        c_obj["todayDate"] = today_str_proj
        c_obj["todayCalls"] = int(t_bc.get("inferenceRequests", 0) or t_bc.get("requests", 0) or 0)
        c_obj["todayTokens"] = int(t_bc.get("tokens", 0) or 0)
        c_obj["todayCostUsd"] = round(float(t_bc.get("costUsd", 0.0) or 0.0), 4)
        c_obj["yesterdayDate"] = yesterday_str_proj
        c_obj["yesterdayCalls"] = int(y_bc.get("inferenceRequests", 0) or y_bc.get("requests", 0) or 0)
        c_obj["yesterdayTokens"] = int(y_bc.get("tokens", 0) or 0)
        c_obj["yesterdayCostUsd"] = round(float(y_bc.get("costUsd", 0.0) or 0.0), 4)
        for d_k, d_v in d_ser_c.items():
            d_v["costUsd"] = round(d_v.get("costUsd", 0.0), 4)
            d_v["vertexCostUsd"] = round(d_v.get("vertexCostUsd", 0.0), 4)
            d_v["geminiCostUsd"] = round(d_v.get("geminiCostUsd", 0.0), 4)
            d_v["otherAiCostUsd"] = round(d_v.get("otherAiCostUsd", 0.0), 4)

        if "resolvedName" not in c_obj:
            if c_id.startswith("apikey:"):
                c_obj["resolvedName"] = f"API Key ({c_id.split(':', 1)[1][:10]}...)"
                c_obj["resolvedType"] = "API_KEY"
            elif c_id.startswith("serviceaccount:"):
                c_obj["resolvedName"] = f"External SA / Scanner ({c_id.split(':', 1)[1]})"
                c_obj["resolvedType"] = "SERVICE_ACCOUNT"
            elif c_id.startswith("oauth2:"):
                c_obj["resolvedName"] = f"OAuth App / Workload ({c_id.split(':', 1)[1][:18]}...)"
                c_obj["resolvedType"] = "OAUTH_CLIENT"
            else:
                c_obj["resolvedName"] = f"User / Default ADC ({c_id or 'default'})"
                c_obj["resolvedType"] = "OAUTH_CLIENT"
        creds_list.append(c_obj)

    creds_list.sort(key=lambda x: (x["estimatedCostUsd"], x["inferenceRequests"], x["requests"]), reverse=True)
    result["credentialsUsage"] = creds_list

    for d_k, d_v in result["dailySeries"].items():
        d_v["costUsd"] = round(d_v.get("costUsd", 0.0), 4)
        d_v["vertexCostUsd"] = round(d_v.get("vertexCostUsd", 0.0), 4)
        d_v["geminiCostUsd"] = round(d_v.get("geminiCostUsd", 0.0), 4)
        d_v["otherAiCostUsd"] = round(d_v.get("otherAiCostUsd", 0.0), 4)

    result["vertexGrossCostUsd"] = round(result.get("vertexGrossCostUsd", result["vertexCostUsd"]), 4)
    result["vertexCacheSavingsUsd"] = round(result.get("vertexCacheSavingsUsd", 0.0), 4)
    result["vertexCostUsd"] = round(result["vertexCostUsd"], 4)
    result["geminiGrossCostUsd"] = round(result.get("geminiGrossCostUsd", result["geminiCostUsd"]), 4)
    result["geminiCacheSavingsUsd"] = round(result.get("geminiCacheSavingsUsd", 0.0), 4)
    result["geminiCostUsd"] = round(result["geminiCostUsd"], 4)
    result["otherAiGrossCostUsd"] = round(result.get("otherAiGrossCostUsd", result["otherAiCostUsd"]), 4)
    result["otherAiCacheSavingsUsd"] = round(result.get("otherAiCacheSavingsUsd", 0.0), 4)
    result["otherAiCostUsd"] = round(result["otherAiCostUsd"], 4)
    result["estimatedCostUsd"] = round(result["estimatedCostUsd"], 4)
    result["costUsd"] = result["estimatedCostUsd"]

    result["permissions"] = build_project_permissions_summary(
        b_status=b_status,
        billing_enabled=result["billingEnabled"],
        ba_granted=ba_granted,
        su_status=su_status,
        granted_perms=granted_perms,
        k_status=k_status,
        sa_status=sa_status,
        enabled_ai_apis_count=len(result["enabledAiApis"]),
        api_keys_count=len(result["apiKeys"]),
        sa_count=len(result["serviceAccounts"])
    )


def inspect_single_project(
    proj: dict,
    token: str,
    days: int,
    budgets: dict = None,
    ba_cache: dict = None,
    prev_proj: dict = None,
    start_date: str = None,
    end_date: str = None
) -> dict:
    """
    Deeply inspects a single GCP project for AI APIs, tokens, requests, credentials, Model Armor, and user logs.
    Supports exact date/range inspection (`start_date` .. `end_date` in YYYY-MM-DD) to query only the requested days.
    """
    pid = proj.get("projectId", "")
    budgets = budgets if isinstance(budgets, dict) else {}
    ba_cache = ba_cache if isinstance(ba_cache, dict) else {}
    now = datetime.now(timezone.utc)
    end_dt = now
    if start_date or end_date:
        s_clean = str(start_date or end_date).strip()[:10]
        e_clean = str(end_date or start_date).strip()[:10]
        if s_clean > e_clean:
            s_clean, e_clean = e_clean, s_clean
        try:
            start_dt = datetime.strptime(s_clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt_raw = datetime.strptime(e_clean, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            end_dt = min(now, end_dt_raw)
            if end_dt <= start_dt:
                end_dt = min(now, start_dt + timedelta(hours=23, minutes=59, seconds=59))
            days = max(1, (end_dt_raw.date() - start_dt.date()).days + 1)
        except Exception:
            start_dt = now - timedelta(days=max(1, int(days or 30)))
            end_dt = now
    else:
        start_dt = now - timedelta(days=max(1, int(days or 30)))
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    fallback_owners = _extract_fallback_apikey_owners(prev_proj)
    result = _init_project_inspection_dict(proj, budgets)
    features_map = {}

    should_return, b_status, ba_granted, su_status, granted_perms, enabled_services_set, all_enabled_services = _check_billing_and_enabled_services(
        proj, pid, token, ba_cache, result, prev_proj=prev_proj
    )
    if should_return:
        return result

    for s_en in result.get("enabledAiApis", []):
        svc_n = s_en.get("service", "")
        if svc_n and svc_n != "aiplatform.googleapis.com":
            f_id = f"svc_{svc_n.split('.')[0]}"
            features_map.setdefault(f_id, {
                "id": f_id,
                "name": s_en.get("label", svc_n),
                "service": svc_n,
                "category": s_en.get("category", "AI_API"),
                "icon": s_en.get("icon", "✨"),
                "description": s_en.get("description", ""),
                "status": "API_ENABLED",
                "requests": 0,
                "inferenceRequests": 0,
                "methods": set(),
                "locations": set()
            })

    can_read_monitoring = "monitoring.timeSeries.list" in granted_perms
    mon_results = _prefetch_project_monitoring_metrics(
        pid, token, start_iso, end_iso, can_read_monitoring, su_status,
        enabled_services_set, all_enabled_services, result
    )

    active_locations_seen = set()
    ma_metrics = {"totalRequests": 0, "sanitizeRequests": 0, "methods": set(), "locations": set()}
    gemini_ok_calls_map = _process_serviceruntime_requests_and_latencies(
        mon_results, can_read_monitoring, result, features_map, active_locations_seen, ma_metrics
    )
    _process_gemini_api_payload_bytes(
        mon_results, pid, token, start_iso, end_iso, can_read_monitoring, gemini_ok_calls_map, result
    )
    _process_vertex_tokens_and_invocations(
        mon_results, pid, token, start_iso, end_iso, can_read_monitoring, su_status, active_locations_seen, result
    )
    _process_dialogflow_llm_tokens(
        mon_results, pid, token, start_iso, end_iso, can_read_monitoring, enabled_services_set,
        su_status, active_locations_seen, features_map, result
    )

    k_status, all_proj_keys, apikey_owners, sa_status, sa_data, prefetched_ma, prefetched_vres, prefetched_user_entries = _parallel_fetch_project_io(
        pid, token, start_dt, end_dt, days, granted_perms, enabled_services_set,
        active_locations_seen, ma_metrics, fallback_owners, result
    )

    _reconcile_apikeys_and_service_accounts(
        pid, now, k_status, all_proj_keys, apikey_owners, sa_status, sa_data, result
    )
    _register_deployed_resources_and_model_armor(prefetched_ma, prefetched_vres, features_map, result)

    if result["totalRequests"] > 0 or result["totalTokens"] > 0 or len(result["apiKeys"]) > 0 or len(result["deployedAiResources"]) > 0 or result.get("isAiStudioProject"):
        result["usersUsage"] = fetch_project_user_activity_logs(
            pid, token, start_dt, end_dt, days, result,
            apikey_owners=apikey_owners,
            prefetched_entries=prefetched_user_entries,
            prev_users_usage=prev_proj.get("usersUsage") if isinstance(prev_proj, dict) else None
        )

    _finalize_project_inspection_formats_and_totals(
        now, features_map, b_status, ba_granted, su_status, granted_perms, k_status, sa_status, result
    )
    enrich_single_project_telemetry(result, scan_days=days)
    result["aiSecurityPosture"] = evaluate_project_ai_security_posture(result)
    return result


def classify_gcp_region_residency(loc: str) -> str:
    loc_clean = (loc or "").strip().lower()
    if not loc_clean or loc_clean in ("-", "all"):
        return "UNKNOWN"
    if loc_clean == "europe-west8" or loc_clean.startswith("europe-west8 "):
        return "ITALY_LOCAL"
    if loc_clean == "eu" or loc_clean.startswith("eu ") or loc_clean.startswith("eu(") or loc_clean.startswith("europe-"):
        return "EU_EEA"
    if loc_clean == "global" or loc_clean.startswith("global "):
        return "GLOBAL_ANYCAST"
    return "NON_EU_US_OTHER"


def _enrich_normalize_costs(p: dict, days_window: int) -> float:
    if p.get("skippedNoBilling") and p.get("scanStatus") == "SKIPPED_NO_BILLING":
        perms = p.get("permissions") or {}
        if perms.get("accessLevel") == "NO_MONITORING_ACCESS":
            perms["accessLevel"] = "SKIPPED_NO_BILLING"
            perms["badgeLabel"] = "⚪ No Active Billing ($0)"

    ai_cost_val = round(float(p.get("estimatedCostUsd", p.get("costUsd", 0.0)) or 0.0), 4)
    p["estimatedCostUsd"] = ai_cost_val
    p["costUsd"] = ai_cost_val

    return ai_cost_val


def _enrich_apikeys_and_features(p: dict, now_dt: datetime) -> tuple:
    creds_by_id = {c.get("credentialId", ""): c for c in (p.get("credentialsUsage") or []) if isinstance(c, dict)}
    has_ai_studio_key = False
    ai_studio_keys_list = []

    for k in (p.get("apiKeys") or []):
        uid = str(k.get("uid", "") or "")
        disp = k.get("displayName") or ""
        svcs = k.get("services") or []
        targets = k.get("apiTargets") if "apiTargets" in k else (k.get("restrictions") or [])
        k["apiTargets"] = targets
        k["restrictions"] = targets

        age_days = None
        ct = k.get("createTime")
        if ct and isinstance(ct, str) and len(ct) >= 10:
            try:
                ct_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                age_days = max(0, (now_dt - ct_dt).days)
            except Exception:
                age_days = None
        k["ageDays"] = age_days

        if uid.isdigit() and len(uid) <= 4:
            k["status"] = "GCP_CONSOLE_FIRST_PARTY"
            k["displayName"] = f"Console GCP / Colab Enterprise UI (First-Party Key #{uid})"
            k["isAiStudioKey"] = False
            c_match = creds_by_id.get(f"apikey:{uid}")
            if c_match:
                c_match["resolvedName"] = k["displayName"]
                c_match["resolvedType"] = "GCP_CONSOLE_UI"
        else:
            is_as_key = bool(
                k.get("isAiStudioKey") or
                "generativelanguage.googleapis.com" in svcs or
                "generativelanguage.googleapis.com" in targets or
                any(w in disp.lower() for w in ("aistudio", "generative language", "gemini"))
            )
            k["isAiStudioKey"] = is_as_key
            if is_as_key:
                has_ai_studio_key = True
                ai_studio_keys_list.append({
                    "uid": uid,
                    "displayName": disp,
                    "ownerEmail": k.get("ownerEmail"),
                    "status": k.get("status", "ACTIVE"),
                    "calls": int(k.get("inferenceRequests", 0) or k.get("requests", 0) or 0),
                    "totalTokens": int(k.get("totalTokens", 0) or 0),
                    "requestBytes": int(k.get("requestBytes", 0) or 0),
                    "responseBytes": int(k.get("responseBytes", 0) or 0),
                    "costUsd": round(float(k.get("estimatedCostUsd", 0.0) or 0.0), 4),
                    "todayCalls": int(k.get("todayCalls", 0) or 0),
                    "yesterdayCalls": int(k.get("yesterdayCalls", 0) or 0),
                    "createTime": ct,
                    "ageDays": age_days,
                    "methods": k.get("inferenceMethods") or k.get("methods") or []
                })

    for f_obj in (p.get("vertexFeatures") or []):
        methods_f = f_obj.get("methods") or []
        inf_r = int(f_obj.get("inferenceRequests", 0) or 0)
        tot_r = int(f_obj.get("requests", 0) or 0)
        is_list_only = (
            inf_r == 0 and tot_r > 0 and len(methods_f) > 0 and
            all(str(m).split(".")[-1].startswith(("List", "Get", "Fetch")) for m in methods_f)
        )
        f_obj["isControlPlaneOnly"] = is_list_only
        if is_list_only and f_obj.get("status") == "ACTIVE_TRAFFIC":
            f_obj["status"] = "CONTROL_PLANE_ONLY"

    return has_ai_studio_key, ai_studio_keys_list


def _enrich_users_tools_and_models(p: dict) -> tuple:
    notebooklm_feat = next((f for f in (p.get("vertexFeatures") or []) if f.get("id") == "svc_notebooklm_enterprise"), None)
    notebooklm_project_calls = int((notebooklm_feat or {}).get("requests", 0) or (notebooklm_feat or {}).get("inferenceRequests", 0) or 0)
    colab_feat = next((f for f in (p.get("vertexFeatures") or []) if f.get("id") in ("vertex_colab_enterprise", "vertex_colab_notebooks")), None)
    colab_project_calls = int((colab_feat or {}).get("requests", 0) or 0)

    for m_obj in (p.get("models") or []):
        if "StreamGenerateContent (Antigravity / AI Studio)" in str(m_obj.get("modelId") or ""):
            has_ide_key = any(
                any(kw in str(k.get("displayName") or "").lower() for kw in ("antigravity", "ide", "vscode", "cursor", "cline", "windsurf"))
                for k in (p.get("apiKeys") or [])
            )
            if not has_ide_key:
                m_obj["modelId"] = str(m_obj["modelId"]).replace(
                    "StreamGenerateContent (Antigravity / AI Studio)",
                    "StreamGenerateContent (Gemini API Stream)"
                )

    for u in (p.get("usersUsage") or []):
        tools = set(u.get("toolsUsed") or [])
        methods_u = u.get("methods") or []
        ds_u = u.get("dataStores") or []
        svcs_u = u.get("services") or []
        ide_u = list(u.get("ideClients") or [])
        k_names_u = [str(kn).lower() for kn in (u.get("apiKeysNames") or [])]
        has_real_ide_key = any(
            any(kw in kn for kw in ("antigravity", "ide", "vscode", "cursor", "cline", "windsurf", "code assist"))
            for kn in k_names_u
        )
        cleaned_ide = [
            "Gemini API Stream (API Key)" if (ic == "Antigravity / IDE (AI Studio Stream)" and not has_real_ide_key) else ic
            for ic in ide_u
        ]
        ide_u = sorted(list(set(cleaned_ide)))
        u["ideClients"] = ide_u

        u.setdefault("codeAssistAcceptedLines", 0)
        u.setdefault("codeAssistAcceptedCount", 0)
        u.setdefault("codeAssistExposedCount", 0)
        u.setdefault("codeAssistAcceptanceRatePct", 0.0)
        u.setdefault("codeAssistInputChars", 0)
        u.setdefault("codeAssistOutputChars", 0)
        u.setdefault("codeAssistLanguages", [])
        u.setdefault("codeAssistWorkspaces", [])
        if (u.get("codeAssistCalls", 0) or 0) > 0 or (u.get("codeAssistAcceptedCount", 0) or 0) > 0:
            u["codeAssistSeatMonthlyUsd"] = float(u.get("codeAssistSeatMonthlyUsd") or 19.0)
        else:
            u["codeAssistSeatMonthlyUsd"] = 0.0

        nb_lm_calls = int(u.get("notebookLmCalls", 0) or 0)
        colab_c = int(u.get("colabCalls", 0) or 0)
        aistudio_c = int(u.get("aiStudioCalls", 0) or 0)

        if any("notebooklm" in str(d).lower() for d in ds_u) or any(
            any(k in str(m).lower() for k in ("notebook", "audiooverview", "freeformstreamed", "interactsources", "uploadsourcefile"))
            for m in methods_u
        ):
            tools.add("NotebookLM Enterprise")
            if nb_lm_calls == 0:
                nb_lm_calls = max(1, int(u.get("fileOps", 0) or 0) + int(u.get("otherCalls", 0) or 0))

        if (u.get("assistTurns", 0) or 0) > 0 or (u.get("searchQueries", 0) or 0) > 0 or u.get("engines"):
            tools.add("Gemini Enterprise / Agentspace")

        if (u.get("codeAssistCalls", 0) or 0) > 0 or "cloudaicompanion.googleapis.com" in svcs_u:
            tools.add("Gemini Code Assist / Cloud Assist")

        if "generativelanguage.googleapis.com" in svcs_u or any("ai studio" in str(ic).lower() for ic in ide_u):
            tools.add("Google AI Studio")
            if aistudio_c == 0:
                aistudio_c = int(u.get("apiKeysCalls", 0) or 0)

        if "notebooks.googleapis.com" in svcs_u or any("runtime:" in str(m).lower() or "notebookruntime" in str(m).lower() for m in methods_u):
            tools.add("Colab Enterprise / Workbench")
            if colab_c == 0:
                colab_c = 1

        if "aiplatform.googleapis.com" in svcs_u and not tools:
            tools.add("Vertex AI")

        u["notebookLmCalls"] = nb_lm_calls
        u["colabCalls"] = colab_c
        u["aiStudioCalls"] = aistudio_c
        u["queriesCount"] = int(u.get("queriesCount", 0) or (int(u.get("assistTurns", 0) or 0) + int(u.get("searchQueries", 0) or 0) + nb_lm_calls) or 0)
        u["conversationsCount"] = int(u.get("conversationsCount", 0) or (max(1, int(u.get("assistTurns", 0) or 0)) if (int(u.get("assistTurns", 0) or 0) > 0 or int(u.get("searchQueries", 0) or 0) > 0) else 0))

        # Per-user Antigravity / IDE / Code Assist, Vertex AI OAuth IDE & API Key Stream attribution
        ca_calls = int(u.get("codeAssistCalls", 0) or 0)
        ak_calls = int(u.get("apiKeysCalls", 0) or aistudio_c or 0)
        ak_tokens = int(u.get("apiKeysTotalTokens", 0) or 0)
        ak_cost = round(float(u.get("apiKeysCostUsd", 0.0) or 0.0), 4)
        vo_calls = int(u.get("vertexOauthCalls", 0) or 0)
        vo_tokens = int(u.get("vertexOauthTokens", 0) or 0)
        vo_cost = round(float(u.get("vertexOauthCostUsd", 0.0) or 0.0), 4)
        oauth_cost = float(u.get("oauthCostUsd", 0.0) or 0.0)
        non_vo_oauth_cost = max(0.0, oauth_cost - vo_cost)
        assist_t = int(u.get("assistTurns", 0) or 0)
        search_q = int(u.get("searchQueries", 0) or 0)

        if ca_calls > 0:
            if assist_t == 0 and search_q == 0 and nb_lm_calls == 0:
                ca_cost = round(non_vo_oauth_cost if non_vo_oauth_cost > 0 else (ca_calls * 0.0014), 4)
                ca_tokens = int(max(0, int(u.get("loggedTotalTokens", 0) or 0) - vo_tokens) or (ca_calls * 245))
            else:
                ca_weight_raw = ca_calls * 0.0014
                tot_oauth_raw = max(0.0001, ca_weight_raw + assist_t * 0.0041 + search_q * 0.0015)
                ca_cost = round(non_vo_oauth_cost * (ca_weight_raw / tot_oauth_raw), 4)
                ca_tokens = int(round(max(0, int(u.get("loggedTotalTokens", 0) or 0) - vo_tokens) * (ca_weight_raw / tot_oauth_raw))) or (ca_calls * 245)
        else:
            ca_cost = 0.0
            ca_tokens = 0

        has_stream_method = any("stream" in str(m).lower() for m in methods_u) or any(
            any("stream" in str(km).lower() for km in (kd.get("methods") or []))
            for kd in (u.get("apiKeysDetails") or [])
        )
        if vo_calls > 0 or vo_cost > 0:
            tools.add("Antigravity IDE (Vertex AI OAuth)")
            tools.add("Vertex AI")
            if "Antigravity IDE (Vertex AI OAuth)" not in ide_u:
                ide_u.append("Antigravity IDE (Vertex AI OAuth)")
                u["ideClients"] = sorted(list(set(ide_u)))

        if (vo_calls > 0 or vo_cost > 0) and (ca_calls > 0 or ak_calls > 0):
            ide_mode = "ANTIGRAVITY_VERTEX_OAUTH_AND_API_KEY"
        elif vo_calls > 0 or vo_cost > 0:
            ide_mode = "ANTIGRAVITY_VERTEX_OAUTH"
        elif ca_calls > 0 and ak_calls > 0:
            ide_mode = "CODE_ASSIST_AND_API_KEY"
        elif ca_calls > 0:
            ide_mode = "GEMINI_CODE_ASSIST_IDE"
        elif ak_calls > 0 and (has_stream_method or has_real_ide_key):
            ide_mode = "ANTIGRAVITY_OR_API_KEY_STREAM"
        elif ak_calls > 0:
            ide_mode = "AI_STUDIO_API_KEY"
        else:
            ide_mode = "NO_GCP_IDE_BILLING"

        if ak_calls > 0 and has_stream_method:
            tools.add("Antigravity / Gemini API Stream")

        u["codeAssistCostUsd"] = ca_cost
        u["codeAssistTokens"] = ca_tokens
        u["antigravityIdeCalls"] = ca_calls + ak_calls + vo_calls
        u["antigravityIdeTokens"] = ca_tokens + ak_tokens + vo_tokens
        u["antigravityIdeCostUsd"] = round(ca_cost + ak_cost + vo_cost, 4)
        u["antigravityIdeMode"] = ide_mode
        u["toolsUsed"] = sorted(list(tools))

    return notebooklm_feat, notebooklm_project_calls, colab_project_calls


def _add_region_residency_weight(
    region_buckets: dict, loc_str: str, calls_w: int = 0, tokens_w: int = 0,
    cost_w: float = 0.0, res_w: int = 0, source_label: str = ""
):
    if not loc_str or loc_str in ("-", "all"):
        return
    cat = classify_gcp_region_residency(loc_str)
    if cat == "UNKNOWN":
        return
    b = region_buckets.setdefault(loc_str, {
        "location": loc_str,
        "category": cat,
        "calls": 0,
        "tokens": 0,
        "costUsd": 0.0,
        "resourcesCount": 0,
        "sources": set()
    })
    b["calls"] += calls_w
    b["tokens"] += tokens_w
    b["costUsd"] = round(b["costUsd"] + cost_w, 4)
    b["resourcesCount"] += res_w
    if source_label:
        b["sources"].add(source_label)


def _enrich_data_residency(p: dict, pid: str) -> dict:
    region_NullSafe = {}

    for m_obj in (p.get("models") or []):
        m_locs = m_obj.get("locations") or ["global"]
        n_l = max(1, len(m_locs))
        for l_item in m_locs:
            _add_region_residency_weight(
                region_NullSafe, l_item,
                calls_w=int(round((m_obj.get("invocations", 0) or 0) / n_l)),
                tokens_w=int(round((m_obj.get("totalTokens", 0) or 0) / n_l)),
                cost_w=float(m_obj.get("costUsd", 0.0) or 0.0) / n_l,
                source_label=f"Model:{m_obj.get('modelId', 'LLM')}"
            )

    non_eu_deployed_resources = []
    re_groups = {}

    for r_obj in (p.get("deployedAiResources") or []):
        r_loc = str(r_obj.get("location") or r_obj.get("region") or "global")
        r_t = str(r_obj.get("resourceType") or r_obj.get("type") or "RESOURCE")
        r_name = str(r_obj.get("displayName") or r_obj.get("name") or r_obj.get("resourceId") or "")
        r_obj["type"] = r_t
        r_obj["resourceType"] = r_t
        r_obj["name"] = r_name
        r_obj["displayName"] = r_obj.get("displayName") or r_name
        r_obj["region"] = r_loc
        r_obj["location"] = r_loc

        _add_region_residency_weight(region_NullSafe, r_loc, res_w=1, source_label=r_t)
        if classify_gcp_region_residency(r_loc) == "NON_EU_US_OTHER":
            non_eu_deployed_resources.append({
                "projectId": pid,
                "name": r_name,
                "displayName": r_name,
                "type": r_t,
                "resourceType": r_t,
                "region": r_loc,
                "location": r_loc
            })
        if r_t in ("REASONING_ENGINE", "AGENT_REGISTRY_AGENT"):
            base_name = re.sub(r'[-_\s]+(?:20\d{2}[-_]?\d{2}[-_]?\d{2}(?:[-_\sT:]?\d{2}(?:[-_:]?\d{2}){0,2})?|\d{8,14})$', '', r_name).strip() or r_name
            re_groups.setdefault((r_t, base_name), []).append((r_obj, r_loc, r_name))

    for f_obj in (p.get("vertexFeatures") or []):
        if f_obj.get("isControlPlaneOnly"):
            continue
        f_inf = int(f_obj.get("inferenceRequests", 0) or 0)
        if f_inf > 0:
            f_locs = [loc for loc in (f_obj.get("locations") or []) if loc not in ("-", "all")]
            if len(f_locs) <= 6:
                for l_item in f_locs:
                    _add_region_residency_weight(
                        region_NullSafe, l_item,
                        calls_w=int(round(f_inf / max(1, len(f_locs)))),
                        source_label=f_obj.get("name", "Feature")
                    )

    regions_list = []
    cat_totals = {"ITALY_LOCAL": 0.0, "EU_EEA": 0.0, "GLOBAL_ANYCAST": 0.0, "NON_EU_US_OTHER": 0.0}
    breakdown = {
        k: {"calls": 0, "tokens": 0, "costUsd": 0.0, "resourcesCount": 0}
        for k in ("ITALY_LOCAL", "EU_EEA", "GLOBAL_ANYCAST", "NON_EU_US_OTHER")
    }
    non_eu_locs = []
    global_locs = []
    eu_locs = []

    for loc_k, b_val in region_NullSafe.items():
        b_val["sources"] = sorted(list(b_val["sources"]))
        regions_list.append(b_val)
        weight_score = (b_val["costUsd"] * 1000.0) + (b_val["tokens"] / 1000.0) + b_val["calls"] + (b_val["resourcesCount"] * 50.0)
        cat = b_val["category"]
        if cat in cat_totals:
            cat_totals[cat] += max(1.0, weight_score)
            breakdown[cat]["calls"] += int(b_val["calls"] or 0)
            breakdown[cat]["tokens"] += int(b_val["tokens"] or 0)
            breakdown[cat]["costUsd"] = round(breakdown[cat]["costUsd"] + float(b_val["costUsd"] or 0.0), 4)
            breakdown[cat]["resourcesCount"] += int(b_val["resourcesCount"] or 0)
        if cat == "NON_EU_US_OTHER":
            non_eu_locs.append(loc_k)
        elif cat == "GLOBAL_ANYCAST":
            global_locs.append(loc_k)
        elif cat in ("ITALY_LOCAL", "EU_EEA"):
            eu_locs.append(loc_k)

    regions_list.sort(key=lambda x: (x["costUsd"], x["tokens"], x["calls"], x["resourcesCount"]), reverse=True)
    tot_w = sum(cat_totals.values())
    it_pct = round((cat_totals["ITALY_LOCAL"] / tot_w) * 100.0, 1) if tot_w > 0 else 0.0
    eu_pct = round(((cat_totals["ITALY_LOCAL"] + cat_totals["EU_EEA"]) / tot_w) * 100.0, 1) if tot_w > 0 else 100.0
    glob_pct = round((cat_totals["GLOBAL_ANYCAST"] / tot_w) * 100.0, 1) if tot_w > 0 else 0.0
    noneu_pct = round((cat_totals["NON_EU_US_OTHER"] / tot_w) * 100.0, 1) if tot_w > 0 else 0.0

    if non_eu_locs:
        res_status = "NON_EU_ALERT"
        res_label = f"🚨 Non-EU ({', '.join(non_eu_locs[:3])})"
    elif global_locs and not eu_locs:
        res_status = "GLOBAL_ONLY"
        res_label = "🌐 Endpoint Global (Multi-Region Anycast)"
    elif global_locs and eu_locs:
        res_status = "EU_AND_GLOBAL"
        res_label = f"🇪🇺 EU + Global ({', '.join(eu_locs[:2])} / global)"
    elif eu_locs and all(l == "europe-west8" for l in eu_locs):
        res_status = "ITALY_LOCAL"
        res_label = "🇮🇹 100% Italy (europe-west8 Milan)"
    elif eu_locs:
        res_status = "EU_COMPLIANT"
        res_label = f"🇮🇹/🇪🇺 100% EU ({', '.join(eu_locs[:3])})"
    else:
        res_status = "NO_TRAFFIC"
        res_label = "⚪ No Active Region"

    p["dataResidency"] = {
        "status": res_status,
        "label": res_label,
        "statusLabel": res_label,
        "primaryStatusLabel": res_label,
        "gdprCompliant": (len(non_eu_locs) == 0 and len(non_eu_deployed_resources) == 0),
        "hasNonEuTraffic": (len(non_eu_locs) > 0 or len(non_eu_deployed_resources) > 0),
        "italySharePct": it_pct,
        "euSharePct": eu_pct,
        "globalSharePct": glob_pct,
        "nonEuSharePct": noneu_pct,
        "nonEuPct": noneu_pct,
        "euLocations": sorted(eu_locs),
        "globalLocations": sorted(global_locs),
        "nonEuLocations": sorted(non_eu_locs),
        "nonEuDeployedResources": non_eu_deployed_resources,
        "nonEuResourcesCount": len(non_eu_deployed_resources),
        "regionsUsed": [r["location"] for r in regions_list],
        "breakdown": breakdown,
        "regions": regions_list
    }
    return re_groups


def _enrich_finops_extended(p: dict, pid: str, ai_cost_val: float, days_window: int, re_groups: dict):
    in_tok = int(p.get("inputTokens", 0) or 0)
    cached_tok = int(p.get("cachedTokens", 0) or 0)
    total_prompt_tok = max(in_tok, cached_tok)
    uncached_in_tok = max(0, total_prompt_tok - cached_tok)
    cache_hit_pct = round((cached_tok / total_prompt_tok) * 100.0, 2) if total_prompt_tok > 0 else 0.0
    cache_savings_usd = round(
        float(p.get("vertexCacheSavingsUsd", 0.0) or 0.0) +
        float(p.get("geminiCacheSavingsUsd", 0.0) or 0.0) +
        float(p.get("otherAiCacheSavingsUsd", 0.0) or 0.0),
        4
    )
    if cache_savings_usd == 0.0 and p.get("models"):
        cache_savings_usd = round(sum(float(m.get("cacheSavingsUsd", 0.0) or 0.0) for m in (p.get("models") or [])), 4)
    gross_ai_usd = round(
        float(p.get("vertexGrossCostUsd", p.get("vertexCostUsd", 0.0)) or 0.0) +
        float(p.get("geminiGrossCostUsd", p.get("geminiCostUsd", 0.0)) or 0.0) +
        float(p.get("otherAiGrossCostUsd", p.get("otherAiCostUsd", 0.0)) or 0.0),
        4
    )
    p["cacheSavingsUsd"] = cache_savings_usd
    p["grossCostUsd"] = max(gross_ai_usd, round(float(p.get("estimatedCostUsd", 0.0) or 0.0) + cache_savings_usd, 4))

    potential_extra_savings = 0.0
    for m_obj in (p.get("models") or []):
        m_in = int(m_obj.get("inputTokens", 0) or 0)
        m_cache = int(m_obj.get("cachedTokens", 0) or 0)
        if m_in > 100_000 and m_cache < m_in:
            uncached_excess = max(0, int((m_in - m_cache) * 0.50))
            m_rates = get_model_rates(m_obj.get("modelId", ""))
            unit_saving = max(0.0, m_rates["input"] - m_rates["cache_read_input"])
            potential_extra_savings += (uncached_excess / 1_000_000.0) * unit_saving

    zombie_engines = []
    for (r_t_grp, base_name), grp_items in re_groups.items():
        grp_items.sort(key=lambda x: (str(x[0].get("createTime") or ""), x[2]), reverse=True)
        latest_name = grp_items[0][2]
        for idx_g, (r_obj, r_loc, r_name) in enumerate(grp_items):
            is_eu_loc = classify_gcp_region_residency(r_loc) in ("ITALY_LOCAL", "EU_EEA", "GLOBAL_ANYCAST")
            r_obj["baseName"] = base_name
            if idx_g == 0:
                r_obj["isLatestVersion"] = True
                r_obj["isZombieVersion"] = False
                r_obj["zombieStatus"] = "ACTIVE_LATEST"
            else:
                r_obj["isLatestVersion"] = False
                r_obj["isZombieVersion"] = True
                r_obj["zombieStatus"] = "ZOMBIE_OLD_BUILD"
                r_obj["keptLatestName"] = latest_name
                zombie_engines.append({
                    "projectId": pid,
                    "type": r_t_grp,
                    "resourceType": r_t_grp,
                    "name": r_name,
                    "displayName": r_name,
                    "baseName": base_name,
                    "region": r_loc,
                    "location": r_loc,
                    "isEu": is_eu_loc,
                    "createTime": r_obj.get("createTime", "") or "",
                    "keptLatestName": latest_name,
                    "reason": f"Outdated build replaced by '{latest_name}'" + (" [NON-EU!]" if not is_eu_loc else "")
                })

    idle_resources = []
    for r_obj in (p.get("deployedAiResources") or []):
        r_t = r_obj.get("resourceType") or r_obj.get("type") or ""
        if r_t == "VERTEX_ENDPOINT" and int(r_obj.get("deployedModelsCount", 0) or 0) == 0:
            idle_resources.append({
                "resourceType": r_t,
                "displayName": r_obj.get("displayName"),
                "location": r_obj.get("location"),
                "reason": "Vertex AI endpoint registered with 0 deployed models (Idle)",
                "estimatedMonthlyWasteUsd": 0.0
            })
        elif r_t == "VERTEX_ENDPOINT" and int(r_obj.get("deployedModelsCount", 0) or 0) > 0 and (p.get("inferenceRequests", 0) or 0) == 0:
            idle_resources.append({
                "resourceType": r_t,
                "displayName": r_obj.get("displayName"),
                "location": r_obj.get("location"),
                "reason": "Endpoint with deployed models but 0 inference calls in the period (Zombie GPU/CPU)",
                "estimatedMonthlyWasteUsd": 180.0
            })
        elif r_t == "VECTOR_SEARCH_ENDPOINT" and (p.get("inferenceRequests", 0) or 0) == 0:
            idle_resources.append({
                "resourceType": r_t,
                "displayName": r_obj.get("displayName"),
                "location": r_obj.get("location"),
                "reason": "Vector Search Endpoint active with no queries detected",
                "estimatedMonthlyWasteUsd": 95.0
            })
        elif r_t in ("COLAB_ENTERPRISE_RUNTIME", "WORKBENCH_NOTEBOOK") and str(r_obj.get("runtimeState", "")).upper() in ("RUNNING", "ACTIVE"):
            idle_resources.append({
                "resourceType": r_t,
                "displayName": r_obj.get("displayName"),
                "location": r_obj.get("location"),
                "reason": f"Notebook Runtime in state {r_obj.get('runtimeState')} ({r_obj.get('machineType') or 'active VM'}) — verify auto-shutdown",
                "estimatedMonthlyWasteUsd": 65.0
            })

    for (r_t_grp, base_name), grp_items in re_groups.items():
        if len(grp_items) > 1:
            latest_name = grp_items[0][2]
            idle_resources.append({
                "resourceType": r_t_grp,
                "displayName": f"{base_name} ({len(grp_items) - 1} outdated builds)",
                "location": grp_items[0][1],
                "reason": f"{len(grp_items) - 1} previous CI/CD versions not removed (latest active: '{latest_name}')",
                "estimatedMonthlyWasteUsd": 0.0
            })

    daily_burn_ai = round(ai_cost_val / days_window, 4)

    p["finopsExtended"] = {
        "cacheHitRatePct": cache_hit_pct,
        "inputTokens": total_prompt_tok,
        "cachedTokens": cached_tok,
        "uncachedInputTokens": uncached_in_tok,
        "cacheSavingsUsd": cache_savings_usd,
        "potentialExtraCacheSavingsUsd": round(potential_extra_savings, 4),
        "idleResourcesCount": len(idle_resources),
        "idleResources": idle_resources,
        "estimatedMonthlyIdleWasteUsd": round(sum(x["estimatedMonthlyWasteUsd"] for x in idle_resources), 2),
        "zombieReasoningEngines": zombie_engines,
        "zombieReasoningEnginesCount": len(zombie_engines),
        "dailyBurnRateAiUsd": daily_burn_ai,
        "forecast30dAiUsd": round(daily_burn_ai * 30.0, 2),
    }

def _infer_connector_type(ds_id_or_name: str) -> str:
    low_s = (ds_id_or_name or "").lower()
    connector_rules = (
        (("mail", "gmail"), "Gmail"),
        (("drive",), "Google Drive"),
        (("calendar",), "Google Calendar"),
        (("chat",), "Google Chat"),
        (("wiki", "confluence"), "Wiki / Confluence"),
        (("docusign",), "DocuSign"),
        (("jira",), "Jira"),
        (("notebooklm",), "NotebookLM"),
        (("asset", "gcp"), "GCP Asset Inventory"),
        (("sharepoint", "onedrive"), "SharePoint / OneDrive"),
    )
    for keywords, label in connector_rules:
        if any(k in low_s for k in keywords):
            return label
    return "Enterprise DataStore"


def _enrich_agentspace_telemetry(p: dict, pid: str):
    as_apps_map = {}
    as_ds_map = {}
    for r_obj in (p.get("deployedAiResources") or []):
        r_t = r_obj.get("resourceType") or r_obj.get("type") or ""
        r_id = str(r_obj.get("resourceId") or r_obj.get("id") or r_obj.get("displayName") or r_obj.get("name") or "")
        r_disp = str(r_obj.get("displayName") or r_obj.get("name") or r_id)
        r_loc = str(r_obj.get("location") or r_obj.get("region") or "global")
        if r_t == "AGENTSPACE_APP" and r_id:
            en_models = r_obj.get("enabledModels") or []
            def_mod = en_models[0] if en_models else (r_obj.get("defaultModel") or "gemini-2.5-pro")
            linked_ds = r_obj.get("dataStoreIds") or r_obj.get("linkedDataStores") or []
            as_apps_map[r_id] = {
                "projectId": pid,
                "id": r_id,
                "engineId": r_id,
                "name": r_disp,
                "displayName": r_disp,
                "cid": r_obj.get("cid", ""),
                "region": r_loc,
                "location": r_loc,
                "defaultModel": def_mod,
                "linkedDataStoresCount": int(r_obj.get("dataStoresCount", len(linked_ds)) or len(linked_ds)),
                "queries": 0,
                "queriesCount": 0,
                "conversationsCount": 0,
                "activeUsersCount": 0,
                "users": set(),
                "status": "ZERO_TRAFFIC"
            }
        elif r_t == "AGENTSPACE_DATASTORE" and r_id:
            as_ds_map[r_id] = {
                "projectId": pid,
                "id": r_id,
                "dataStoreId": r_id,
                "name": r_disp,
                "displayName": r_disp,
                "connectorType": r_obj.get("connectorType") or _infer_connector_type(f"{r_id} {r_disp}"),
                "region": r_loc,
                "location": r_loc,
                "queries": 0,
                "queriesCount": 0,
                "activeUsersCount": 0,
                "users": set(),
                "unused": True,
                "status": "UNUSED_0_QUERIES"
            }

    tot_user_queries = 0
    tot_user_convs = 0
    for u_obj in (p.get("usersUsage") or []):
        u_em = str(u_obj.get("userEmail") or "")
        u_q = int(u_obj.get("queriesCount", 0) or (int(u_obj.get("assistTurns", 0) or 0) + int(u_obj.get("searchQueries", 0) or 0) + int(u_obj.get("notebookLmCalls", 0) or 0)) or 0)
        u_c = int(u_obj.get("conversationsCount", 0) or 0)
        tot_user_queries += u_q
        tot_user_convs += u_c

        u_engs = u_obj.get("engines")
        if isinstance(u_engs, dict):
            eng_items = list(u_engs.items())
        elif isinstance(u_engs, list):
            n_e = max(1, len(u_engs))
            eng_items = [(str(e_id), max(1, int(round(u_q / n_e))) if u_q > 0 else 1) for e_id in u_engs if e_id]
        else:
            eng_items = []

        for e_id, e_cnt in eng_items:
            target_app = as_apps_map.get(e_id)
            if not target_app:
                for k_app, v_app in as_apps_map.items():
                    if e_id in k_app or k_app in e_id or e_id.lower() == v_app["name"].lower():
                        target_app = v_app
                        break
            if not target_app:
                target_app = as_apps_map.setdefault(e_id, {
                    "projectId": pid,
                    "id": e_id,
                    "engineId": e_id,
                    "name": e_id,
                    "displayName": e_id,
                    "cid": "",
                    "region": "global",
                    "location": "global",
                    "defaultModel": "gemini-2.5-pro",
                    "linkedDataStoresCount": 0,
                    "queries": 0,
                    "queriesCount": 0,
                    "conversationsCount": 0,
                    "activeUsersCount": 0,
                    "users": set(),
                    "status": "ACTIVE"
                })
            target_app["queriesCount"] += int(e_cnt or 0)
            target_app["queries"] = target_app["queriesCount"]
            target_app["conversationsCount"] += max(1, u_c) if int(e_cnt or 0) > 0 else 0
            if u_em:
                target_app["users"].add(u_em)

        u_dss = u_obj.get("dataStores")
        if isinstance(u_dss, dict):
            ds_items = list(u_dss.items())
        elif isinstance(u_dss, list):
            n_d = max(1, len(u_dss))
            ds_items = [(str(d_id), max(1, int(round(u_q / n_d))) if u_q > 0 else 1) for d_id in u_dss if d_id]
        else:
            ds_items = []

        for d_id, d_cnt in ds_items:
            target_ds = as_ds_map.get(d_id)
            if not target_ds:
                for k_ds, v_ds in as_ds_map.items():
                    if d_id in k_ds or k_ds in d_id or d_id.lower() == v_ds["name"].lower():
                        target_ds = v_ds
                        break
            if not target_ds:
                target_ds = as_ds_map.setdefault(d_id, {
                    "projectId": pid,
                    "id": d_id,
                    "dataStoreId": d_id,
                    "name": d_id,
                    "displayName": d_id,
                    "connectorType": _infer_connector_type(d_id),
                    "region": "global",
                    "location": "global",
                    "queries": 0,
                    "queriesCount": 0,
                    "activeUsersCount": 0,
                    "users": set(),
                    "unused": False,
                    "status": "ACTIVE"
                })
            target_ds["queriesCount"] += int(d_cnt or 0)
            target_ds["queries"] = target_ds["queriesCount"]
            if u_em:
                target_ds["users"].add(u_em)

    as_apps_list = []
    for app_v in as_apps_map.values():
        app_v["users"] = sorted(list(app_v["users"]))
        app_v["activeUsers"] = app_v["users"][:10]
        app_v["activeUsersCount"] = len(app_v["users"])
        app_v["queries"] = app_v["queriesCount"]
        app_v["status"] = "ACTIVE" if app_v["queriesCount"] > 0 else "ZERO_TRAFFIC"
        as_apps_list.append(app_v)
    as_apps_list.sort(key=lambda x: (x["queriesCount"], x["activeUsersCount"], x["name"]), reverse=True)

    as_ds_list = []
    for ds_v in as_ds_map.values():
        ds_v["users"] = sorted(list(ds_v["users"]))
        ds_v["activeUsers"] = ds_v["users"][:10]
        ds_v["activeUsersCount"] = len(ds_v["users"])
        ds_v["queries"] = ds_v["queriesCount"]
        ds_v["unused"] = (ds_v["queriesCount"] == 0)
        ds_v["status"] = "ACTIVE" if ds_v["queriesCount"] > 0 else "UNUSED_0_QUERIES"
        as_ds_list.append(ds_v)
    as_ds_list.sort(key=lambda x: (x["queriesCount"], x["activeUsersCount"], x["name"]), reverse=True)

    p["agentspaceTelemetry"] = {
        "totalApps": len(as_apps_list),
        "activeAppsCount": sum(1 for a in as_apps_list if a["queriesCount"] > 0),
        "totalDataStores": len(as_ds_list),
        "activeDataStoresCount": sum(1 for d in as_ds_list if d["queriesCount"] > 0),
        "unusedDataStoresCount": sum(1 for d in as_ds_list if d["queriesCount"] == 0),
        "totalUserQueries": max(tot_user_queries, sum(a["queriesCount"] for a in as_apps_list)),
        "totalConversations": max(tot_user_convs, sum(a["conversationsCount"] for a in as_apps_list)),
        "apps": as_apps_list,
        "dataStores": as_ds_list
    }

    with contextlib.suppress(KeyError, TypeError, ValueError):
        build_project_gemini_enterprise_inventory(p)


def _collect_forensics_resources_and_mutations(deployed_all: list, ds_all: dict, users_all: list, creds_all: list):
    public_endpoints = []
    non_cmek_resources = []
    for r_obj in deployed_all:
        rt = r_obj.get("resourceType") or r_obj.get("type") or ""
        det_low = str(r_obj.get("details", "")).lower()
        if rt in ("VERTEX_ENDPOINT", "VECTOR_SEARCH_ENDPOINT"):
            if "private" not in det_low and "psc" not in det_low and "vpc" not in det_low and not r_obj.get("network"):
                public_endpoints.append(r_obj.get("displayName") or r_obj.get("resourceId") or rt)
        if rt in ("VERTEX_ENDPOINT", "VECTOR_SEARCH_ENDPOINT", "COLAB_ENTERPRISE_RUNTIME", "WORKBENCH_NOTEBOOK", "REASONING_ENGINE", "RAG_CORPUS"):
            if not (r_obj.get("cmekKey") or r_obj.get("encryptionSpec") or "cmek" in det_low or "kms" in det_low):
                non_cmek_resources.append(r_obj.get("displayName") or r_obj.get("resourceId") or rt)

    weekend_calls = 0
    weekend_cost = 0.0
    active_day_costs = [float(v.get("costUsd", 0.0) or 0.0) for v in ds_all.values() if float(v.get("costUsd", 0.0) or 0.0) > 0]
    avg_active_day_cost = (sum(active_day_costs) / len(active_day_costs)) if active_day_costs else 0.0
    spike_days = []

    for day_k, d_val in ds_all.items():
        d_c = float(d_val.get("costUsd", 0.0) or 0.0)
        d_req = int(d_val.get("inferenceRequests", 0) or 0)
        with contextlib.suppress(ValueError, TypeError):
            wd = datetime.strptime(day_k[:10], "%Y-%m-%d").weekday()
            if wd in (5, 6):
                weekend_calls += d_req
                weekend_cost += d_c
        if len(active_day_costs) >= 3 and d_c > max(0.50, avg_active_day_cost * 2.5):
            spike_days.append({"date": day_k, "costUsd": round(d_c, 4), "calls": d_req, "ratioVsAvg": round(d_c / max(0.0001, avg_active_day_cost), 1)})

    spike_days.sort(key=lambda x: x["costUsd"], reverse=True)

    mutation_methods = set()
    read_prefixes = ("list", "get", "fetch", "query", "search", "predict", "generate", "stream", "converse", "answer", "count", "embed", "sanitize")
    for u_obj in users_all:
        for m_str in (u_obj.get("methods") or []):
            m_clean = str(m_str).split(":")[-1].split(".")[-1]
            if m_clean and not m_clean.lower().startswith(read_prefixes):
                mutation_methods.add(m_clean)
    mutation_verbs = ("create", "update", "delete", "deploy", "undeploy", "import", "upload", "setiam", "start", "stop", "patch")
    for c_obj in creds_all:
        for m_str in (c_obj.get("methods") or []):
            m_clean = str(m_str).split(".")[-1]
            if m_clean and any(m_clean.lower().startswith(w) for w in mutation_verbs):
                mutation_methods.add(m_clean)

    return public_endpoints, non_cmek_resources, weekend_calls, weekend_cost, spike_days, mutation_methods


def _enrich_ai_tools_summary(
    p: dict, pid_low: str, name_low: str, has_ai_studio_key: bool,
    ai_studio_keys_list: list, notebooklm_feat: dict, notebooklm_project_calls: int, colab_project_calls: int
):
    enabled_set = {a.get("service", "") for a in (p.get("enabledAiApis") or [])}
    is_aistudio_proj = bool(
        p.get("isAiStudioProject") or
        pid_low.startswith("gen-lang-client-") or
        "aistudio" in pid_low or
        "ai-studio" in pid_low or
        "gemini api" in name_low or
        "generativelanguage.googleapis.com" in enabled_set or
        (p.get("geminiApiRequests", 0) or 0) > 0 or
        has_ai_studio_key
    )
    p["isAiStudioProject"] = is_aistudio_proj

    colab_resources = [
        r for r in (p.get("deployedAiResources") or [])
        if (r.get("resourceType") or r.get("type")) in ("COLAB_ENTERPRISE_TEMPLATE", "COLAB_RUNTIME_TEMPLATE", "COLAB_ENTERPRISE_RUNTIME", "COLAB_RUNTIME", "COLAB_EXECUTION_JOB", "WORKBENCH_NOTEBOOK", "WORKBENCH_INSTANCE")
    ]
    colab_runtimes_cnt = sum(1 for r in colab_resources if (r.get("resourceType") or r.get("type")) in ("COLAB_ENTERPRISE_RUNTIME", "COLAB_RUNTIME", "COLAB_EXECUTION_JOB"))
    colab_templates_cnt = sum(1 for r in colab_resources if (r.get("resourceType") or r.get("type")) in ("COLAB_ENTERPRISE_TEMPLATE", "COLAB_RUNTIME_TEMPLATE"))
    workbench_cnt = sum(1 for r in colab_resources if (r.get("resourceType") or r.get("type")) in ("WORKBENCH_NOTEBOOK", "WORKBENCH_INSTANCE"))

    notebooklm_datastores = [
        r for r in (p.get("deployedAiResources") or [])
        if (r.get("resourceType") or r.get("type")) == "AGENTSPACE_DATASTORE" and "notebooklm" in (r.get("resourceId", "") + " " + r.get("displayName", "")).lower()
    ]
    has_notebooks_or_colab = bool(
        len(colab_resources) > 0 or
        colab_project_calls > 0 or
        "notebooks.googleapis.com" in enabled_set or
        notebooklm_project_calls > 0 or
        len(notebooklm_datastores) > 0
    )

    as_users_list = sorted(list({
        u.get("userEmail") for u in (p.get("usersUsage") or [])
        if "Google AI Studio" in (u.get("toolsUsed") or []) and u.get("userEmail")
    } | {k.get("ownerEmail") for k in ai_studio_keys_list if k.get("ownerEmail")}))

    nb_users_list = sorted(list({
        u.get("userEmail") for u in (p.get("usersUsage") or [])
        if any(t in (u.get("toolsUsed") or []) for t in ("NotebookLM Enterprise", "Colab Enterprise / Workbench")) and u.get("userEmail")
    } | {r.get("runtimeUser") for r in colab_resources if r.get("runtimeUser")}))

    as_calls = int(p.get("geminiApiRequests", 0) or sum(k.get("calls", 0) for k in ai_studio_keys_list))
    as_tokens = int(sum(k.get("totalTokens", 0) for k in ai_studio_keys_list))
    as_cost = round(float(p.get("geminiCostUsd", 0.0) or sum(k.get("costUsd", 0.0) for k in ai_studio_keys_list)), 4)
    as_req_b = int(p.get("geminiRequestBytes", 0) or sum(k.get("requestBytes", 0) for k in ai_studio_keys_list))
    as_resp_b = int(p.get("geminiResponseBytes", 0) or sum(k.get("responseBytes", 0) for k in ai_studio_keys_list))

    p["aiToolsSummary"] = {
        "isAiStudioProject": is_aistudio_proj,
        "isGenLangClientAutoProject": pid_low.startswith("gen-lang-client-"),
        "geminiDeveloperApiEnabled": "generativelanguage.googleapis.com" in enabled_set,
        "geminiApiRequests": as_calls,
        "geminiApiCostUsd": as_cost,
        "geminiRequestBytes": as_req_b,
        "geminiResponseBytes": as_resp_b,
        "aiStudioKeysCount": len(ai_studio_keys_list),
        "aiStudioKeys": ai_studio_keys_list,
        "aiStudioUsers": as_users_list,
        "hasNotebooksOrColab": has_notebooks_or_colab,
        "colabEnterpriseCalls": colab_project_calls,
        "colabResourcesCount": len(colab_resources),
        "colabResources": colab_resources,
        "notebookLmEnterpriseCalls": notebooklm_project_calls,
        "notebookLmMethods": (notebooklm_feat or {}).get("methods") or [],
        "notebookLmDataStores": [d.get("displayName") or d.get("resourceId") for d in notebooklm_datastores],
        "notebookUsers": nb_users_list,
        "aiStudio": {
            "isAiStudioProject": is_aistudio_proj,
            "tier": "PAID_PAY_AS_YOU_GO" if p.get("billingEnabled") else "FREE_TIER_NO_BILLING",
            "apiKeysCount": len(ai_studio_keys_list),
            "inferenceCalls": as_calls,
            "totalTokens": as_tokens,
            "costUsd": as_cost,
            "requestBytes": as_req_b,
            "responseBytes": as_resp_b,
            "owners": as_users_list
        },
        "notebooks": {
            "hasNotebooksOrColab": has_notebooks_or_colab,
            "notebookLmEnterpriseCalls": notebooklm_project_calls,
            "colabEnterpriseCalls": colab_project_calls,
            "colabRuntimesCount": colab_runtimes_cnt,
            "colabTemplatesCount": colab_templates_cnt,
            "workbenchInstancesCount": workbench_cnt,
            "users": nb_users_list
        }
    }


def _enrich_ai_log_forensics(p: dict):
    creds_all = p.get("credentialsUsage") or []
    keys_all = p.get("apiKeys") or []
    users_all = p.get("usersUsage") or []
    deployed_all = p.get("deployedAiResources") or []
    ds_all = p.get("dailySeries") or {}

    err_429_total = max(
        int(p.get("errors429", 0) or 0),
        sum(int(c.get("errors429", 0) or 0) for c in creds_all)
    )
    err_other_total = sum(int(c.get("otherErrors", 0) or 0) for c in creds_all)
    failed_inf_total = sum(
        max(0, int(c.get("inferenceRequests", 0) or 0) - int(c.get("ok200Inference", c.get("inferenceRequests", 0)) or 0))
        for c in creds_all
    )
    total_failed_or_denied = max(err_other_total, failed_inf_total)
    tot_r_proj = max(1, int(p.get("totalRequests", 0) or 0))
    err_rate_pct = round(((err_429_total + total_failed_or_denied) / float(tot_r_proj)) * 100.0, 2) if int(p.get("totalRequests", 0) or 0) > 0 else 0.0

    user_api_keys = [k for k in keys_all if k.get("status") != "GCP_CONSOLE_FIRST_PARTY"]
    unrestricted_keys_cnt = sum(1 for k in user_api_keys if not (k.get("restrictions") or k.get("apiTargets")))
    stale_keys_90d_cnt = sum(1 for k in user_api_keys if k.get("status") == "ACTIVE" and (k.get("ageDays") or 0) > 90)
    ghost_deleted_keys = [
        k for k in user_api_keys
        if k.get("status") == "DELETED_OR_EXTERNAL" and (int(k.get("inferenceRequests", 0) or 0) > 0 or int(k.get("requests", 0) or 0) > 0)
    ]
    console_fp_keys = [k for k in keys_all if k.get("status") == "GCP_CONSOLE_FIRST_PARTY"]

    sa_list = p.get("serviceAccounts") or []
    exported_sa_keys_cnt = sum(int(sa.get("userManagedKeysCount", 0) or 0) for sa in sa_list)
    external_users = [
        u.get("userEmail") for u in users_all
        if u.get("userType") == "EXTERNAL_USER" or "@external." in str(u.get("userEmail", "")).lower()
    ]
    unattributed_cred = next((c for c in creds_all if c.get("credentialId") == "system:unattributed-audit-logs-disabled"), None)
    unattributed_tokens = int((unattributed_cred or {}).get("totalTokens", 0) or 0)
    unattributed_calls = int((unattributed_cred or {}).get("inferenceRequests", 0) or (unattributed_cred or {}).get("requests", 0) or 0)

    public_endpoints, non_cmek_resources, weekend_calls, weekend_cost, spike_days, mutation_methods = (
        _collect_forensics_resources_and_mutations(deployed_all, ds_all, users_all, creds_all)
    )

    sec_keywords = []
    for cond, kw_str in (
        (unrestricted_keys_cnt > 0, f"UNRESTRICTED_KEYS:{unrestricted_keys_cnt}"),
        (len(ghost_deleted_keys) > 0, f"GHOST_DELETED_KEYS:{len(ghost_deleted_keys)}"),
        (stale_keys_90d_cnt > 0, f"KEYS_OVER_90D:{stale_keys_90d_cnt}"),
        (exported_sa_keys_cnt > 0, f"STATIC_SA_KEYS:{exported_sa_keys_cnt}"),
        (unattributed_tokens > 0 or unattributed_calls > 0, "AUDIT_BLINDNESS_NO_DATA_ACCESS"),
        (len(public_endpoints) > 0, f"PUBLIC_ENDPOINTS:{len(public_endpoints)}"),
        (len(non_cmek_resources) > 0, f"GOOGLE_MANAGED_KMS:{len(non_cmek_resources)}"),
        (len(external_users) > 0, f"EXTERNAL_USERS:{len(external_users)}"),
        (err_429_total > 0, f"HTTP_429_QUOTA:{err_429_total}"),
        (total_failed_or_denied > 0, f"HTTP_4XX_5XX_FAIL:{total_failed_or_denied}"),
        (len(spike_days) > 0, f"COST_SPIKE_DAYS:{len(spike_days)}"),
        (weekend_calls > 0, f"WEEKEND_CALLS:{weekend_calls}"),
    ):
        if cond:
            sec_keywords.append(kw_str)

    p["aiLogForensics"] = {
        "errors429Count": err_429_total,
        "failedOrDeniedCallsCount": total_failed_or_denied,
        "errorRatePct": err_rate_pct,
        "unrestrictedKeysCount": unrestricted_keys_cnt,
        "staleKeysOver90dCount": stale_keys_90d_cnt,
        "ghostDeletedKeysWithTrafficCount": len(ghost_deleted_keys),
        "ghostDeletedKeysNames": [k.get("displayName") or k.get("uid", "")[:8] for k in ghost_deleted_keys],
        "firstPartyConsoleKeysCount": len(console_fp_keys),
        "exportedSaKeysCount": exported_sa_keys_cnt,
        "externalUsersCount": len(external_users),
        "externalUsers": external_users,
        "unattributedAuditBlindness": bool(unattributed_tokens > 0 or unattributed_calls > 0),
        "unattributedTokens": unattributed_tokens,
        "unattributedCalls": unattributed_calls,
        "publicEndpointsCount": len(public_endpoints),
        "publicEndpoints": public_endpoints,
        "nonCmekResourcesCount": len(non_cmek_resources),
        "nonCmekResources": non_cmek_resources[:10],
        "weekendCalls": weekend_calls,
        "weekendCostUsd": round(weekend_cost, 4),
        "costSpikeDaysCount": len(spike_days),
        "costSpikeDays": spike_days[:5],
        "adminMutationsCount": len(mutation_methods),
        "adminMutations": sorted(list(mutation_methods))[:15],
        "securityKeywords": sec_keywords
    }

    hb_existing = p.get("httpStatusBreakdown")
    if not isinstance(hb_existing, dict) or sum(int(v or 0) for v in hb_existing.values()) == 0:
        e5xx = int(p.get("errors5xx", 0) or 0)
        tot_r_all = int(p.get("totalRequests", 0) or 0)
        ok200 = max(0, tot_r_all - err_429_total - max(total_failed_or_denied, e5xx))
        e403 = max(0, total_failed_or_denied - e5xx)
        p["httpStatusBreakdown"] = {
            "200": ok200,
            "400": 0,
            "403": e403,
            "404": 0,
            "429": err_429_total,
            "500": e5xx,
            "other": 0
        }
    else:
        for k_hb in ("200", "400", "403", "404", "429", "500", "other"):
            hb_existing[k_hb] = int(hb_existing.get(k_hb, 0) or 0)

    p["avgLatencyMs"] = round(float(p.get("avgLatencyMs", 0.0) or 0.0), 1)


def enrich_single_project_telemetry(p: dict, scan_days: int = 30):
    """
    Normalizes and enriches a single project dict (works on both live scans and existing cached JSON payloads).
    """
    pid = p.get("projectId", "")
    pid_low = pid.lower()
    name_low = (p.get("name") or "").lower()
    now_dt = datetime.now(timezone.utc)
    days_window = max(1, int(p.get("scanDays", scan_days) or 30))

    ai_cost_val = _enrich_normalize_costs(p, days_window)
    has_ai_studio_key, ai_studio_keys_list = _enrich_apikeys_and_features(p, now_dt)
    notebooklm_feat, notebooklm_project_calls, colab_project_calls = _enrich_users_tools_and_models(p)
    re_groups = _enrich_data_residency(p, pid)
    _enrich_finops_extended(p, pid, ai_cost_val, days_window, re_groups)
    _enrich_agentspace_telemetry(p, pid)
    _enrich_ai_tools_summary(
        p, pid_low, name_low, has_ai_studio_key, ai_studio_keys_list,
        notebooklm_feat, notebooklm_project_calls, colab_project_calls
    )
    _enrich_ai_log_forensics(p)


