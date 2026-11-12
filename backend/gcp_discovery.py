def parse_model_armor_filter_config(filter_cfg: dict) -> dict:
    """Extracts human-readable filter settings from a Model Armor filterConfig object."""
    if not filter_cfg or not isinstance(filter_cfg, dict):
        return {
            "hasConfiguredFilters": False,
            "promptInjectionAndJailbreak": "NOT CONFIGURED",
            "raiFilters": [],
            "sdpDlp": "NOT CONFIGURED",
            "maliciousUri": "NOT CONFIGURED",
            "csam": "NOT CONFIGURED",
            "summaryBadges": []
        }

    badges = []
    # 1. Prompt Injection & Jailbreak
    pi_cfg = filter_cfg.get("piAndJailbreakFilterSettings", {})
    pi_enf = pi_cfg.get("filterEnforcement", "NOT CONFIGURED")
    pi_conf = pi_cfg.get("confidenceLevel", "")
    pi_str = f"{pi_enf}" + (f" ({pi_conf})" if pi_conf else "")
    if pi_enf and pi_enf != "NOT CONFIGURED":
        badges.append(f"Prompt Injection/Jailbreak: {pi_str}")

    # 2. RAI Filters (Hate Speech, Harassment, Sexually Explicit, Dangerous)
    rai_list = []
    for rf in filter_cfg.get("raiSettings", {}).get("raiFilters", []):
        f_type = rf.get("filterType", "")
        f_conf = rf.get("confidenceLevel", "")
        if f_type:
            rai_list.append({"filterType": f_type, "confidenceLevel": f_conf or "DEFAULT"})
            badges.append(f"RAI {f_type}: {f_conf or 'ON'}")

    # 3. Sensitive Data Protection (SDP / Cloud DLP)
    sdp_cfg = filter_cfg.get("sdpSettings", {})
    sdp_str = "NOT CONFIGURED"
    if sdp_cfg.get("basicConfig"):
        sdp_enf = sdp_cfg["basicConfig"].get("filterEnforcement", "ENABLED")
        sdp_str = f"Basic SDP ({sdp_enf})"
        badges.append(f"SDP/DLP: {sdp_str}")
    elif sdp_cfg.get("advancedConfig"):
        adv = sdp_cfg["advancedConfig"]
        insp = adv.get("inspectTemplate", "").split("/")[-1] or "Custom"
        deid = adv.get("deidentifyTemplate", "").split("/")[-1]
        sdp_str = f"Advanced DLP (Inspect: {insp}" + (f", De-ID: {deid})" if deid else ")")
        badges.append(f"SDP/DLP: {sdp_str}")

    # 4. Malicious URI Filter
    uri_cfg = filter_cfg.get("maliciousUriFilterSettings", {})
    uri_enf = uri_cfg.get("filterEnforcement", "NOT CONFIGURED")
    if uri_enf and uri_enf != "NOT CONFIGURED":
        badges.append(f"Malicious URI: {uri_enf}")

    # 5. CSAM Filter
    csam_cfg = filter_cfg.get("csamFilterSettings", {})
    csam_enf = csam_cfg.get("filterEnforcement", "DEFAULT_ON" if filter_cfg else "NOT CONFIGURED")

    has_any = bool(badges) or bool(rai_list)
    return {
        "hasConfiguredFilters": has_any,
        "promptInjectionAndJailbreak": pi_str,
        "raiFilters": rai_list,
        "sdpDlp": sdp_str,
        "maliciousUri": uri_enf,
        "csam": csam_enf,
        "summaryBadges": badges
    }


def inspect_model_armor_violation_logs(pid: str, token: str, days: int = 30) -> dict:
    """
    100% Read-Only inspection of Cloud Logging for Google Cloud Model Armor sanitization telemetry:
    Queries logName="projects/{pid}/logs/modelarmor.googleapis.com%2Fsanitize_operations"
    and Model Armor Data Access Audit logs to count total analyzed, flagged (MATCH_FOUND),
    blocked (INSPECT_AND_BLOCK), and breakdown by threat category (Prompt Injection/Jailbreak, RAI, SDP/PII, Malicious URI).
    """
    telemetry = {
        "logQueryExecuted": False,
        "totalSanitizeLogs": 0,
        "flaggedCount": 0,
        "blockedCount": 0,
        "passedCount": 0,
        "byCategory": {
            "promptInjectionAndJailbreak": 0,
            "sdpDlp": 0,
            "rai": 0,
            "maliciousUri": 0,
            "csam": 0
        },
        "recentViolations": []
    }
    start_iso = (datetime.now(timezone.utc) - timedelta(days=min(days, 30))).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_filter = (
        f'timestamp >= "{start_iso}" AND ('
        f'logName="projects/{pid}/logs/modelarmor.googleapis.com%2Fsanitize_operations" OR '
        f'protoPayload.serviceName="modelarmor.googleapis.com")'
    )
    payload = {
        "resourceNames": [f"projects/{pid}"],
        "filter": log_filter,
        "pageSize": 150,
        "orderBy": "timestamp desc"
    }
    st, data = gcp_api_post("https://logging.googleapis.com/v2/entries:list", token, payload, timeout=6)
    if st != 200 or not isinstance(data, dict):
        return telemetry
    entries = data.get("entries", [])
    telemetry["logQueryExecuted"] = True

    for entry in entries:
        telemetry["totalSanitizeLogs"] += 1
        ts = entry.get("timestamp", "")
        sev = entry.get("severity", "INFO")
        jp = entry.get("jsonPayload", {}) or {}
        pp = entry.get("protoPayload", {}) or {}
        raw_str = json.dumps(jp or pp).lower()

        matched_cats = []
        if "piandjailbreak" in raw_str or "prompt_injection" in raw_str or "jailbreak" in raw_str:
            if "match_found" in raw_str or '"matched"' in raw_str or "violation" in raw_str:
                telemetry["byCategory"]["promptInjectionAndJailbreak"] += 1
                matched_cats.append("Prompt Injection / Jailbreak")
        if "sdpsettings" in raw_str or "sdpfilterresult" in raw_str or "deidentify" in raw_str or "infotype" in raw_str:
            if "match_found" in raw_str or "infotype" in raw_str:
                telemetry["byCategory"]["sdpDlp"] += 1
                matched_cats.append("SDP / DLP (PII Leak)")
        if "raifilterresult" in raw_str or "hate_speech" in raw_str or "harassment" in raw_str or "dangerous" in raw_str or "sexually_explicit" in raw_str:
            if "match_found" in raw_str:
                telemetry["byCategory"]["rai"] += 1
                matched_cats.append("RAI Safety Violation")
        if "maliciousuri" in raw_str or "malicious_uri" in raw_str:
            if "match_found" in raw_str:
                telemetry["byCategory"]["maliciousUri"] += 1
                matched_cats.append("Malicious URI")

        is_flagged = ("match_found" in raw_str) or bool(matched_cats) or sev in ("WARNING", "ERROR", "CRITICAL")
        is_blocked = is_flagged and ("block" in raw_str or "denied" in raw_str or sev in ("ERROR", "CRITICAL"))

        if is_flagged:
            telemetry["flaggedCount"] += 1
            if is_blocked:
                telemetry["blockedCount"] += 1
            if len(telemetry["recentViolations"]) < 12:
                caller = pp.get("authenticationInfo", {}).get("principalEmail", "") or jp.get("principalEmail", "Runtime Agent / Gateway")
                method_name = pp.get("methodName", "") or jp.get("operationType", "SanitizeOperation")
                telemetry["recentViolations"].append({
                    "timestamp": ts,
                    "severity": sev,
                    "action": "BLOCKED" if is_blocked else "FLAGGED",
                    "categories": matched_cats or ["Policy Violation"],
                    "method": method_name.split(".")[-1],
                    "caller": caller
                })
        else:
            telemetry["passedCount"] += 1

    return telemetry


def inspect_model_armor(pid: str, token: str, api_enabled: bool, ma_metrics: dict, can_read_ma: bool = True, days: int = 30) -> dict:
    """
    100% Read-Only inspection of Google Cloud Model Armor (modelarmor.googleapis.com):
    - Checks global Floor Settings (/locations/global/floorSetting)
    - Checks regional & global Templates (/locations/{loc}/templates)
    - Inspects sanitize_operations & audit logs for Threat & Violations Telemetry
    - Combines with serviceruntime API usage metrics
    """
    ma_info = {
        "enabled": api_enabled or (ma_metrics.get("totalRequests", 0) > 0),
        "permissionGranted": can_read_ma,
        "status": "DISABLED",
        "statusLabel": "Not Enabled",
        "totalRequests": ma_metrics.get("totalRequests", 0),
        "sanitizeRequests": ma_metrics.get("sanitizeRequests", 0),
        "methodsCalled": sorted(list(ma_metrics.get("methods", set()))),
        "activeLocations": sorted(list(ma_metrics.get("locations", set()))),
        "floorSetting": None,
        "templates": [],
        "rawFloorSetting": None,
        "threatTelemetry": {
            "logQueryExecuted": False,
            "totalSanitizeLogs": 0,
            "flaggedCount": 0,
            "blockedCount": 0,
            "passedCount": 0,
            "byCategory": {
                "promptInjectionAndJailbreak": 0,
                "sdpDlp": 0,
                "rai": 0,
                "maliciousUri": 0,
                "csam": 0
            },
            "recentViolations": []
        }
    }

    if not ma_info["enabled"]:
        return ma_info

    if not can_read_ma:
        ma_info["threatTelemetry"] = inspect_model_armor_violation_logs(pid, token, days=days)
        ma_info["status"] = "PERMISSION_DENIED"
        ma_info["statusLabel"] = "🔒 API Enabled but Permission Denied (403) on Floor Settings / Templates"
        return ma_info

    # Run Threat Telemetry Log Query, Global Floor Setting GET, and Regional Template GETs all in parallel
    floor_url = f"https://modelarmor.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/global/floorSetting"
    template_locs = ["global", "eu", "europe-west1", "europe-west4", "us-central1", "us"]
    for extra_loc in ma_info["activeLocations"]:
        if extra_loc and extra_loc not in template_locs:
            template_locs.append(extra_loc)

    def fetch_loc_templates(loc: str):
        if loc == "global":
            url = f"https://modelarmor.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/global/templates"
        else:
            url = f"https://modelarmor.{loc}.rep.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/templates"
        st, d = gcp_api_get(url, token, timeout=5)
        if st == 200 and isinstance(d, dict):
            return loc, (d.get("modelArmorTemplates") or d.get("templates") or [])
        return loc, []

    with ThreadPoolExecutor(max_workers=min(10, 2 + len(template_locs))) as ex:
        fut_logs = ex.submit(inspect_model_armor_violation_logs, pid, token, days)
        fut_floor = ex.submit(gcp_api_get, floor_url, token, 6)
        fut_tmpls = [ex.submit(fetch_loc_templates, loc) for loc in template_locs]

        ma_info["threatTelemetry"] = fut_logs.result()
        f_status, f_data = fut_floor.result()
        tmpl_results = [f.result() for f in fut_tmpls]

    if f_status == 403:
        ma_info["permissionGranted"] = False
        ma_info["status"] = "PERMISSION_DENIED"
        ma_info["statusLabel"] = "🔒 API Enabled but Permission Denied (403) on Floor Settings / Templates"
        return ma_info

    if f_status == 200 and isinstance(f_data, dict) and f_data.get("name"):
        ma_info["rawFloorSetting"] = f_data
        enf_enabled = bool(f_data.get("enableFloorSettingEnforcement", False))
        integrated_svcs = f_data.get("integratedServices", [])
        ai_plat_cfg = f_data.get("aiPlatformFloorSetting", {})
        enf_mode = "INACTIVE"
        if ai_plat_cfg.get("inspectAndBlock"):
            enf_mode = "INSPECT_AND_BLOCK (Blocks Prompts/Responses)"
        elif ai_plat_cfg.get("inspectOnly"):
            enf_mode = "INSPECT_ONLY (Log/Audit Only)"
        elif enf_enabled:
            enf_mode = "ACTIVE"

        parsed_filters = parse_model_armor_filter_config(f_data.get("filterConfig", {}))
        ma_info["floorSetting"] = {
            "name": f_data.get("name"),
            "enforcementEnabled": enf_enabled,
            "enforcementMode": enf_mode,
            "integratedServices": integrated_svcs,
            "cloudLoggingEnabled": bool(ai_plat_cfg.get("enableCloudLogging", False)),
            "updateTime": f_data.get("updateTime"),
            "filters": parsed_filters
        }

    for loc, tmpl_list in tmpl_results:
        for t in tmpl_list:
            t_name = t.get("name", "")
            t_id = t_name.split("/")[-1] if t_name else "template"
            t_meta = t.get("templateMetadata", {})
            parsed_f = parse_model_armor_filter_config(t.get("filterConfig", {}))
            ma_info["templates"].append({
                "templateId": t_id,
                "fullName": t_name,
                "location": loc,
                "createTime": t.get("createTime"),
                "updateTime": t.get("updateTime"),
                "labels": t.get("labels", {}),
                "enforcementType": t_meta.get("enforcementType", "DEFAULT"),
                "logSanitizeOperations": bool(t_meta.get("logSanitizeOperations", False)),
                "customPromptErrorMessage": t_meta.get("customPromptSafetyErrorMessage", ""),
                "filters": parsed_f,
                "rawTemplate": t
            })

    # Determine status summary
    has_floor_policy = bool(
        ma_info["floorSetting"] and (
            ma_info["floorSetting"]["enforcementEnabled"] or
            ma_info["floorSetting"]["filters"]["hasConfiguredFilters"]
        )
    )
    has_templates = len(ma_info["templates"]) > 0

    if has_templates or has_floor_policy:
        ma_info["status"] = "CONFIGURED_ACTIVE"
        ma_info["statusLabel"] = f"Active ({len(ma_info['templates'])} Templates" + (", Floor Policy ON)" if has_floor_policy else ")")
    else:
        ma_info["status"] = "API_ENABLED_DEFAULT"
        ma_info["statusLabel"] = "API Enabled (0 Templates / Default Floor Setting not configured)"

    return ma_info


def _parse_vertex_core_resources(kind: str, loc: str, data: dict, pid: str, discovered: list[dict]) -> bool:
    if kind == "reasoningEngines":
        for re_obj in data.get("reasoningEngines", []):
            name = re_obj.get("name", "")
            rid = name.split("/")[-1] if name else ""
            spec = re_obj.get("spec", {})
            fw = spec.get("agentFramework") or "Google ADK / Reasoning Engine"
            py_ver = spec.get("packageSpec", {}).get("pythonVersion", "")
            discovered.append({
                "resourceType": "REASONING_ENGINE",
                "typeLabel": "🤖 ADK Agent / Reasoning Engine",
                "displayName": re_obj.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "framework": fw,
                "pythonVersion": py_ver,
                "description": re_obj.get("description", ""),
                "createTime": re_obj.get("createTime"),
                "updateTime": re_obj.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/reasoning-engines/locations/{loc}/reasoning-engines/{rid}?project={pid}",
                "details": f"Framework: {fw}" + (f" (Python {py_ver})" if py_ver else "") + (f" — {re_obj.get('description')}" if re_obj.get("description") else "")
            })
        return True
    if kind == "endpoints":
        for ep in data.get("endpoints", []):
            name = ep.get("name", "")
            rid = name.split("/")[-1] if name else ""
            dep_models = ep.get("deployedModels", [])
            dep_names = [dm.get("displayName") or dm.get("model", "").split("/")[-1] for dm in dep_models]
            discovered.append({
                "resourceType": "VERTEX_ENDPOINT",
                "typeLabel": "🚀 Vertex Online Endpoint",
                "displayName": ep.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "deployedModelsCount": len(dep_models),
                "deployedModels": dep_names,
                "createTime": ep.get("createTime"),
                "updateTime": ep.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/online-prediction/locations/{loc}/endpoints/{rid}?project={pid}",
                "details": f"{len(dep_models)} deployed models" + (f": {', '.join(dep_names[:3])}" if dep_names else " (Inactive / 0 nodes)")
            })
        return True
    if kind == "models":
        for md in data.get("models", []):
            name = md.get("name", "")
            rid = name.split("/")[-1] if name else ""
            discovered.append({
                "resourceType": "CUSTOM_MODEL",
                "typeLabel": "🧠 Registered Model (Model Registry)",
                "displayName": md.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "createTime": md.get("createTime"),
                "updateTime": md.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/models/locations/{loc}/models/{rid}?project={pid}",
                "details": f"Version {md.get('versionId', '1')}"
            })
        return True
    if kind == "ragCorpora":
        for rc in data.get("ragCorpora", []):
            name = rc.get("name", "")
            rid = name.split("/")[-1] if name else ""
            discovered.append({
                "resourceType": "RAG_CORPUS",
                "typeLabel": "📚 Vertex AI RAG Corpus",
                "displayName": rc.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "createTime": rc.get("createTime"),
                "updateTime": rc.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/rag/locations/{loc}/corpora/{rid}?project={pid}",
                "details": rc.get("description") or "RAG vector corpus active"
            })
        return True
    return False


def _parse_vertex_colab_and_jobs(kind: str, loc: str, data: dict, pid: str, discovered: list[dict]) -> bool:
    if kind == "notebookRuntimeTemplates":
        for nrt in data.get("notebookRuntimeTemplates", []):
            name = nrt.get("name", "")
            rid = name.split("/")[-1] if name else ""
            m_type = nrt.get("machineSpec", {}).get("machineType", "e2-standard-4")
            acc_type = nrt.get("machineSpec", {}).get("acceleratorType", "")
            acc_cnt = nrt.get("machineSpec", {}).get("acceleratorCount", 0)
            idle_to = nrt.get("idleShutdownConfig", {}).get("idleTimeout", "")
            euc = nrt.get("eucConfig", {}).get("eucDisabled", False)
            hw_label = f"{m_type}" + (f" + {acc_cnt}x {acc_type}" if acc_type else " (CPU)")
            discovered.append({
                "resourceType": "COLAB_ENTERPRISE_TEMPLATE",
                "typeLabel": "📓 Colab Enterprise Runtime Template",
                "displayName": nrt.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "machineType": m_type,
                "acceleratorType": acc_type,
                "acceleratorCount": acc_cnt,
                "idleTimeout": idle_to,
                "eucDisabled": euc,
                "createTime": nrt.get("createTime"),
                "updateTime": nrt.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/colab/runtime-templates?project={pid}",
                "details": f"Machine: {hw_label}" + (f" • Idle Shutdown: {idle_to}" if idle_to else "")
            })
        return True
    if kind == "notebookRuntimes":
        for nr in data.get("notebookRuntimes", []):
            name = nr.get("name", "")
            rid = name.split("/")[-1] if name else ""
            r_user = nr.get("runtimeUser", "")
            r_state = nr.get("runtimeState", "ACTIVE")
            h_state = nr.get("healthState", "")
            m_type = nr.get("machineSpec", {}).get("machineType", "")
            acc_type = nr.get("machineSpec", {}).get("acceleratorType", "")
            acc_cnt = nr.get("machineSpec", {}).get("acceleratorCount", 0)
            net_tags = nr.get("networkTags", [])
            hw_str = (f"{m_type}" + (f" + {acc_cnt}x {acc_type}" if acc_type else "")) if m_type else "Runtime"
            discovered.append({
                "resourceType": "COLAB_ENTERPRISE_RUNTIME",
                "typeLabel": "⚡ Colab Enterprise Active Runtime",
                "displayName": nr.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "runtimeUser": r_user,
                "runtimeState": r_state,
                "healthState": h_state,
                "machineType": m_type,
                "acceleratorType": acc_type,
                "acceleratorCount": acc_cnt,
                "networkTags": net_tags,
                "createTime": nr.get("createTime"),
                "updateTime": nr.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/colab/runtimes?project={pid}",
                "details": f"User: {r_user or 'N/A'} • Status: {r_state}" + (f" ({h_state})" if h_state else "") + f" • {hw_str}"
            })
        return True
    if kind == "notebookExecutionJobs":
        for job in data.get("notebookExecutionJobs", []):
            name = job.get("name", "")
            rid = name.split("/")[-1] if name else ""
            j_state = job.get("jobState", "JOB_STATE_UNSPECIFIED")
            gcs_uri = job.get("gcsNotebookSource", {}).get("uri", "") or job.get("gcsOutputUri", "")
            exec_user = job.get("executionUser", "") or job.get("serviceAccount", "")
            discovered.append({
                "resourceType": "COLAB_EXECUTION_JOB",
                "typeLabel": "🗓️ Colab Scheduled Execution Job",
                "displayName": job.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "jobState": j_state,
                "executionIdentity": exec_user,
                "gcsUri": gcs_uri,
                "createTime": job.get("createTime"),
                "updateTime": job.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/colab/execution-jobs?project={pid}",
                "details": f"Status: {j_state}" + (f" • Identity: {exec_user}" if exec_user else "") + (f" • GCS: {gcs_uri}" if gcs_uri else "")
            })
        return True
    if kind == "tuningJobs":
        for tj in data.get("tuningJobs", []):
            name = tj.get("name", "")
            rid = name.split("/")[-1] if name else ""
            base_m = tj.get("baseModel", "")
            t_state = tj.get("state", "JOB_STATE_UNSPECIFIED")
            tuned_m = tj.get("tunedModel", {}).get("model", "").split("/")[-1] if isinstance(tj.get("tunedModel"), dict) else ""
            discovered.append({
                "resourceType": "VERTEX_TUNING_JOB",
                "typeLabel": "🎯 Fine-Tuning LLM Job (SFT)",
                "displayName": tj.get("tunedModelDisplayName") or tj.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "baseModel": base_m,
                "jobState": t_state,
                "tunedModelId": tuned_m,
                "createTime": tj.get("createTime"),
                "updateTime": tj.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/generative/language/locations/{loc}/tuning?project={pid}",
                "details": f"Base: {base_m or 'Gemini'} • Status: {t_state}" + (f" • Tuned Model: {tuned_m}" if tuned_m else "")
            })
        return True
    if kind == "batchPredictionJobs":
        for bp in data.get("batchPredictionJobs", []):
            name = bp.get("name", "")
            rid = name.split("/")[-1] if name else ""
            b_state = bp.get("state", "JOB_STATE_UNSPECIFIED")
            model_name = (bp.get("model") or "").split("/")[-1]
            in_fmt = bp.get("inputConfig", {}).get("instancesFormat", "")
            out_uri = bp.get("outputInfo", {}).get("gcsOutputDirectory") or bp.get("outputInfo", {}).get("bigqueryOutputDataset") or ""
            discovered.append({
                "resourceType": "VERTEX_BATCH_JOB",
                "typeLabel": "📦 Batch Prediction LLM Job",
                "displayName": bp.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "model": model_name,
                "jobState": b_state,
                "outputUri": out_uri,
                "createTime": bp.get("createTime"),
                "updateTime": bp.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/batch-predictions/locations/{loc}/batch-predictions/{rid}?project={pid}",
                "details": f"Model: {model_name or 'N/A'} • Status: {b_state}" + (f" • Format: {in_fmt}" if in_fmt else "")
            })
        return True
    return False


def _parse_registry_and_vector_resources(kind: str, loc: str, data: dict, pid: str, discovered: list[dict]) -> bool:
    if kind == "vectorIndexes":
        for v_idx in data.get("indexes", []):
            name = v_idx.get("name", "")
            rid = name.split("/")[-1] if name else ""
            upd_method = v_idx.get("indexUpdateMethod", "BATCH_UPDATE")
            dep_cnt = len(v_idx.get("deployedIndexes", []))
            v_cnt = v_idx.get("indexStats", {}).get("vectorsCount", 0)
            s_cnt = v_idx.get("indexStats", {}).get("shardsCount", 0)
            discovered.append({
                "resourceType": "VECTOR_SEARCH_INDEX",
                "typeLabel": "🧭 Vertex Vector Search Index",
                "displayName": v_idx.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "updateMethod": upd_method,
                "vectorsCount": v_cnt,
                "shardsCount": s_cnt,
                "deployedCount": dep_cnt,
                "createTime": v_idx.get("createTime"),
                "updateTime": v_idx.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/matching-engine/indexes?project={pid}",
                "details": f"Update: {upd_method} • Vectors: {v_cnt} ({s_cnt} shards) • {dep_cnt} active deployments"
            })
        return True
    if kind == "vectorIndexEndpoints":
        for v_ep in data.get("indexEndpoints", []):
            name = v_ep.get("name", "")
            rid = name.split("/")[-1] if name else ""
            dep_idxs = v_ep.get("deployedIndexes", [])
            pub_ep = v_ep.get("publicEndpointDomainName", "")
            vpc_net = v_ep.get("network", "")
            psc_cfg = v_ep.get("privateServiceConnectConfig", {}).get("enablePrivateServiceConnect", False)
            net_mode = "Public Endpoint" if pub_ep else ("PSC Private" if psc_cfg else ("VPC Peering" if vpc_net else "Standard"))
            discovered.append({
                "resourceType": "VECTOR_SEARCH_ENDPOINT",
                "typeLabel": "📡 Vector Search Index Endpoint",
                "displayName": v_ep.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "networkMode": net_mode,
                "deployedIndexesCount": len(dep_idxs),
                "createTime": v_ep.get("createTime"),
                "updateTime": v_ep.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/matching-engine/index-endpoints?project={pid}",
                "details": f"Network: {net_mode} • {len(dep_idxs)} deployed indexes"
            })
        return True
    if kind == "agentRegistryAgents":
        for ar_ag in data.get("agents", []):
            name = ar_ag.get("name", "")
            rid = name.split("/")[-1] if name else ""
            proto = ar_ag.get("protocol") or ar_ag.get("type") or "A2A / ADK"
            ver = ar_ag.get("version", "")
            discovered.append({
                "resourceType": "AGENT_REGISTRY_AGENT",
                "typeLabel": "🗂️ Agent Registry (Governed Agent)",
                "displayName": ar_ag.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "protocol": proto,
                "version": ver,
                "createTime": ar_ag.get("createTime"),
                "updateTime": ar_ag.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/agent-builder?project={pid}",
                "details": f"Protocol: {proto}" + (f" (v{ver})" if ver else "") + (f" — {ar_ag.get('description')}" if ar_ag.get("description") else "")
            })
        return True
    if kind == "agentRegistryMcpServers":
        for mcp_s in data.get("mcpServers", []):
            name = mcp_s.get("name", "")
            rid = name.split("/")[-1] if name else ""
            tools_cnt = len(mcp_s.get("tools", []))
            uri = mcp_s.get("uri") or mcp_s.get("endpoint") or ""
            discovered.append({
                "resourceType": "AGENT_REGISTRY_MCP",
                "typeLabel": "🔌 Agent Registry MCP Server",
                "displayName": mcp_s.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "toolsCount": tools_cnt,
                "endpointUri": uri,
                "createTime": mcp_s.get("createTime"),
                "updateTime": mcp_s.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/agent-builder?project={pid}",
                "details": f"{tools_cnt} registered MCP Tools" + (f" • URI: {uri}" if uri else "")
            })
        return True
    if kind == "dlpInspectTemplates":
        for dlp_t in data.get("inspectTemplates", []):
            name = dlp_t.get("name", "")
            rid = name.split("/")[-1] if name else ""
            info_types = [it.get("name", "") for it in dlp_t.get("inspectConfig", {}).get("infoTypes", []) if it.get("name")]
            discovered.append({
                "resourceType": "DLP_INSPECT_TEMPLATE",
                "typeLabel": "🛡️ Sensitive Data Protection (DLP Template)",
                "displayName": dlp_t.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "infoTypesCount": len(info_types),
                "infoTypes": info_types[:8],
                "createTime": dlp_t.get("createTime"),
                "updateTime": dlp_t.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/security/sensitive-data-protection/landing/configuration/templates/inspect?project={pid}",
                "details": f"{len(info_types)} inspected InfoTypes" + (f": {', '.join(info_types[:5])}" if info_types else "")
            })
        return True
    return False


def _parse_discovery_engine_and_notebooks(kind: str, loc: str, data: dict, pid: str, discovered: list[dict]) -> bool:
    if kind == "discoveryEngines":
        for eng in data.get("engines", []):
            name = eng.get("name", "")
            rid = name.split("/")[-1] if name else ""
            sol_type = (eng.get("solutionType") or "").replace("SOLUTION_TYPE_", "")
            app_type = (eng.get("appType") or "").replace("APP_TYPE_", "")
            ind_vert = (eng.get("industryVertical") or "").replace("INDUSTRY_VERTICAL_", "")
            ds_ids = eng.get("dataStoreIds", [])
            search_tier = (eng.get("searchEngineConfig", {}).get("searchTier") or "").replace("SEARCH_TIER_", "")
            add_ons = [a.replace("SEARCH_ADD_ON_", "") for a in eng.get("searchEngineConfig", {}).get("searchAddOns", [])]
            company = eng.get("commonConfig", {}).get("companyName", "")
            is_agentspace = app_type == "INTRANET" or "ENTERPRISE" in search_tier or "LLM" in add_ons or len(ds_ids) > 1
            type_label = "✨ Google Agentspace / Enterprise App" if is_agentspace else "🔍 Discovery Engine App"
            details_parts = []
            if app_type:
                details_parts.append(f"App: {app_type}")
            elif sol_type:
                details_parts.append(f"Type: {sol_type}")
            if search_tier:
                details_parts.append(f"Tier: {search_tier}")
            if add_ons:
                details_parts.append(f"Add-On: {', '.join(add_ons)}")
            if ds_ids:
                details_parts.append(f"{len(ds_ids)} linked DataStores")
            if company:
                details_parts.append(f"Org: {company}")
            discovered.append({
                "resourceType": "AGENTSPACE_APP",
                "typeLabel": type_label,
                "displayName": eng.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "solutionType": sol_type,
                "appType": app_type,
                "industryVertical": ind_vert,
                "searchTier": search_tier,
                "searchAddOns": add_ons,
                "dataStoreIds": ds_ids,
                "companyName": company,
                "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/engines?project={pid}",
                "details": " • ".join(details_parts) if details_parts else f"App: {sol_type or 'Enterprise'}",
                "createTime": eng.get("createTime"),
                "updateTime": eng.get("updateTime")
            })
        return True
    if kind == "discoveryDataStores":
        for ds in data.get("dataStores", []):
            name = ds.get("name", "")
            rid = name.split("/")[-1] if name else ""
            c_cfg = (ds.get("contentConfig") or "").replace("CONTENT_CONFIG_", "")
            sol_types = [s.replace("SOLUTION_TYPE_", "") for s in ds.get("solutionTypes", [])]
            doc_cfg = ds.get("documentProcessingConfig", {})
            parser_name = (doc_cfg.get("defaultParsingConfig") or {}).keys()
            parser_label = "Layout/OCR Parser" if "layoutParsingConfig" in parser_name or "ocrParsingConfig" in parser_name else ("Digital Parser" if "digitalParsingConfig" in parser_name else "")
            discovered.append({
                "resourceType": "AGENTSPACE_DATASTORE",
                "typeLabel": "🗄️ Agentspace / Discovery DataStore",
                "displayName": ds.get("displayName") or rid,
                "resourceId": rid,
                "location": loc,
                "contentConfig": c_cfg,
                "solutionTypes": sol_types,
                "createTime": ds.get("createTime"),
                "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/data-stores?project={pid}",
                "details": f"Content: {c_cfg or 'Unstructured'}" + (f" • {', '.join(sol_types)}" if sol_types else "") + (f" • {parser_label}" if parser_label else "")
            })
        return True
    if kind == "notebooks":
        for nb in data.get("instances", []):
            name = nb.get("name", "")
            rid = name.split("/")[-1] if name else ""
            parts = name.split("/")
            nb_loc = parts[3] if len(parts) > 3 else loc
            m_type = nb.get("gceSetup", {}).get("machineType", "").split("/")[-1]
            state = nb.get("state", "ACTIVE")
            discovered.append({
                "resourceType": "WORKBENCH_NOTEBOOK",
                "typeLabel": "💻 Vertex AI Workbench Instance",
                "displayName": rid,
                "resourceId": rid,
                "location": nb_loc,
                "state": state,
                "machineType": m_type,
                "createTime": nb.get("createTime"),
                "updateTime": nb.get("updateTime"),
                "consoleUrl": f"https://console.cloud.google.com/vertex-ai/workbench/instances?project={pid}",
                "details": f"Status: {state}" + (f" • Machine: {m_type}" if m_type else "")
            })
        return True
    return False


def _dispatch_discovered_resource_batch(
    kind: str,
    loc: str,
    data: dict,
    pid: str,
    discovered: list[dict],
    df_agents_to_enrich: list[tuple[str, dict]]
) -> None:
    if _parse_vertex_core_resources(kind, loc, data, pid, discovered):
        return
    if _parse_vertex_colab_and_jobs(kind, loc, data, pid, discovered):
        return
    if _parse_registry_and_vector_resources(kind, loc, data, pid, discovered):
        return
    if kind == "dialogflowAgents":
        for ag in data.get("agents", []):
            df_agents_to_enrich.append((loc, ag))
        return
    _parse_discovery_engine_and_notebooks(kind, loc, data, pid, discovered)


def _enrich_single_df_agent(item: tuple[str, dict], pid: str, token: str) -> dict:
    loc, ag = item
    ag_name = ag.get("name", "")
    ag_id = ag_name.split("/")[-1] if ag_name else ""
    lang = ag.get("defaultLanguageCode", "it")
    host = "dialogflow.googleapis.com" if loc == "global" else f"{loc}-dialogflow.googleapis.com"

    llm_model = ""
    playbooks_names = []
    flows_count = 0
    webhooks_count = 0

    sub_urls = [
        ("genSettings", f"https://{host}/v3/{ag_name}/generativeSettings?languageCode={urllib.parse.quote(lang)}"),
        ("playbooks", f"https://{host}/v3/{ag_name}/playbooks"),
        ("flows", f"https://{host}/v3/{ag_name}/flows"),
        ("webhooks", f"https://{host}/v3/{ag_name}/webhooks")
    ]
    with ThreadPoolExecutor(max_workers=4) as sub_ex:
        for s_kind, (s_st, s_data) in zip([u[0] for u in sub_urls], sub_ex.map(lambda u: gcp_api_get(u[1], token, timeout=4, user_project=pid), sub_urls)):
            if s_st != 200 or not isinstance(s_data, dict):
                continue
            if s_kind == "genSettings":
                llm_model = s_data.get("llmModelSettings", {}).get("model", "")
            elif s_kind == "playbooks":
                for pb in s_data.get("playbooks", []):
                    pb_disp = pb.get("displayName") or pb.get("name", "").split("/")[-1]
                    if pb_disp:
                        playbooks_names.append(pb_disp)
            elif s_kind == "flows":
                flows_count = len(s_data.get("flows", []))
            elif s_kind == "webhooks":
                webhooks_count = len(s_data.get("webhooks", []))

    stt_enabled = ag.get("speechToTextSettings", {}).get("enableSpeechAdaptation", False)
    tts_map = ag.get("textToSpeechSettings", {}).get("synthesizeSpeechConfigs", {})
    tts_voice = ""
    if isinstance(tts_map, dict) and lang in tts_map:
        tts_voice = tts_map[lang].get("voice", {}).get("name", "")

    details_parts = [f"Language: {lang}"]
    if llm_model:
        details_parts.append(f"LLM: {llm_model}")
    if playbooks_names:
        details_parts.append(f"{len(playbooks_names)} AI Playbooks ({', '.join(playbooks_names[:4])})")
    if flows_count:
        details_parts.append(f"{flows_count} Flows")
    if webhooks_count:
        details_parts.append(f"{webhooks_count} Webhooks")
    if stt_enabled or tts_voice:
        details_parts.append(f"STT/TTS voice ({tts_voice or 'active'})")

    return {
        "resourceType": "DIALOGFLOW_CX_AGENT",
        "typeLabel": "💬 Dialogflow CX Generative Agent",
        "displayName": ag.get("displayName") or ag_id,
        "resourceId": ag_id,
        "location": loc,
        "llmModel": llm_model,
        "playbooks": playbooks_names,
        "consoleUrl": f"https://conversational-agents.cloud.google.com/projects/{pid}/locations/{loc}/agents/{ag_id}",
        "details": " • ".join(details_parts),
        "createTime": None,
        "updateTime": None
    }


def _merge_deep_gemini_enterprise_resources(pid: str, token: str, discovered: list[dict]) -> None:
    try:
        deep_ge = discover_gemini_enterprise_deep(pid, token, ["global", "eu", "us"])
        existing_app_map = {
            r["resourceId"]: r
            for r in discovered
            if r.get("resourceType") == "AGENTSPACE_APP" and r.get("resourceId")
        }
        lic_pools_by_loc = deep_ge.get("licensePools") or {}
        for eng in (deep_ge.get("engines") or []):
            e_id = (eng.get("name") or "").split("/")[-1]
            if e_id and e_id in existing_app_map:
                app_ref = existing_app_map[e_id]
                e_loc = app_ref.get("location") or eng.get("_location") or "eu"
                for k_src, k_dst in [
                    ("_assistants", "assistants"),
                    ("_agents", "agents"),
                    ("_agentOwners", "agentOwners"),
                    ("_agentGroups", "agentGroups"),
                    ("_widgetConfig", "widgetConfig"),
                    ("_servingConfigs", "servingConfigs"),
                ]:
                    if eng.get(k_src) is not None:
                        app_ref[k_dst] = eng[k_src]
                if eng.get("_agents") is not None:
                    app_ref["agentsCount"] = len(eng["_agents"])
                if eng.get("_agentOwners") is not None:
                    app_ref["agentOwnersCount"] = len(eng["_agentOwners"])
                if eng.get("_sessionsCount") is not None:
                    app_ref["sessionsCount"] = eng["_sessionsCount"]
                    app_ref["sessions"] = eng.get("_sessions") or []
                if eng.get("_licensePool") or lic_pools_by_loc.get(e_loc):
                    app_ref["licensePool"] = eng.get("_licensePool") or lic_pools_by_loc.get(e_loc) or {}
        for conn in (deep_ge.get("connectors") or []):
            col_id = conn.get("collectionId") or ""
            discovered.append({
                "resourceType": "GEMINI_ENTERPRISE_CONNECTOR",
                "typeLabel": "🔌 Gemini Enterprise Connector (DataConnector)",
                "displayName": f"{conn.get('dataSource') or col_id} ({col_id})",
                "resourceId": col_id,
                "collectionId": col_id,
                "location": conn.get("location") or "eu",
                "dataSource": conn.get("dataSource") or "",
                "state": conn.get("state") or "ACTIVE",
                "refreshInterval": conn.get("refreshInterval") or "",
                "syncMode": conn.get("syncMode") or "",
                "params": conn.get("params") or {},
                "entities": conn.get("entities") or [],
                "entitiesCount": conn.get("entitiesCount", 0),
                "aclEnabled": conn.get("aclEnabled", False),
                "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/data-stores?project={pid}",
                "details": f"DataSource: {conn.get('dataSource') or 'Connector'} • Status: {conn.get('state') or 'ACTIVE'} • {conn.get('entitiesCount', 0)} entities",
                "createTime": conn.get("createTime"),
                "updateTime": conn.get("updateTime")
            })
        for ag in (deep_ge.get("agents") or []):
            ag_id = ag.get("agentId") or ""
            if ag_id:
                discovered.append({
                    "resourceType": "GEMINI_ENTERPRISE_ASSISTANT_AGENT",
                    "typeLabel": "🤖 Gemini Enterprise Agent (Assistant Agent)",
                    "displayName": ag.get("displayName") or ag_id,
                    "resourceId": ag_id,
                    "engineId": ag.get("engineId") or "",
                    "engineName": ag.get("engineName") or "",
                    "location": ag.get("location") or "eu",
                    "state": ag.get("state") or "ENABLED",
                    "agentType": ag.get("agentType") or "CUSTOM",
                    "llmModel": ag.get("llmModel") or "",
                    "creatorEmail": ag.get("creatorEmail") or "",
                    "owners": ag.get("owners") or [],
                    "iamGroups": ag.get("iamGroups") or [],
                    "sharingScope": ag.get("sharingScope") or "",
                    "instructionPreview": ag.get("instructionPreview") or "",
                    "tools": ag.get("tools") or [],
                    "dataStoreSpecs": ag.get("dataStoreSpecs") or [],
                    "starterPrompts": ag.get("starterPrompts") or [],
                    "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/locations/{ag.get('location') or 'eu'}/engines/{ag.get('engineId') or ''}/configurations?project={pid}",
                    "details": ag.get("description") or f"Engine: {ag.get('engineId') or 'default'} • Status: {ag.get('state') or 'ENABLED'}",
                    "createTime": ag.get("createTime"),
                    "updateTime": ag.get("updateTime")
                })
    except (OSError, ValueError, KeyError, TypeError) as _ge_exc:
        logging.debug("Gemini Enterprise discovery skipped for %s: %s", pid, _ge_exc)


def discover_active_vertex_resources(pid: str, token: str, enabled_services: set[str], active_locations: set[str]) -> list[dict]:
    """
    100% Read-Only discovery of deployed Vertex AI, Dialogflow CX & Agentspace resources on active projects:
    - Vertex AI Reasoning Engines (Google ADK / LangChain Agents)
    - Vertex AI Custom Online Endpoints & Model Garden Deployments
    - Vertex AI RAG Corpora
    - Vertex AI / Colab Enterprise Notebook Runtime Templates
    - Dialogflow CX / Conversational Agents (with Playbooks, Flows, Webhooks & LLM Generative Settings)
    - Google Agentspace / Discovery Engine Apps & DataStores (global, eu, us)
    - Vertex AI Workbench Notebooks
    """
    discovered = []
    tasks = []

    # Regions to check for Vertex AI resources
    vertex_locs = ["europe-west8", "europe-west1", "europe-west4", "us-central1"]
    for loc in active_locations:
        if loc and loc not in ("global", "eu", "us") and loc not in vertex_locs:
            vertex_locs.append(loc)

    if "aiplatform.googleapis.com" in enabled_services:
        for loc in vertex_locs[:5]:
            tasks.append(("reasoningEngines", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/reasoningEngines"))
            tasks.append(("endpoints", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/endpoints"))
            tasks.append(("models", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/models"))
            tasks.append(("ragCorpora", loc, f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{urllib.parse.quote(pid)}/locations/{loc}/ragCorpora"))
            tasks.append(("notebookRuntimeTemplates", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/notebookRuntimeTemplates"))
            tasks.append(("notebookRuntimes", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/notebookRuntimes"))
            tasks.append(("notebookExecutionJobs", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/notebookExecutionJobs"))
            tasks.append(("tuningJobs", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/tuningJobs"))
            tasks.append(("batchPredictionJobs", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/batchPredictionJobs"))
            tasks.append(("vectorIndexes", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/indexes"))
            tasks.append(("vectorIndexEndpoints", loc, f"https://{loc}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/indexEndpoints"))

    if "agentregistry.googleapis.com" in enabled_services:
        for loc in ["global", "us-central1", "europe-west1"]:
            tasks.append(("agentRegistryAgents", loc, f"https://agentregistry.googleapis.com/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}/agents"))
            tasks.append(("agentRegistryMcpServers", loc, f"https://agentregistry.googleapis.com/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}/mcpServers"))

    if "dlp.googleapis.com" in enabled_services:
        tasks.append(("dlpInspectTemplates", "global", f"https://dlp.googleapis.com/v2/projects/{urllib.parse.quote(pid)}/locations/global/inspectTemplates"))

    if "dialogflow.googleapis.com" in enabled_services or "ces.googleapis.com" in enabled_services:
        df_locs = ["eu", "global", "europe-west1", "europe-west3", "europe-west4", "europe-west8", "us-central1", "us"]
        for loc in active_locations:
            if loc and loc not in df_locs:
                df_locs.append(loc)
        for loc in df_locs[:8]:
            host = "dialogflow.googleapis.com" if loc == "global" else f"{loc}-dialogflow.googleapis.com"
            tasks.append(("dialogflowAgents", loc, f"https://{host}/v3/projects/{urllib.parse.quote(pid)}/locations/{loc}/agents"))

    if "discoveryengine.googleapis.com" in enabled_services:
        for loc in ["global", "eu", "us"]:
            host = f"{loc}-discoveryengine.googleapis.com" if loc in ("eu", "us") else "discoveryengine.googleapis.com"
            tasks.append(("discoveryEngines", loc, f"https://{host}/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}/collections/default_collection/engines"))
            tasks.append(("discoveryDataStores", loc, f"https://{host}/v1/projects/{urllib.parse.quote(pid)}/locations/{loc}/collections/default_collection/dataStores"))

    if "notebooks.googleapis.com" in enabled_services:
        tasks.append(("notebooks", "all", f"https://notebooks.googleapis.com/v2/projects/{urllib.parse.quote(pid)}/locations/-/instances"))

    if not tasks:
        return discovered

    df_agents_to_enrich = []
    with ThreadPoolExecutor(max_workers=min(24, len(tasks))) as ex:
        for kind, loc, st, data in ex.map(lambda t: (t[0], t[1], *gcp_api_get(t[2], token, timeout=5, user_project=pid)), tasks):
            if st != 200 or not isinstance(data, dict):
                continue
            _dispatch_discovered_resource_batch(kind, loc, data, pid, discovered, df_agents_to_enrich)

    if df_agents_to_enrich:
        with ThreadPoolExecutor(max_workers=min(8, len(df_agents_to_enrich))) as df_ex:
            for enriched_ag in df_ex.map(lambda item: _enrich_single_df_agent(item, pid, token), df_agents_to_enrich):
                discovered.append(enriched_ag)

    if "discoveryengine.googleapis.com" in enabled_services:
        _merge_deep_gemini_enterprise_resources(pid, token, discovered)

    return discovered


def build_project_permissions_summary(
    b_status: int,
    billing_enabled: bool,
    ba_granted: bool,
    su_status: int,
    granted_perms: set[str],
    k_status: int,
    sa_status: int,
    enabled_ai_apis_count: int = 0,
    api_keys_count: int = 0,
    sa_count: int = 0
) -> dict:
    effective_perms = set(granted_perms)
    if su_status == 200:
        effective_perms.add("serviceusage.services.list")
    if k_status == 200:
        effective_perms.add("serviceusage.apiKeys.list")
    if sa_status == 200:
        effective_perms.add("iam.serviceAccounts.list")

    iam_granted_list = [p for p in PROJECT_IAM_PERMISSIONS_TO_CHECK if p in effective_perms]
    iam_missing_list = [p for p in PROJECT_IAM_PERMISSIONS_TO_CHECK if p not in effective_perms]
    iam_granted_count = len(iam_granted_list)
    iam_total_count = len(PROJECT_IAM_PERMISSIONS_TO_CHECK)

    can_billing_info = (b_status == 200)
    can_billing_costs = bool(ba_granted)
    can_service_usage = ("serviceusage.services.list" in effective_perms)
    can_monitoring = ("monitoring.timeSeries.list" in effective_perms)
    can_api_keys = ("serviceusage.apiKeys.list" in effective_perms)
    can_service_accounts = ("iam.serviceAccounts.list" in effective_perms)

    res_perm_keys = [
        "aiplatform.endpoints.list",
        "aiplatform.reasoningEngines.list",
        "dialogflow.agents.list",
        "discoveryengine.engines.list"
    ]
    res_granted = [p for p in res_perm_keys if p in effective_perms]
    res_missing = [p for p in res_perm_keys if p not in effective_perms]
    can_ai_resources = (len(res_granted) > 0)
    ai_resources_status = "GRANTED" if len(res_granted) == len(res_perm_keys) else ("PARTIAL" if res_granted else "DENIED")

    ma_perm_keys = ["modelarmor.floorSettings.get", "modelarmor.templates.list"]
    ma_granted = [p for p in ma_perm_keys if p in effective_perms]
    can_model_armor = (len(ma_granted) > 0)
    model_armor_status = "GRANTED" if len(ma_granted) == len(ma_perm_keys) else ("PARTIAL" if ma_granted else "DENIED")

    missing_summary = []
    if not can_billing_info:
        missing_summary.append("Project Billing Status (403)")
    if billing_enabled and not can_billing_costs:
        missing_summary.append("Billing Account Invoice (Monitoring Estimate Only)")
    if not can_service_usage:
        missing_summary.append("Active API List / ServiceUsage (403)")
    if not can_monitoring:
        missing_summary.append("Metrics, Calls, Models, Tokens & Costs (403)")
    if ai_resources_status == "DENIED":
        missing_summary.append("AI Resources / Deployed Agents Inspection (403)")
    elif ai_resources_status == "PARTIAL":
        missing_summary.append(f"Partial AI Resources ({len(res_granted)}/4)")
    if model_armor_status == "DENIED":
        missing_summary.append("Model Armor Configurations & Templates (403)")
    if not can_api_keys:
        missing_summary.append("API Key Names (403)")
    if not can_service_accounts:
        missing_summary.append("IAM Service Accounts List (403)")

    if iam_granted_count == iam_total_count:
        access_level = "FULL"
        badge_label = f"🟢 Project Permissions OK ({iam_granted_count}/{iam_total_count})"
    elif can_monitoring:
        access_level = "PARTIAL"
        badge_label = f"⚠️ Partial Permissions ({iam_granted_count}/{iam_total_count})"
    else:
        access_level = "NO_MONITORING_ACCESS"
        badge_label = f"🔒 Access Denied to Metrics/Costs ({iam_granted_count}/{iam_total_count})"

    areas = {
        "billingInfo": {
            "id": "billingInfo",
            "title": "Project Billing Status",
            "label": "Project Billing Status",
            "granted": can_billing_info,
            "partial": False,
            "status": "GRANTED" if can_billing_info else "DENIED",
            "statusLabel": "✅ OK (200)" if can_billing_info else f"🔒 Denied ({b_status or 403})",
            "httpCode": b_status or 403,
            "permission": "billing.resourceAssociations.list",
            "requiredRole": "roles/viewer (billing.resourceAssociations.list)",
            "detail": (
                "Billing linked and visible" if (can_billing_info and billing_enabled)
                else ("No Billing linked" if can_billing_info else "Permission Denied (403) to read billingInfo")
            )
        },
        "billingCosts": {
            "id": "billingCosts",
            "title": "Actual Billing Account Invoices",
            "label": "Actual Billing Account Invoices",
            "granted": can_billing_costs,
            "partial": not can_billing_costs,
            "status": "GRANTED" if can_billing_costs else "ESTIMATED_ONLY",
            "statusLabel": "✅ OK (200)" if can_billing_costs else "📊 From Metrics",
            "httpCode": 200 if can_billing_costs else 403,
            "permission": "billing.accounts.get / getSpendingInformation (roles/billing.viewer on Billing Account)",
            "requiredRole": "roles/billing.viewer (su Billing Account)",
            "detail": (
                "Direct Billing Account access enabled"
                if can_billing_costs
                else "🔒 Missing permission on the Billing Account (403) — Costs calculated from Tokens & Cloud Monitoring Metrics"
            )
        },
        "serviceUsage": {
            "id": "serviceUsage",
            "title": "Enabled APIs & Services",
            "label": "Enabled APIs & Services",
            "granted": can_service_usage,
            "partial": False,
            "status": "GRANTED" if can_service_usage else "DENIED",
            "statusLabel": "✅ OK (200)" if can_service_usage else "🔒 Denied (403)",
            "httpCode": 200 if can_service_usage else 403,
            "permission": "serviceusage.services.list",
            "requiredRole": "roles/serviceusage.serviceUsageViewer",
            "detail": (
                f"Visible ({enabled_ai_apis_count} active AI APIs)"
                if can_service_usage
                else "🔒 Permission Denied (403): unable to verify which APIs are enabled on the project"
            )
        },
        "monitoring": {
            "id": "monitoring",
            "title": "Calls, Models, Tokens & Costs",
            "label": "Calls, Models, Tokens & Costs",
            "granted": can_monitoring,
            "partial": False,
            "status": "GRANTED" if can_monitoring else "DENIED",
            "statusLabel": "✅ OK (200)" if can_monitoring else "🔒 Denied (403)",
            "httpCode": 200 if can_monitoring else 403,
            "permission": "monitoring.timeSeries.list",
            "requiredRole": "roles/monitoring.viewer",
            "detail": (
                "Visible: full read of API calls, LLM models, tokens and cost estimates"
                if can_monitoring
                else "🔒 Permission Denied (403): unable to read calls, models, tokens and costs from Cloud Monitoring"
            )
        },
        "aiResources": {
            "id": "aiResources",
            "title": "Deployed AI Resources (Vertex / Dialogflow / Agentspace)",
            "label": "Deployed AI Resources (Vertex / Dialogflow / Agentspace)",
            "granted": can_ai_resources,
            "partial": ai_resources_status == "PARTIAL",
            "status": ai_resources_status,
            "statusLabel": "✅ OK (4/4)" if ai_resources_status == "GRANTED" else (f"⚠️ Partial ({len(res_granted)}/4)" if ai_resources_status == "PARTIAL" else "🔒 Denied (403)"),
            "httpCode": 200 if ai_resources_status == "GRANTED" else (206 if ai_resources_status == "PARTIAL" else 403),
            "permission": "aiplatform.endpoints.list, aiplatform.reasoningEngines.list, dialogflow.agents.list, discoveryengine.engines.list",
            "requiredRole": "roles/aiplatform.viewer, roles/dialogflow.reader, roles/discoveryengine.viewer",
            "grantedSubPermissions": res_granted,
            "missingSubPermissions": res_missing,
            "detail": (
                "Visible (4/4 permissions for Vertex Endpoints, Reasoning Engines, Dialogflow CX and Agentspace)"
                if ai_resources_status == "GRANTED"
                else (
                    f"Partial ({len(res_granted)}/4 permissions granted; missing: {', '.join(res_missing)})"
                    if ai_resources_status == "PARTIAL"
                    else "🔒 Permission Denied (403): unable to inspect Vertex Endpoints, Dialogflow CX Agents or Agentspace Apps"
                )
            )
        },
        "modelArmor": {
            "id": "modelArmor",
            "title": "Model Armor Configurations & Templates",
            "label": "Model Armor Configurations & Templates",
            "granted": can_model_armor,
            "partial": False,
            "status": model_armor_status,
            "statusLabel": "✅ OK (200)" if model_armor_status == "GRANTED" else "🔒 Denied (403)",
            "httpCode": 200 if model_armor_status == "GRANTED" else 403,
            "permission": "modelarmor.floorSettings.get, modelarmor.templates.list",
            "requiredRole": "roles/modelarmor.viewer",
            "detail": (
                "Visible: reading Floor Settings and Model Armor Templates is allowed"
                if model_armor_status == "GRANTED"
                else "🔒 Permission Denied (403): unable to read Floor Settings and Model Armor Templates"
            )
        },
        "apiKeys": {
            "id": "apiKeys",
            "title": "API Key Names Inventory",
            "label": "API Key Names Inventory",
            "granted": can_api_keys,
            "partial": False,
            "status": "GRANTED" if can_api_keys else "DENIED",
            "statusLabel": "✅ OK (200)" if can_api_keys else "🔒 Denied (403)",
            "httpCode": 200 if can_api_keys else 403,
            "permission": "serviceusage.apiKeys.list",
            "requiredRole": "roles/serviceusage.apiKeysViewer",
            "detail": (
                f"Visible ({api_keys_count} API Keys listed)"
                if can_api_keys
                else "🔒 Permission Denied (403): unable to read API Key names (any traffic appears only as UID)"
            )
        },
        "serviceAccounts": {
            "id": "serviceAccounts",
            "title": "IAM Service Accounts Inventory",
            "label": "IAM Service Accounts Inventory",
            "granted": can_service_accounts,
            "partial": False,
            "status": "GRANTED" if can_service_accounts else "DENIED",
            "statusLabel": "✅ OK (200)" if can_service_accounts else "🔒 Denied (403)",
            "httpCode": 200 if can_service_accounts else 403,
            "permission": "iam.serviceAccounts.list",
            "requiredRole": "roles/iam.securityReviewer (iam.serviceAccounts.list)",
            "detail": (
                f"Visible ({sa_count} Service Accounts listed)"
                if can_service_accounts
                else "🔒 Permission Denied (403): unable to read the project's IAM Service Accounts list"
            )
        }
    }

    return {
        "accessLevel": access_level,
        "badgeLabel": badge_label,
        "iamGrantedCount": iam_granted_count,
        "iamTotalCount": iam_total_count,
        "grantedIamPermissions": iam_granted_list,
        "missingIamPermissions": iam_missing_list,
        "missingSummary": missing_summary,
        "areas": areas
    }


def fetch_project_apikey_owners(
    pid: str,
    token: str,
    keys_list: list[dict] = None,
    fallback_owners: dict[str, dict] = None
) -> dict[str, dict]:
    """
    100% Read-Only lookup of API Key creators/owners from Cloud Audit Logs (cloudaudit.googleapis.com/activity):
    Uses top-level timestamp partition pruning around each API key's createTime (plus a recent 30-day window
    for deleted/updated keys) so Cloud Logging responds in ~0.5s instead of scanning 400 days and timing out.
    """
    base_clause = (
        f'logName="projects/{pid}/logs/cloudaudit.googleapis.com%2Factivity" AND '
        '(protoPayload.serviceName="apikeys.googleapis.com" OR protoPayload.methodName:"ApiKeys")'
    )
    now_utc = datetime.now(timezone.utc)
    raw_windows = []
    for k in (keys_list or []):
        ct_str = str(k.get("createTime") or "").strip()
        if not ct_str:
            continue
        with contextlib.suppress(ValueError, TypeError):
            ct_dt = datetime.fromisoformat(ct_str.replace("Z", "+00:00"))
            raw_windows.append((ct_dt - timedelta(minutes=5), ct_dt + timedelta(minutes=5)))

    # Merge windows that are within 1 hour of each other to keep partition pruning ultra-tight (~10 min each)
    raw_windows.sort(key=lambda w: w[0])
    merged_windows = []
    for w_start, w_end in raw_windows:
        if not merged_windows:
            merged_windows.append([w_start, w_end])
        else:
            prev_s, prev_e = merged_windows[-1]
            if (w_start - prev_e).total_seconds() <= 3600:
                merged_windows[-1][1] = max(prev_e, w_end)
            else:
                merged_windows.append([w_start, w_end])

    # Include a 48-hour recent window to catch any brand-new or just-deleted keys
    if not merged_windows:
        merged_windows.append([now_utc - timedelta(days=30), now_utc + timedelta(minutes=5)])
    elif (now_utc - merged_windows[-1][1]).total_seconds() > 3600:
        merged_windows.append([now_utc - timedelta(hours=48), now_utc + timedelta(minutes=5)])

    def _query_window(win_pair):
        w_s, w_e = win_pair
        s_iso = w_s.strftime("%Y-%m-%dT%H:%M:%SZ")
        e_iso = w_e.strftime("%Y-%m-%dT%H:%M:%SZ")
        log_filter = f'timestamp >= "{s_iso}" AND timestamp <= "{e_iso}" AND {base_clause}'
        win_entries = []
        page_tok = None
        for _ in range(2):
            payload_dict = {
                "resourceNames": [f"projects/{pid}"],
                "filter": log_filter,
                "pageSize": 500,
                "orderBy": "timestamp desc"
            }
            if page_tok:
                payload_dict["pageToken"] = page_tok
            st_l, data = gcp_api_post("https://logging.googleapis.com/v2/entries:list", token, payload_dict, timeout=12)
            if st_l != 200 or not isinstance(data, dict):
                break
            batch = data.get("entries", [])
            if batch:
                win_entries.extend(batch)
            page_tok = data.get("nextPageToken")
            if not page_tok:
                break
        return win_entries

    entries = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(merged_windows)))) as w_pool:
        for w_res in w_pool.map(_query_window, merged_windows):
            if w_res:
                entries.extend(w_res)

    owners = {}
    op_to_principal = {}
    for entry in entries:
        pp = entry.get("protoPayload") or {}
        principal = ((pp.get("authenticationInfo") or {}).get("principalEmail") or "").strip().lower()
        op_id = ((entry.get("operation") or {}).get("id") or "").strip()
        if op_id and principal:
            op_to_principal[op_id] = principal

    for entry in entries:
        pp = entry.get("protoPayload") or {}
        op_id = ((entry.get("operation") or {}).get("id") or "").strip()
        principal = ((pp.get("authenticationInfo") or {}).get("principalEmail") or "").strip().lower()
        if not principal and op_id:
            principal = op_to_principal.get(op_id, "")
        if not principal:
            continue
        method = pp.get("methodName") or ""
        resp_obj = pp.get("response") if isinstance(pp.get("response"), dict) else {}
        req_obj = pp.get("request") if isinstance(pp.get("request"), dict) else {}
        req_key = req_obj.get("key") if isinstance(req_obj.get("key"), dict) else {}
        uid = resp_obj.get("uid") or req_key.get("uid") or ""
        for cand_name in (resp_obj.get("name") or "", pp.get("resourceName") or "", req_key.get("name") or ""):
            if not uid and "/keys/" in cand_name:
                uid = cand_name.split("/keys/", 1)[1].split("/")[0]
        if not uid:
            continue
        disp = resp_obj.get("displayName") or req_key.get("displayName") or ""
        ts = entry.get("timestamp") or ""
        existing = owners.get(uid)
        if not existing:
            owners[uid] = {
                "uid": uid,
                "ownerEmail": principal,
                "displayName": disp,
                "createdAt": ts,
                "method": method
            }
        else:
            # Prefer CreateKey over UpdateKey for the creator email
            if "CreateKey" in method and "CreateKey" not in existing.get("method", ""):
                existing["ownerEmail"] = principal
                existing["createdAt"] = ts
                existing["method"] = method
            if disp and not existing.get("displayName"):
                existing["displayName"] = disp

    if fallback_owners:
        for f_uid, f_info in fallback_owners.items():
            if f_uid and isinstance(f_info, dict) and f_info.get("ownerEmail"):
                if f_uid not in owners or not owners[f_uid].get("ownerEmail"):
                    owners[f_uid] = dict(f_info)

    return owners


def prefetch_project_user_activity_entries(pid: str, token: str, start_dt: datetime, end_dt: datetime, days: int) -> list[dict]:
    """
    100% Read-Only parallel Cloud Logging I/O prefetch for individual human / OAuth user & inference operation logs.
    Runs Stream A (user activity & data_access) and Stream B (gen_ai.client.inference.operation.details) concurrently
    across time slices over persistent Keep-Alive connections.
    """
    num_slices = 1 if days <= 2 else (4 if days <= 7 else (8 if days <= 30 else 12))
    total_sec = max(60.0, (end_dt - start_dt).total_seconds())
    slice_sec = total_sec / float(num_slices)

    slices = []
    for idx in range(num_slices):
        s_t = start_dt + timedelta(seconds=idx * slice_sec)
        e_t = start_dt + timedelta(seconds=(idx + 1) * slice_sec)
        slices.append((s_t.strftime("%Y-%m-%dT%H:%M:%SZ"), e_t.strftime("%Y-%m-%dT%H:%M:%SZ")))

    ai_audit_services = (
        '"aiplatform.googleapis.com" OR "discoveryengine.googleapis.com" OR '
        '"dialogflow.googleapis.com" OR "generativelanguage.googleapis.com" OR '
        '"cloudaicompanion.googleapis.com" OR "notebooks.googleapis.com" OR '
        '"geminicloudassist.googleapis.com" OR "geminidataanalytics.googleapis.com" OR '
        '"documentai.googleapis.com" OR "vision.googleapis.com" OR '
        '"speech.googleapis.com" OR "texttospeech.googleapis.com" OR '
        '"translate.googleapis.com" OR "modelarmor.googleapis.com" OR '
        '"agentregistry.googleapis.com"'
    )

    def _paginate_log_query(log_filter: str, max_pages: int = 8, page_size: int = 1000) -> list[dict]:
        entries_out = []
        page_tok = None
        for _ in range(max_pages):
            payload_dict = {
                "resourceNames": [f"projects/{pid}"],
                "filter": log_filter,
                "pageSize": page_size,
                "orderBy": "timestamp desc"
            }
            if page_tok:
                payload_dict["pageToken"] = page_tok
            st_l, data = gcp_api_post("https://logging.googleapis.com/v2/entries:list", token, payload_dict, timeout=15)
            if st_l != 200 or not isinstance(data, dict):
                break
            batch = data.get("entries", [])
            if batch:
                entries_out.extend(batch)
            page_tok = data.get("nextPageToken")
            if not page_tok:
                break
        return entries_out

    query_tasks = []
    for s_iso, e_iso in slices:
        user_filter = (
            f'timestamp >= "{s_iso}" AND timestamp <= "{e_iso}" AND ('
            f'(logName="projects/{pid}/logs/discoveryengine.googleapis.com%2Fgemini_enterprise_user_activity" AND jsonPayload.userIamPrincipal:* AND NOT jsonPayload.logMetadata.methodName="WriteUserEvent") OR '
            f'logName="projects/{pid}/logs/cloudaicompanion.googleapis.com%2Fmetadata" OR '
            f'logName="projects/{pid}/logs/cloudaicompanion.googleapis.com%2Frequest" OR '
            f'logName="projects/{pid}/logs/cloudaicompanion.googleapis.com%2Fresponse" OR '
            f'((logName:"cloudaudit.googleapis.com%2Fdata_access" OR logName:"cloudaudit.googleapis.com%2Factivity") AND protoPayload.authenticationInfo.principalEmail:* AND protoPayload.serviceName:({ai_audit_services}))'
            f')'
        )
        op_filter = (
            f'timestamp >= "{s_iso}" AND timestamp <= "{e_iso}" AND '
            f'logName="projects/{pid}/logs/discoveryengine.googleapis.com%2Fgen_ai.client.inference.operation.details"'
        )
        query_tasks.append((user_filter, 10, 1000))
        query_tasks.append((op_filter, 6, 1000))

    all_entries = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(query_tasks)))) as ex:
        for res_list in ex.map(lambda qt: _paginate_log_query(qt[0], qt[1], qt[2]), query_tasks):
            if res_list:
                all_entries.extend(res_list)
    return all_entries


def _get_or_create_user_record(user_records: dict[str, dict], email_raw: str, pid: str) -> dict:
    email = email_raw.strip().lower()
    if email not in user_records:
        if email.startswith("oauth-workload:"):
            u_type = "OAUTH_WORKLOAD"
        elif "@external." in email:
            u_type = "EXTERNAL_USER"
        elif "gserviceaccount.com" in email:
            u_type = "SERVICE_ACCOUNT"
        else:
            u_type = "INTERNAL_USER"
        user_records[email] = {
            "userEmail": email,
            "projectId": pid,
            "userType": u_type,
            "totalInteractions": 0,
            "assistTurns": 0,
            "searchQueries": 0,
            "fileOps": 0,
            "codeAssistCalls": 0,
            "codeAssistAcceptedLines": 0,
            "codeAssistAcceptedCount": 0,
            "codeAssistExposedCount": 0,
            "codeAssistAcceptanceRatePct": 0.0,
            "codeAssistInputChars": 0,
            "codeAssistOutputChars": 0,
            "codeAssistSeatMonthlyUsd": 0.0,
            "codeAssistLanguages": set(),
            "codeAssistWorkspaces": set(),
            "notebookLmCalls": 0,
            "colabCalls": 0,
            "aiStudioCalls": 0,
            "otherCalls": 0,
            "toolsUsed": set(),
            "loggedInferenceOps": 0,
            "loggedInputTokens": 0,
            "loggedOutputTokens": 0,
            "loggedCachedTokens": 0,
            "loggedTotalTokens": 0,
            "attributedTokens": 0,
            "vertexOauthCalls": 0,
            "vertexOauthInputTokens": 0,
            "vertexOauthOutputTokens": 0,
            "vertexOauthCachedTokens": 0,
            "vertexOauthTokens": 0,
            "vertexOauthGrossCostUsd": 0.0,
            "vertexOauthCacheSavingsUsd": 0.0,
            "vertexOauthCostUsd": 0.0,
            "vertexOauthTodayCalls": 0,
            "vertexOauthTodayTokens": 0,
            "vertexOauthTodayCostUsd": 0.0,
            "vertexOauthYesterdayCalls": 0,
            "vertexOauthYesterdayTokens": 0,
            "vertexOauthYesterdayCostUsd": 0.0,
            "oauthClientsDetails": [],
            "apiKeysCount": 0,
            "apiKeysNames": set(),
            "apiKeysDetails": [],
            "apiKeysCalls": 0,
            "apiKeysInputTokens": 0,
            "apiKeysOutputTokens": 0,
            "apiKeysCachedTokens": 0,
            "apiKeysTotalTokens": 0,
            "apiKeysRequestBytes": 0,
            "apiKeysResponseBytes": 0,
            "apiKeysGrossCostUsd": 0.0,
            "apiKeysCacheSavingsUsd": 0.0,
            "apiKeysCostUsd": 0.0,
            "apiKeysTodayCalls": 0,
            "apiKeysTodayTokens": 0,
            "apiKeysTodayCostUsd": 0.0,
            "apiKeysYesterdayCalls": 0,
            "apiKeysYesterdayTokens": 0,
            "apiKeysYesterdayCostUsd": 0.0,
            "oauthCostUsd": 0.0,
            "oauthSharePct": 0.0,
            "directCostUsd": 0.0,
            "estimatedCostUsd": 0.0,
            "sharePct": 0.0,
            "methods": set(),
            "engines": set(),
            "dataStores": set(),
            "ideClients": set(),
            "services": set(),
            "activeDays": set(),
            "firstSeen": None,
            "lastSeen": None
        }
    return user_records[email]


def _update_user_timestamps(u_rec: dict, ts_str: str) -> None:
    if not ts_str:
        return
    day_s = ts_str[:10]
    if len(day_s) == 10:
        u_rec["activeDays"].add(day_s)
    if not u_rec["firstSeen"] or ts_str < u_rec["firstSeen"]:
        u_rec["firstSeen"] = ts_str
    if not u_rec["lastSeen"] or ts_str > u_rec["lastSeen"]:
        u_rec["lastSeen"] = ts_str


def _parse_gemini_enterprise_user_log(
    jp: dict,
    ts_str: str,
    trace: str,
    pid: str,
    user_records: dict[str, dict],
    trace_to_user: dict[str, str],
    conv_to_user: dict[str, str]
) -> None:
    principal = (jp.get("userIamPrincipal") or "").strip()
    if not principal:
        return
    u_rec = _get_or_create_user_record(user_records, principal, pid)
    _update_user_timestamps(u_rec, ts_str)
    u_rec["services"].add("discoveryengine.googleapis.com")
    if trace:
        trace_to_user[trace] = principal.lower()

    meta = jp.get("logMetadata") or {}
    method = (meta.get("methodName") or "Unknown").split(".")[-1]
    res_name = meta.get("name") or ""
    if "/engines/" not in res_name:
        req_obj = jp.get("request") if isinstance(jp.get("request"), dict) else {}
        ue_obj = req_obj.get("userEvent") if isinstance(req_obj.get("userEvent"), dict) else {}
        res_name = str(ue_obj.get("engine") or req_obj.get("servingConfig") or req_obj.get("name") or res_name)
    if "/engines/" in res_name:
        eng_id = res_name.split("/engines/", 1)[1].split("/")[0]
        if eng_id:
            u_rec["engines"].add(eng_id)
    for marker in ("/sessions/", "/conversations/"):
        if marker in res_name:
            cid = res_name.split(marker, 1)[1].split("/")[0]
            if cid and cid != "-":
                conv_to_user[cid] = principal.lower()

    resp_obj = jp.get("response") if isinstance(jp.get("response"), dict) else {}
    ds_info = resp_obj.get("dataSourceInfo") if isinstance(resp_obj.get("dataSourceInfo"), dict) else {}
    for ds in (ds_info.get("dataStores") or []):
        ds_name = (ds.get("dataStoreName") if isinstance(ds, dict) else str(ds)) or ""
        ds_short = ds_name.split("/dataStores/", 1)[1].split("/")[0] if "/dataStores/" in ds_name else ds_name.strip()
        if ds_short.endswith("_s2s"):
            ds_short = ds_short[:-4]
        if ds_short:
            u_rec["dataStores"].add(ds_short)

    u_rec["totalInteractions"] += 1
    u_rec["methods"].add(method)
    m_low = method.lower()
    is_notebook_lm = any(
        nb_k in m_low for nb_k in ("notebook", "audiooverview", "freeformstreamed", "interactsources", "uploadsourcefile")
    ) or any("notebooklm" in ds.lower() for ds in u_rec["dataStores"])
    if is_notebook_lm:
        u_rec["notebookLmCalls"] += 1
        u_rec["toolsUsed"].add("NotebookLM Enterprise")
    if "assist" in m_low or "converse" in m_low or "answer" in m_low:
        u_rec["assistTurns"] += 1
        u_rec["toolsUsed"].add("Gemini Enterprise / Agentspace")
    elif "search" in m_low or "recommend" in m_low:
        u_rec["searchQueries"] += 1
        u_rec["toolsUsed"].add("Gemini Enterprise / Agentspace")
    elif "file" in m_low or "context" in m_low:
        u_rec["fileOps"] += 1
    else:
        u_rec["otherCalls"] += 1


def _parse_cloud_companion_user_log(
    log_name: str,
    jp: dict,
    labels: dict,
    ts_str: str,
    pid: str,
    user_records: dict[str, dict]
) -> None:
    uid = (labels.get("user_id") or "").strip()
    raw_method = (labels.get("method") or "").strip()
    method = raw_method.split(".")[-1]
    if not uid:
        return
    u_rec = _get_or_create_user_record(user_records, uid, pid)
    _update_user_timestamps(u_rec, ts_str)
    u_rec["services"].add("cloudaicompanion.googleapis.com")
    u_rec["toolsUsed"].add("Gemini Code Assist / Cloud Assist")

    client_name = (jp.get("clientName") or "").strip()
    client_ver = (jp.get("clientVersion") or "").strip()
    if client_name:
        ide_lbl = f"{client_name} v{client_ver}" if client_ver else client_name
        if client_ver and client_name in u_rec["ideClients"]:
            u_rec["ideClients"].discard(client_name)
        if not any(ic.startswith(f"{client_name} v") for ic in u_rec["ideClients"]) or client_ver:
            u_rec["ideClients"].add(ide_lbl)

    if "%2Fmetadata" in log_name or "/metadata" in log_name:
        if method == "Metrics":
            c_acc = jp.get("codeAcceptance") if isinstance(jp.get("codeAcceptance"), dict) else None
            c_exp = jp.get("codeExposure") if isinstance(jp.get("codeExposure"), dict) else None
            if c_acc is not None:
                u_rec["codeAssistAcceptedCount"] += 1
                u_rec["codeAssistAcceptedLines"] += int(c_acc.get("linesCount", 1) or 1)
                lang_a = (c_acc.get("programmingLanguage") or "").strip().lower()
                if lang_a:
                    u_rec["codeAssistLanguages"].add(lang_a)
            if c_exp is not None:
                u_rec["codeAssistExposedCount"] += 1
                lang_e = (c_exp.get("programmingLanguage") or "").strip().lower()
                if lang_e:
                    u_rec["codeAssistLanguages"].add(lang_e)
        else:
            u_rec["totalInteractions"] += 1
            u_rec["codeAssistCalls"] += 1
            if method:
                u_rec["methods"].add(method)
    elif "%2Frequest" in log_name or "/request" in log_name:
        cc_req = jp.get("codeCompletionRequest") if isinstance(jp.get("codeCompletionRequest"), dict) else {}
        in_ctx = cc_req.get("inputDataContext") if isinstance(cc_req.get("inputDataContext"), dict) else {}
        add_ctx = in_ctx.get("additionalContext") if isinstance(in_ctx.get("additionalContext"), dict) else {}
        skip_dirs = {"src", "main", "test", "java", "resources", "webapp", "app", "pages", "components", "modules", "lib", "dist", "build", "node_modules", "users"}
        for f_item in (add_ctx.get("files") or []):
            if not isinstance(f_item, dict):
                continue
            f_lang = (f_item.get("language") or "").strip().lower()
            if f_lang:
                u_rec["codeAssistLanguages"].add(f_lang)
            f_path = (f_item.get("path") or "").strip()
            if f_path:
                parts = [pt for pt in f_path.replace("\\", "/").split("/") if pt and ":" not in pt]
                ws_candidates = [pt for pt in parts[:-1] if pt.lower() not in skip_dirs and not pt.startswith(".")]
                if ws_candidates:
                    u_rec["codeAssistWorkspaces"].add(ws_candidates[-1])
            for seg in (f_item.get("segments") or []):
                if isinstance(seg, dict):
                    u_rec["codeAssistInputChars"] += len(seg.get("content") or "")
        gen_req = jp.get("generateCodeRequest") or jp.get("chatRequest") or {}
        if isinstance(gen_req, dict) and gen_req:
            u_rec["codeAssistInputChars"] += len(json.dumps(gen_req))
    elif "%2Fresponse" in log_name or "/response" in log_name:
        cc_resp = jp.get("codeCompletionResponse") if isinstance(jp.get("codeCompletionResponse"), dict) else {}
        out_obj = cc_resp.get("output") if isinstance(cc_resp.get("output"), dict) else {}
        out_content = out_obj.get("content") or ""
        if out_content:
            u_rec["codeAssistOutputChars"] += len(str(out_content))
        gen_resp = jp.get("generateCodeResponse") or jp.get("chatResponse") or {}
        if isinstance(gen_resp, dict) and gen_resp:
            u_rec["codeAssistOutputChars"] += len(json.dumps(gen_resp))
    elif method != "Metrics":
        u_rec["totalInteractions"] += 1
        u_rec["codeAssistCalls"] += 1
        if method:
            u_rec["methods"].add(method)


def _parse_cloud_audit_user_log(entry: dict, ts_str: str, pid: str, user_records: dict[str, dict]) -> None:
    pp = entry.get("protoPayload") or {}
    principal = ((pp.get("authenticationInfo") or {}).get("principalEmail") or "").strip()
    if not principal:
        return
    svc_name = pp.get("serviceName") or "aiplatform.googleapis.com"
    method = (pp.get("methodName") or "AuditCall").split(".")[-1]
    if method.startswith("List") or method in ("GetFloorSetting", "GetCacheConfig", "TestIamPermissions", "GetIamPolicy"):
        return
    u_rec = _get_or_create_user_record(user_records, principal, pid)
    _update_user_timestamps(u_rec, ts_str)
    u_rec["services"].add(svc_name)
    audit_res_name = str(pp.get("resourceName") or "")
    if "/engines/" in audit_res_name:
        audit_eng_id = audit_res_name.split("/engines/", 1)[1].split("/")[0].split(":")[0]
        if audit_eng_id:
            u_rec["engines"].add(audit_eng_id)
    if "/dataStores/" in audit_res_name:
        audit_ds_id = audit_res_name.split("/dataStores/", 1)[1].split("/")[0].split(":")[0]
        if audit_ds_id:
            u_rec["dataStores"].add(audit_ds_id)
    u_rec["totalInteractions"] += 1
    u_rec["methods"].add(method)
    m_low = method.lower()
    if svc_name == "notebooks.googleapis.com" or "notebookruntime" in m_low or "notebookexecution" in m_low:
        u_rec["colabCalls"] += 1
        u_rec["toolsUsed"].add("Colab Enterprise / Workbench")
    elif svc_name == "generativelanguage.googleapis.com":
        u_rec["aiStudioCalls"] += 1
        u_rec["toolsUsed"].add("Google AI Studio")
    elif svc_name in ("cloudaicompanion.googleapis.com", "geminicloudassist.googleapis.com", "geminidataanalytics.googleapis.com"):
        u_rec["codeAssistCalls"] += 1
        u_rec["toolsUsed"].add("Gemini Code Assist / Cloud Assist")
    elif svc_name == "discoveryengine.googleapis.com" and "notebook" in m_low:
        u_rec["notebookLmCalls"] += 1
        u_rec["toolsUsed"].add("NotebookLM Enterprise")
    elif svc_name == "discoveryengine.googleapis.com":
        u_rec["otherCalls"] += 1
        u_rec["toolsUsed"].add("Gemini Enterprise / Agentspace")
    else:
        u_rec["otherCalls"] += 1
        if svc_name == "aiplatform.googleapis.com":
            u_rec["toolsUsed"].add("Vertex AI")


def _attribute_apikeys_to_user_records(
    result: dict,
    creds_dict: dict[str, dict],
    end_dt: datetime,
    pid: str,
    user_records: dict[str, dict]
) -> None:
    today_str = end_dt.strftime("%Y-%m-%d")
    yesterday_str = (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    for k_obj in (result.get("apiKeys") or []):
        owner_email = (k_obj.get("ownerEmail") or "").strip().lower()
        if not owner_email:
            continue
        k_calls = int(k_obj.get("inferenceRequests", 0) or k_obj.get("requests", 0) or 0)
        k_tot_tok = int(k_obj.get("totalTokens", 0) or 0)
        k_cost = float(k_obj.get("estimatedCostUsd", 0.0) or 0.0)
        if k_calls <= 0 and k_tot_tok <= 0 and k_cost <= 0.0 and k_obj.get("status") != "ACTIVE":
            continue

        u_rec = _get_or_create_user_record(user_records, owner_email, pid)
        u_rec["apiKeysCount"] += 1
        disp_name = k_obj.get("displayName") or k_obj.get("uid", "")[:8]
        if disp_name:
            u_rec["apiKeysNames"].add(disp_name)
        u_rec["apiKeysCalls"] += k_calls
        u_rec["apiKeysInputTokens"] += int(k_obj.get("inputTokens", 0) or 0)
        u_rec["apiKeysOutputTokens"] += int(k_obj.get("outputTokens", 0) or 0)
        u_rec["apiKeysCachedTokens"] += int(k_obj.get("cachedTokens", 0) or 0)
        u_rec["apiKeysTotalTokens"] += k_tot_tok
        u_rec["apiKeysRequestBytes"] += int(k_obj.get("requestBytes", 0) or 0)
        u_rec["apiKeysResponseBytes"] += int(k_obj.get("responseBytes", 0) or 0)
        u_rec["apiKeysGrossCostUsd"] += float(k_obj.get("grossCostUsd", k_cost) or 0.0)
        u_rec["apiKeysCacheSavingsUsd"] += float(k_obj.get("cacheSavingsUsd", 0.0) or 0.0)
        u_rec["apiKeysCostUsd"] += k_cost

        c_lookup = f"apikey:{k_obj.get('uid', '')}"
        c_data = creds_dict.get(c_lookup, {})
        d_series = c_data.get("dailySeries") or {}
        today_b = d_series.get(today_str) or {}
        yest_b = d_series.get(yesterday_str) or {}

        k_today_calls = int(k_obj.get("todayCalls") if "todayCalls" in k_obj else (today_b.get("inferenceRequests", 0) or today_b.get("requests", 0) or 0))
        k_today_tok = int(k_obj.get("todayTokens") if "todayTokens" in k_obj else (today_b.get("tokens", 0) or 0))
        k_today_cost = float(k_obj.get("todayCostUsd") if "todayCostUsd" in k_obj else (today_b.get("costUsd", 0.0) or 0.0))

        k_yest_calls = int(k_obj.get("yesterdayCalls") if "yesterdayCalls" in k_obj else (yest_b.get("inferenceRequests", 0) or yest_b.get("requests", 0) or 0))
        k_yest_tok = int(k_obj.get("yesterdayTokens") if "yesterdayTokens" in k_obj else (yest_b.get("tokens", 0) or 0))
        k_yest_cost = float(k_obj.get("yesterdayCostUsd") if "yesterdayCostUsd" in k_obj else (yest_b.get("costUsd", 0.0) or 0.0))

        u_rec["apiKeysTodayCalls"] += k_today_calls
        u_rec["apiKeysTodayTokens"] += k_today_tok
        u_rec["apiKeysTodayCostUsd"] += k_today_cost
        u_rec["apiKeysYesterdayCalls"] += k_yest_calls
        u_rec["apiKeysYesterdayTokens"] += k_yest_tok
        u_rec["apiKeysYesterdayCostUsd"] += k_yest_cost

        u_rec["apiKeysDetails"].append({
            "uid": k_obj.get("uid", ""),
            "displayName": disp_name,
            "status": k_obj.get("status", "ACTIVE"),
            "calls": k_calls,
            "ok200Calls": int(k_obj.get("ok200Inference", k_calls) or 0),
            "inputTokens": int(k_obj.get("inputTokens", 0) or 0),
            "outputTokens": int(k_obj.get("outputTokens", 0) or 0),
            "totalTokens": k_tot_tok,
            "requestBytes": int(k_obj.get("requestBytes", 0) or 0),
            "responseBytes": int(k_obj.get("responseBytes", 0) or 0),
            "grossCostUsd": round(float(k_obj.get("grossCostUsd", k_cost) or 0.0), 4),
            "cacheSavingsUsd": round(float(k_obj.get("cacheSavingsUsd", 0.0) or 0.0), 4),
            "costUsd": round(k_cost, 4),
            "todayDate": today_str,
            "todayCalls": k_today_calls,
            "todayTokens": k_today_tok,
            "todayCostUsd": round(k_today_cost, 4),
            "yesterdayDate": yesterday_str,
            "yesterdayCalls": k_yest_calls,
            "yesterdayTokens": k_yest_tok,
            "yesterdayCostUsd": round(k_yest_cost, 4),
            "methods": k_obj.get("inferenceMethods") or k_obj.get("methods") or []
        })

        for s_name in (k_obj.get("services") or []):
            if s_name:
                u_rec["services"].add(s_name)
                if s_name == "generativelanguage.googleapis.com":
                    u_rec["aiStudioCalls"] += k_calls
                    u_rec["toolsUsed"].add("Google AI Studio")
        if "aistudio" in disp_name.lower() or "generative language" in disp_name.lower() or "gemini" in disp_name.lower():
            u_rec["toolsUsed"].add("Google AI Studio")
        is_ide_key = any(kw in disp_name.lower() for kw in ("antigravity", "ide", "vscode", "cursor", "cline", "windsurf", "code assist"))
        for m_name in (k_obj.get("inferenceMethods") or k_obj.get("methods") or []):
            if m_name:
                u_rec["methods"].add(f"APIKey:{m_name}")
                if "stream" in m_name.lower():
                    u_rec["ideClients"].add("Antigravity / IDE (AI Studio Stream)" if is_ide_key else "Gemini API Stream (API Key)")
                else:
                    u_rec["ideClients"].add("AI Studio API Key")
        for day_s, d_bucket in d_series.items():
            if (d_bucket.get("requests", 0) or 0) > 0:
                _update_user_timestamps(u_rec, f"{day_s}T12:00:00Z")


def _attribute_oauth_clients_to_user_records(
    result: dict,
    creds_dict: dict[str, dict],
    end_dt: datetime,
    pid: str,
    user_records: dict[str, dict]
) -> None:
    """
    Attributes OAuth Client IDs (e.g. Antigravity IDE calling Vertex AI aiplatform.googleapis.com)
    directly to their configured owner in models_pricing_config.json (or to a dedicated oauth-workload:<id> record),
    preventing Vertex AI OAuth costs from being pooled/smeared across Discovery Engine (Agentspace) users.
    """
    today_str = end_dt.strftime("%Y-%m-%d")
    yesterday_str = (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    oauth_owners = get_oauth_client_owners()

    for c_id, c_obj in creds_dict.items():
        if not c_id or c_id.startswith("apikey:") or c_id.startswith("serviceaccount:") or c_id == "system:unattributed-audit-logs-disabled":
            continue
        raw_client_id = c_id.split(":", 1)[1] if c_id.startswith(("oauth2:", "oauth:")) else c_id
        owner_entry = oauth_owners.get(raw_client_id) or oauth_owners.get(c_id)

        svcs_c = set(c_obj.get("services") or [])
        v_inf_calls = int(c_obj.get("vertexInferenceRequests", 0) or 0)
        inf_calls = int(c_obj.get("inferenceRequests", 0) or c_obj.get("requests", 0) or 0)
        tot_tok_c = int(c_obj.get("totalTokens", 0) or 0)
        cost_c = float(c_obj.get("estimatedCostUsd", 0.0) or 0.0)
        is_vertex_oauth = ("aiplatform.googleapis.com" in svcs_c) or (v_inf_calls > 0)

        owner_email = ""
        disp_name = ""
        tool_label = "Antigravity IDE (Vertex AI OAuth)"

        if isinstance(owner_entry, dict) and owner_entry.get("ownerEmail"):
            owner_email = str(owner_entry.get("ownerEmail") or "").strip().lower()
            disp_name = str(owner_entry.get("displayName") or f"OAuth App ({raw_client_id[:16]}...)")
            tool_label = str(owner_entry.get("tool") or "Antigravity IDE (Vertex AI OAuth)")
        elif isinstance(owner_entry, str) and owner_entry.strip():
            owner_email = owner_entry.strip().lower()
            disp_name = f"OAuth App ({raw_client_id[:16]}...)"
            tool_label = "Antigravity IDE (Vertex AI OAuth)"
        elif is_vertex_oauth and (inf_calls > 0 or tot_tok_c > 0 or cost_c > 0.0):
            short_cid = raw_client_id.split("-")[0] if "-" in raw_client_id else raw_client_id[:16]
            owner_email = f"oauth-workload:{short_cid}"
            disp_name = f"OAuth Workload Vertex AI ({short_cid})"
            tool_label = "Vertex AI OAuth / ADC"

        if not owner_email:
            continue

        c_obj["_attributedToUser"] = owner_email
        c_obj["ownerEmail"] = owner_email
        c_obj["resolvedName"] = f"{disp_name} — {owner_email}" if "@" in owner_email else disp_name
        c_obj["resolvedType"] = "OAUTH_CLIENT"

        if inf_calls <= 0 and tot_tok_c <= 0 and cost_c <= 0.0:
            continue

        u_rec = _get_or_create_user_record(user_records, owner_email, pid)
        vo_calls = v_inf_calls if v_inf_calls > 0 else inf_calls
        vo_in = int(c_obj.get("inputTokens", 0) or 0)
        vo_out = int(c_obj.get("outputTokens", 0) or 0)
        vo_cache = int(c_obj.get("cachedTokens", 0) or 0)
        vo_gross = float(c_obj.get("grossCostUsd", cost_c) or 0.0)
        vo_sav = float(c_obj.get("cacheSavingsUsd", 0.0) or 0.0)

        d_series = c_obj.get("dailySeries") or {}
        today_b = d_series.get(today_str) or {}
        yest_b = d_series.get(yesterday_str) or {}

        c_today_calls = int(c_obj.get("todayCalls") if "todayCalls" in c_obj else (today_b.get("inferenceRequests", 0) or today_b.get("requests", 0) or 0))
        c_today_tok = int(c_obj.get("todayTokens") if "todayTokens" in c_obj else (today_b.get("tokens", 0) or 0))
        c_today_cost = float(c_obj.get("todayCostUsd") if "todayCostUsd" in c_obj else (today_b.get("costUsd", 0.0) or 0.0))

        c_yest_calls = int(c_obj.get("yesterdayCalls") if "yesterdayCalls" in c_obj else (yest_b.get("inferenceRequests", 0) or yest_b.get("requests", 0) or 0))
        c_yest_tok = int(c_obj.get("yesterdayTokens") if "yesterdayTokens" in c_obj else (yest_b.get("tokens", 0) or 0))
        c_yest_cost = float(c_obj.get("yesterdayCostUsd") if "yesterdayCostUsd" in c_obj else (yest_b.get("costUsd", 0.0) or 0.0))

        u_rec["vertexOauthCalls"] += vo_calls
        u_rec["vertexOauthInputTokens"] += vo_in
        u_rec["vertexOauthOutputTokens"] += vo_out
        u_rec["vertexOauthCachedTokens"] += vo_cache
        u_rec["vertexOauthTokens"] += tot_tok_c
        u_rec["vertexOauthGrossCostUsd"] += vo_gross
        u_rec["vertexOauthCacheSavingsUsd"] += vo_sav
        u_rec["vertexOauthCostUsd"] += cost_c
        u_rec["vertexOauthTodayCalls"] += c_today_calls
        u_rec["vertexOauthTodayTokens"] += c_today_tok
        u_rec["vertexOauthTodayCostUsd"] += c_today_cost
        u_rec["vertexOauthYesterdayCalls"] += c_yest_calls
        u_rec["vertexOauthYesterdayTokens"] += c_yest_tok
        u_rec["vertexOauthYesterdayCostUsd"] += c_yest_cost
        u_rec["totalInteractions"] += vo_calls

        u_rec["oauthClientsDetails"].append({
            "credentialId": c_id,
            "clientId": raw_client_id,
            "displayName": disp_name,
            "tool": tool_label,
            "calls": vo_calls,
            "ok200Calls": int(c_obj.get("ok200Inference", vo_calls) or 0),
            "errors429": int(c_obj.get("errors429", 0) or 0),
            "inputTokens": vo_in,
            "outputTokens": vo_out,
            "cachedTokens": vo_cache,
            "totalTokens": tot_tok_c,
            "grossCostUsd": round(vo_gross, 4),
            "cacheSavingsUsd": round(vo_sav, 4),
            "costUsd": round(cost_c, 4),
            "todayDate": today_str,
            "todayCalls": c_today_calls,
            "todayTokens": c_today_tok,
            "todayCostUsd": round(c_today_cost, 4),
            "yesterdayDate": yesterday_str,
            "yesterdayCalls": c_yest_calls,
            "yesterdayTokens": c_yest_tok,
            "yesterdayCostUsd": round(c_yest_cost, 4),
            "services": sorted(list(svcs_c)),
            "models": sorted(list(c_obj.get("modelsUsed") or c_obj.get("models") or [])),
            "methods": sorted(list(c_obj.get("inferenceMethods") or c_obj.get("methods") or []))
        })

        u_rec["toolsUsed"].add(tool_label)
        if is_vertex_oauth:
            u_rec["toolsUsed"].add("Vertex AI")
        u_rec["ideClients"].add(tool_label)
        for s_name in svcs_c:
            if s_name:
                u_rec["services"].add(s_name)
        for m_name in (c_obj.get("inferenceMethods") or c_obj.get("methods") or []):
            if m_name:
                u_rec["methods"].add(f"OAuth:{m_name}")
        for day_s, d_bucket in d_series.items():
            if (d_bucket.get("requests", 0) or 0) > 0:
                _update_user_timestamps(u_rec, f"{day_s}T12:00:00Z")


def _reconcile_user_oauth_and_final_costs(user_records: dict[str, dict], creds_dict: dict[str, dict]) -> list[dict]:
    oauth_pool_cost = 0.0
    oauth_pool_tokens = 0
    for c_obj in creds_dict.values():
        c_id = c_obj.get("credentialId", "")
        if c_obj.pop("_attributedToUser", None):
            continue
        if not c_id.startswith("apikey:") and not c_id.startswith("serviceaccount:") and c_id != "system:unattributed-audit-logs-disabled":
            c_est = float(c_obj.get("estimatedCostUsd", 0.0) or 0.0)
            c_vtx = float(c_obj.get("vertexCostUsd", 0.0) or 0.0)
            if c_vtx <= 0 and "aiplatform.googleapis.com" in (c_obj.get("services") or []) and len(c_obj.get("services") or []) == 1:
                continue
            non_vtx_cost = max(0.0, c_est - c_vtx)
            oauth_pool_cost += non_vtx_cost
            if non_vtx_cost > 0:
                oauth_pool_tokens += int(c_obj.get("totalTokens", 0) or 0)

    rates = get_model_rates("gemini-2.5-pro")
    total_direct_oauth_cost = 0.0
    total_oauth_weight = 0.0

    for u_rec in user_records.values():
        if u_rec["codeAssistCalls"] > 0 or u_rec["codeAssistInputChars"] > 0 or u_rec["codeAssistOutputChars"] > 0:
            ca_in_tok = int(round(u_rec["codeAssistInputChars"] / 4.0)) if u_rec["codeAssistInputChars"] > 0 else (u_rec["codeAssistCalls"] * 180)
            ca_out_tok = int(round(u_rec["codeAssistOutputChars"] / 4.0)) if u_rec["codeAssistOutputChars"] > 0 else (u_rec["codeAssistCalls"] * 65)
            if u_rec["loggedTotalTokens"] == 0:
                u_rec["loggedInputTokens"] = ca_in_tok
                u_rec["loggedOutputTokens"] = ca_out_tok
                u_rec["loggedTotalTokens"] = ca_in_tok + ca_out_tok
        if u_rec["codeAssistExposedCount"] > 0:
            u_rec["codeAssistAcceptanceRatePct"] = round(min(100.0, (u_rec["codeAssistAcceptedCount"] / float(u_rec["codeAssistExposedCount"])) * 100.0), 1)
        elif u_rec["codeAssistAcceptedCount"] > 0:
            u_rec["codeAssistAcceptanceRatePct"] = 100.0
        u_rec["codeAssistSeatMonthlyUsd"] = 0.0

        non_cached_in = max(0, u_rec["loggedInputTokens"] - u_rec["loggedCachedTokens"])
        tok_cost = (
            (non_cached_in / 1_000_000.0) * rates["input"] +
            (u_rec["loggedCachedTokens"] / 1_000_000.0) * rates["cache_read_input"] +
            (u_rec["loggedOutputTokens"] / 1_000_000.0) * rates["output"]
        )
        assist_cost = u_rec["assistTurns"] * (0.0041 if u_rec["loggedTotalTokens"] == 0 else 0.0015)
        search_cost = u_rec["searchQueries"] * 0.0015
        code_cost = u_rec["codeAssistCalls"] * 0.00084

        direct_oauth = tok_cost + assist_cost + search_cost + code_cost
        u_rec["_directOauth"] = direct_oauth
        total_direct_oauth_cost += direct_oauth

        has_oauth_activity = any(
            u_rec[k] > 0 for k in ("assistTurns", "searchQueries", "codeAssistCalls", "fileOps", "otherCalls", "loggedTotalTokens")
        )
        weight = (
            direct_oauth * 100.0 +
            u_rec["assistTurns"] * 0.40 +
            u_rec["searchQueries"] * 0.12 +
            u_rec["codeAssistCalls"] * 0.08 +
            u_rec["fileOps"] * 0.05 +
            (0.01 if has_oauth_activity else 0.0)
        )
        u_rec["_weight"] = weight
        total_oauth_weight += weight

    target_pool_cost = oauth_pool_cost if oauth_pool_cost > 0 else total_direct_oauth_cost
    target_pool_tokens = max(oauth_pool_tokens, sum(u["loggedTotalTokens"] for u in user_records.values()))

    users_list = []
    for u_rec in user_records.values():
        w_share = (u_rec["_weight"] / total_oauth_weight) if (total_oauth_weight > 0 and u_rec["_weight"] > 0) else 0.0
        direct_oauth = u_rec.pop("_directOauth", 0.0)
        u_rec.pop("_weight", None)

        vo_calls = int(u_rec.get("vertexOauthCalls", 0) or 0)
        vo_tok = int(u_rec.get("vertexOauthTokens", 0) or 0)
        vo_cost = round(float(u_rec.get("vertexOauthCostUsd", 0.0) or 0.0), 4)
        u_rec["vertexOauthGrossCostUsd"] = round(float(u_rec.get("vertexOauthGrossCostUsd", vo_cost) or 0.0), 4)
        u_rec["vertexOauthCacheSavingsUsd"] = round(float(u_rec.get("vertexOauthCacheSavingsUsd", 0.0) or 0.0), 4)
        u_rec["vertexOauthCostUsd"] = vo_cost
        u_rec["vertexOauthTodayCostUsd"] = round(float(u_rec.get("vertexOauthTodayCostUsd", 0.0) or 0.0), 4)
        u_rec["vertexOauthYesterdayCostUsd"] = round(float(u_rec.get("vertexOauthYesterdayCostUsd", 0.0) or 0.0), 4)
        u_rec["oauthClientsDetails"].sort(key=lambda x: (x["costUsd"], x["totalTokens"], x["calls"]), reverse=True)

        pool_oauth_cost = (target_pool_cost * w_share) if target_pool_cost > 0 else direct_oauth
        pool_oauth_tok = max(u_rec["loggedTotalTokens"], int(round(target_pool_tokens * w_share))) if w_share > 0 else u_rec["loggedTotalTokens"]

        oauth_est_cost = pool_oauth_cost + vo_cost
        oauth_attr_tok = pool_oauth_tok + vo_tok

        u_rec["oauthCostUsd"] = round(oauth_est_cost, 4)
        u_rec["oauthSharePct"] = round(w_share * 100.0, 2)
        u_rec["apiKeysGrossCostUsd"] = round(u_rec["apiKeysGrossCostUsd"], 4)
        u_rec["apiKeysCacheSavingsUsd"] = round(u_rec["apiKeysCacheSavingsUsd"], 4)
        u_rec["apiKeysCostUsd"] = round(u_rec["apiKeysCostUsd"], 4)
        u_rec["apiKeysTodayCostUsd"] = round(u_rec["apiKeysTodayCostUsd"], 4)
        u_rec["apiKeysYesterdayCostUsd"] = round(u_rec["apiKeysYesterdayCostUsd"], 4)
        u_rec["apiKeysDetails"].sort(key=lambda x: (x["costUsd"], x["totalTokens"], x["calls"]), reverse=True)
        u_rec["directCostUsd"] = round(direct_oauth + vo_cost + u_rec["apiKeysCostUsd"], 4)
        u_rec["estimatedCostUsd"] = round(oauth_est_cost + u_rec["apiKeysCostUsd"], 4)
        u_rec["attributedTokens"] = oauth_attr_tok + u_rec["apiKeysTotalTokens"]

        ca_calls_u = int(u_rec.get("codeAssistCalls", 0) or 0)
        ak_calls_u = int(u_rec.get("apiKeysCalls", 0) or 0)
        if ca_calls_u > 0:
            if u_rec.get("assistTurns", 0) == 0 and u_rec.get("searchQueries", 0) == 0:
                ca_cost_u = round(pool_oauth_cost, 4)
                ca_tok_u = int(pool_oauth_tok)
            else:
                ca_cost_u = round(min(pool_oauth_cost, ca_calls_u * 0.0014), 4)
                ca_tok_u = ca_calls_u * 245
        else:
            ca_cost_u = 0.0
            ca_tok_u = 0
        u_rec["codeAssistCostUsd"] = ca_cost_u
        u_rec["codeAssistTokens"] = ca_tok_u
        u_rec["antigravityIdeCalls"] = ca_calls_u + ak_calls_u + vo_calls
        u_rec["antigravityIdeTokens"] = ca_tok_u + int(u_rec.get("apiKeysTotalTokens", 0) or 0) + vo_tok
        u_rec["antigravityIdeCostUsd"] = round(ca_cost_u + u_rec["apiKeysCostUsd"] + vo_cost, 4)

        for set_k in ("apiKeysNames", "methods", "engines", "dataStores", "ideClients", "codeAssistLanguages", "codeAssistWorkspaces", "services", "toolsUsed"):
            u_rec[set_k] = sorted(list(u_rec.get(set_k, set())))
        u_rec["activeDaysCount"] = len(u_rec["activeDays"])
        u_rec.pop("activeDays", None)
        users_list.append(u_rec)

    total_all_users_cost = sum(u["estimatedCostUsd"] for u in users_list)
    total_all_users_int = sum(u["totalInteractions"] for u in users_list)
    for u_rec in users_list:
        if total_all_users_cost > 0:
            u_rec["sharePct"] = round((u_rec["estimatedCostUsd"] / total_all_users_cost) * 100.0, 2)
        elif total_all_users_int > 0:
            u_rec["sharePct"] = round((u_rec["totalInteractions"] / float(total_all_users_int)) * 100.0, 2)
        else:
            u_rec["sharePct"] = round(100.0 / len(users_list), 2)

    users_list.sort(key=lambda x: (x["estimatedCostUsd"], x["attributedTokens"], x["totalInteractions"]), reverse=True)
    return users_list


def fetch_project_user_activity_logs(
    pid: str,
    token: str,
    start_dt: datetime,
    end_dt: datetime,
    days: int,
    result: dict,
    apikey_owners: dict = None,
    prefetched_entries: list[dict] = None,
    prev_users_usage: list[dict] = None
) -> list[dict]:
    """
    100% Read-Only extraction & correlation of individual human / OAuth user & API Key owner AI usage from Cloud Logging.
    """
    all_entries = (
        prefetched_entries
        if prefetched_entries is not None
        else prefetch_project_user_activity_entries(pid, token, start_dt, end_dt, days)
    )

    trace_to_user = {}
    conv_to_user = {}
    user_records = {}
    op_entries = []

    for entry in all_entries:
        log_name = entry.get("logName", "")
        ts_str = entry.get("timestamp", "")
        trace = entry.get("trace", "")
        jp = entry.get("jsonPayload") or {}
        labels = entry.get("labels") or {}

        if "gemini_enterprise_user_activity" in log_name:
            _parse_gemini_enterprise_user_log(jp, ts_str, trace, pid, user_records, trace_to_user, conv_to_user)
        elif "gen_ai.client.inference.operation.details" in log_name:
            in_t = int(jp.get("gen_ai.usage.input_tokens") or 0)
            out_t = int(jp.get("gen_ai.usage.output_tokens") or 0)
            cache_t = int(jp.get("gen_ai.usage.cache_read.input_tokens") or 0)
            conv_id = str(jp.get("gen_ai.conversation.id") or "")
            agent_name = str(jp.get("gen_ai.agent.name") or "")
            op_entries.append((ts_str, trace, conv_id, agent_name, in_t, out_t, cache_t))
        elif "cloudaicompanion.googleapis.com" in log_name:
            _parse_cloud_companion_user_log(log_name, jp, labels, ts_str, pid, user_records)
        elif "cloudaudit.googleapis.com" in log_name:
            _parse_cloud_audit_user_log(entry, ts_str, pid, user_records)

    for ts_str, trace, conv_id, agent_name, in_t, out_t, cache_t in op_entries:
        matched_user = trace_to_user.get(trace) or conv_to_user.get(conv_id)
        if matched_user and conv_id:
            conv_to_user[conv_id] = matched_user

    for ts_str, trace, conv_id, agent_name, in_t, out_t, cache_t in op_entries:
        matched_user = trace_to_user.get(trace) or conv_to_user.get(conv_id)
        if not matched_user:
            continue
        u_rec = _get_or_create_user_record(user_records, matched_user, pid)
        _update_user_timestamps(u_rec, ts_str)
        u_rec["loggedInferenceOps"] += 1
        u_rec["loggedInputTokens"] += in_t
        u_rec["loggedOutputTokens"] += out_t
        u_rec["loggedCachedTokens"] += cache_t
        u_rec["loggedTotalTokens"] += (in_t + out_t)
        if agent_name:
            u_rec["methods"].add(f"Agent:{agent_name}")

    start_iso_bound = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(prev_users_usage, list) and days >= 30:
        for pu in prev_users_usage:
            if not isinstance(pu, dict):
                continue
            p_email = str(pu.get("userEmail") or "").strip().lower()
            p_last = str(pu.get("lastSeen") or "")
            if not p_email or p_email.startswith("oauth-workload:") or (p_last and p_last < start_iso_bound):
                continue
            has_prev_oauth = any(
                int(pu.get(k, 0) or 0) > 0
                for k in ("assistTurns", "searchQueries", "notebookLmCalls", "codeAssistCalls", "fileOps", "otherCalls", "loggedTotalTokens")
            )
            if not has_prev_oauth:
                continue
            u_rec = _get_or_create_user_record(user_records, p_email, pid)
            _update_user_timestamps(u_rec, str(pu.get("firstSeen") or ""))
            _update_user_timestamps(u_rec, p_last)
            for int_field in (
                "totalInteractions", "assistTurns", "searchQueries", "fileOps",
                "codeAssistCalls", "codeAssistAcceptedLines", "codeAssistExposedCount", "codeAssistAcceptedCount",
                "codeAssistInputChars", "codeAssistOutputChars", "notebookLmCalls", "otherCalls",
                "loggedInferenceOps", "loggedInputTokens", "loggedOutputTokens", "loggedCachedTokens", "loggedTotalTokens"
            ):
                u_rec[int_field] = max(int(u_rec.get(int_field, 0) or 0), int(pu.get(int_field, 0) or 0))
            for set_field in ("engines", "dataStores", "ideClients", "codeAssistLanguages", "codeAssistWorkspaces", "services", "toolsUsed"):
                for item_v in (pu.get(set_field) or []):
                    if item_v:
                        u_rec[set_field].add(str(item_v))
            for m_v in (pu.get("methods") or []):
                if m_v and not str(m_v).startswith(("APIKey:", "OAuth:")):
                    u_rec["methods"].add(str(m_v))

    creds_dict = result.get("credentialsUsage", {}) if isinstance(result.get("credentialsUsage"), dict) else {
        c.get("credentialId", ""): c for c in (result.get("credentialsUsage") or [])
    }
    _attribute_apikeys_to_user_records(result, creds_dict, end_dt, pid, user_records)
    _attribute_oauth_clients_to_user_records(result, creds_dict, end_dt, pid, user_records)

    for res_obj in (result.get("deployedAiResources") or []):
        r_type = res_obj.get("resourceType") or res_obj.get("type") or ""
        rt_user = (res_obj.get("runtimeUser") or "").strip().lower()
        if r_type in ("COLAB_ENTERPRISE_RUNTIME", "COLAB_EXECUTION_JOB", "WORKBENCH_NOTEBOOK") and rt_user:
            u_rec = _get_or_create_user_record(user_records, rt_user, pid)
            u_rec["colabCalls"] += 1
            u_rec["totalInteractions"] = max(1, u_rec["totalInteractions"])
            u_rec["toolsUsed"].add("Colab Enterprise / Workbench")
            u_rec["services"].add("notebooks.googleapis.com" if r_type == "WORKBENCH_NOTEBOOK" else "aiplatform.googleapis.com")
            u_rec["methods"].add(f"Runtime:{res_obj.get('displayName') or res_obj.get('resourceId')}")
            _update_user_timestamps(u_rec, res_obj.get("updateTime") or res_obj.get("createTime") or "")

    if not user_records:
        return []

    return _reconcile_user_oauth_and_final_costs(user_records, creds_dict)


