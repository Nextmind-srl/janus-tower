def evaluate_project_ai_security_posture(p: dict) -> dict:
    """
    100% Read-Only AI Security Posture Management (AI-SPM) & Gemini Enterprise Agent Platform Audit.
    Evaluates a project across 8 enterprise AI security & GDPR pillars and produces a 0-100 score,
    grade (A/B/C/D/F), risk level, governance flags, and read-only gcloud remediation commands.
    """
    pid = p.get("projectId", "unknown")
    ai_active = bool(p.get("aiActive", False))
    total_reqs = p.get("totalRequests", 0) or 0
    inf_reqs = p.get("inferenceRequests", 0) or 0
    total_tokens = p.get("totalTokens", 0) or 0
    gemini_reqs = p.get("geminiApiRequests", 0) or 0
    deployed = p.get("deployedAiResources", []) or []
    enabled_apis = {a.get("service", "") for a in (p.get("enabledAiApis", []) or [])}
    ma = p.get("modelArmor", {}) or {}
    ma_status = ma.get("status", "DISABLED")
    ma_telemetry = ma.get("threatTelemetry", {}) or {}
    residency = p.get("dataResidency") or {}

    if not ai_active and total_reqs == 0 and total_tokens == 0 and not deployed:
        return {
            "evaluated": False,
            "score": 100,
            "grade": "A",
            "riskLevel": "NONE",
            "riskLabel": "⚪ No Active AI Workloads",
            "findingsCount": 0,
            "criticalCount": 0,
            "highCount": 0,
            "mediumCount": 0,
            "lowCount": 0,
            "findings": [],
            "governance": {
                "modelArmorProtected": False,
                "agentRegistryEnabled": False,
                "dlpEnabled": False,
                "iapGatewayEnabled": False,
                "gdprCompliant": True
            }
        }

    score = 100
    findings = []

    def _rtype(r: dict) -> str:
        return r.get("resourceType") or r.get("type") or ""

    has_agents = any(_rtype(r) in ("REASONING_ENGINE", "DIALOGFLOW_CX_AGENT", "AGENT_REGISTRY_AGENT", "AGENT_REGISTRY_MCP", "AGENTSPACE_APP") for r in deployed) or ("discoveryengine.googleapis.com" in enabled_apis)
    vertex_reqs = int(p.get("vertexRequests", 0) or 0)
    other_ai_reqs = max(0, inf_reqs - vertex_reqs - gemini_reqs)
    has_vertex_or_enterprise_ai = (
        vertex_reqs > 0
        or other_ai_reqs > 0
        or len(deployed) > 0
        or ("aiplatform.googleapis.com" in enabled_apis and (inf_reqs > gemini_reqs or total_reqs > gemini_reqs))
        or ("discoveryengine.googleapis.com" in enabled_apis and total_reqs > 0)
    )
    has_active_traffic = (inf_reqs > 0 or total_tokens > 0 or total_reqs > 0 or len(deployed) > 0)

    # 1. Model Armor Protection Check (Prompt Injection / Jailbreak / SDP / Malicious URI)
    # Note: Model Armor applies to Vertex AI / Gemini Enterprise / Agentspace workloads, not pure Google AI Studio API keys
    ma_protected = ma_status in ("INSPECT_AND_BLOCK", "FLOOR_PROTECTED", "CONFIGURED_ACTIVE", "CONFIGURED") or len(ma.get("templates") or []) > 0
    if has_active_traffic and has_vertex_or_enterprise_ai and not ma_protected:
        sev = "CRITICAL" if (has_agents or total_tokens > 10000 or inf_reqs > 50) else "HIGH"
        deduct = 28 if sev == "CRITICAL" else 18
        score -= deduct
        findings.append({
            "id": "MISSING_MODEL_ARMOR",
            "severity": sev,
            "category": "Runtime AI Guardrails (Model Armor)",
            "title": "Unprotected Vertex AI workloads / agents: Model Armor not enabled",
            "description": (
                f"The project is processing Enterprise AI traffic ({inf_reqs} inferences, {total_tokens} tokens, {len(deployed)} deployed resources) "
                f"but Model Armor status is '{ma.get('statusLabel', ma_status)}'. Prompt injection, jailbreak, PII data leakage and malicious URLs in tools are not being filtered."
            ),
            "verifyCmd": f"gcloud model-armor floorsettings describe --full-uri=projects/{pid}/locations/global/floorSetting",
            "remediationCmd": (
                f"gcloud services enable modelarmor.googleapis.com --project={pid} && "
                f"gcloud model-armor floorsettings update --full-uri=projects/{pid}/locations/global/floorSetting "
                f"--enable-floor-setting-enforcement=true "
                f"--pi-and-jailbreak-filter-settings-enforcement=ENABLED "
                f"--pi-and-jailbreak-filter-settings-confidence-level=MEDIUM_AND_ABOVE "
                f"--malicious-uri-filter-settings-enforcement=ENABLED"
            )
        })

    # 2. Unrestricted API Keys, Old Unrotated Keys (>90d) or Direct Gemini API Key Usage Bypassing IAM/VPC-SC
    api_keys = [k for k in (p.get("apiKeys", []) or []) if k.get("status") != "GCP_CONSOLE_FIRST_PARTY"]
    unrestricted_keys = [k for k in api_keys if not (k.get("restrictions") or k.get("apiTargets"))]
    old_keys = [k for k in api_keys if k.get("status") == "ACTIVE" and (k.get("ageDays") or 0) > 90]

    if unrestricted_keys:
        sev = "CRITICAL" if gemini_reqs > 0 else "HIGH"
        score -= (22 if sev == "CRITICAL" else 14)
        k_names = ", ".join(k.get("displayName") or k.get("name", "key") for k in unrestricted_keys[:3])
        first_uid = unrestricted_keys[0].get("uid") or "KEY_UID"
        target_svcs = [s for s in (unrestricted_keys[0].get("services") or []) if s] or (["generativelanguage.googleapis.com"] if gemini_reqs > 0 else ["aiplatform.googleapis.com"])
        api_target_flags = " ".join(f"--api-target=service={s}" for s in target_svcs[:3])
        findings.append({
            "id": "UNRESTRICTED_API_KEYS",
            "severity": sev,
            "category": "Credential & Key Hygiene",
            "title": f"{len(unrestricted_keys)} API Keys without API restrictions (Unrestricted Keys)",
            "description": (
                f"Found {len(unrestricted_keys)} API Keys ({k_names}) with no apiTargets. "
                f"If leaked in client code or a Git repository, they can be used to call any API enabled on the project and generate uncontrolled costs."
            ),
            "verifyCmd": f"gcloud services api-keys list --project={pid} --format=\"table(uid,displayName,restrictions.apiTargets)\"",
            "remediationCmd": f"gcloud services api-keys update {first_uid} --project={pid} {api_target_flags}"
        })
    if gemini_reqs > 0 and ("generativelanguage.googleapis.com" in enabled_apis or any(k.get("isAiStudioKey") for k in api_keys)):
        score -= 10
        findings.append({
            "id": "DIRECT_GEMINI_DEVELOPER_API",
            "severity": "MEDIUM",
            "category": "Enterprise AI Governance (AI Studio)",
            "title": f"Traffic on Google AI Studio / Gemini Developer API ({gemini_reqs} calls) instead of Vertex AI",
            "description": (
                "Direct use of generativelanguage.googleapis.com via API Key (AI Studio) supports neither VPC Service Controls, CMEK, Model Armor Floor Settings nor granular IAM."
            ),
            "verifyCmd": f"gcloud services list --enabled --project={pid} --filter=\"config.name:generativelanguage.googleapis.com\"",
            "remediationCmd": f"gcloud services enable aiplatform.googleapis.com --project={pid} && gcloud services disable generativelanguage.googleapis.com --project={pid}"
        })
    if old_keys:
        score -= 8
        old_names = ", ".join(f"{k.get('displayName')} ({k.get('ageDays')}d)" for k in old_keys[:3])
        old_uid = old_keys[0].get("uid") or "KEY_UID"
        findings.append({
            "id": "STATIC_APIKEY_ROTATION_OVERDUE",
            "severity": "LOW",
            "category": "Credential & Key Hygiene",
            "title": f"{len(old_keys)} active API Keys created more than 90 days ago without rotation",
            "description": f"The static keys ({old_names}) exceed the recommended rotation threshold (90 days).",
            "verifyCmd": f"gcloud services api-keys list --project={pid} --format=\"table(displayName,createTime,uid)\"",
            "remediationCmd": f"gcloud services api-keys clone {old_uid} --project={pid} && gcloud services api-keys delete {old_uid} --project={pid}"
        })

    # 3. GDPR / Data Residency & Sovereignty Check (Extra-UE US regions vs Control-Plane vs Global Endpoint Routing)
    non_eu_locs = residency.get("nonEuLocations") or []
    non_eu_res = residency.get("nonEuDeployedResources") or []
    non_eu_res_cnt = int(residency.get("nonEuResourcesCount", len(non_eu_res)) or 0)
    global_locs = residency.get("globalLocations") or []
    if non_eu_locs or non_eu_res_cnt > 0:
        reg_buckets = {r_b.get("location"): (r_b.get("sources") or []) for r_b in (residency.get("regions") or [])}
        all_non_eu_sources = [src for loc_k in non_eu_locs for src in reg_buckets.get(loc_k, [])]
        only_code_assist_us = (
            non_eu_res_cnt == 0
            and non_eu_locs == ["us-east4"]
            and all("Code Assist" in s or "Companion" in s for s in all_non_eu_sources)
        )
        only_aistudio_us = (
            non_eu_res_cnt == 0
            and all("AI Studio" in loc_k for loc_k in non_eu_locs)
        )
        locs_lbl = ", ".join(non_eu_locs[:3]) if non_eu_locs else ", ".join(sorted(list({x.get("region", "us") for x in non_eu_res}))[:3])
        if only_code_assist_us:
            score -= 6
            findings.append({
                "id": "GDPR_NON_EU_AI_PROCESSING",
                "severity": "LOW",
                "category": "Data Residency & GDPR Sovereignty",
                "title": f"Gemini Code Assist telemetry / control plane routed to {locs_lbl}",
                "description": (
                    f"No customer AI resources are deployed outside the EU, but the managed service 'cloudaicompanion.googleapis.com' (Gemini Code Assist IDE) "
                    f"uses the default Google endpoint in '{locs_lbl}'. To keep Code Assist in the EU, configure Data Residency in the Admin Console."
                ),
                "verifyCmd": f"gcloud logging read 'logName:\"cloudaicompanion.googleapis.com\"' --project={pid} --limit=5 --format=\"table(timestamp,location,labels.user_id)\"",
                "remediationCmd": f"gcloud resource-manager org-policies describe gcp.resourceLocations --project={pid} # Set Gemini Code Assist Data Residency = Europe in the GCP Console"
            })
        elif only_aistudio_us:
            score -= 12
            findings.append({
                "id": "GDPR_NON_EU_AI_PROCESSING",
                "severity": "MEDIUM",
                "category": "Data Residency & GDPR Sovereignty",
                "title": f"Google AI Studio API Key processing routed to US data centers ({locs_lbl})",
                "description": (
                    f"Calls to 'generativelanguage.googleapis.com' via API Key are processed on global/US endpoints ({locs_lbl}) with no EU Data Residency guarantee. "
                    "Migrate SDK calls to Vertex AI with region='europe-west8' (Milan) or 'europe-west1'."
                ),
                "verifyCmd": f"gcloud services api-keys list --project={pid} --format=\"table(displayName,uid,restrictions.apiTargets)\"",
                "remediationCmd": f"gcloud services enable aiplatform.googleapis.com --project={pid} # Set vertexai.init(project='{pid}', location='europe-west8')"
            })
        else:
            score -= 18
            res_detail_str = ""
            if non_eu_res:
                res_names_str = ", ".join(f"{x.get('name')} ({x.get('region')})" for x in non_eu_res[:5])
                res_detail_str = f" Non-EU resources detected ({non_eu_res_cnt}): {res_names_str}."
            findings.append({
                "id": "GDPR_NON_EU_AI_PROCESSING",
                "severity": "HIGH",
                "category": "Data Residency & GDPR Sovereignty",
                "title": f"AI Processing or Resources in Non-EU Regions ({locs_lbl})",
                "description": (
                    f"Inference calls or deployed AI resources detected outside the European Union ({locs_lbl}).{res_detail_str} "
                    "For GDPR compliance and corporate Data Residency, restrict AI workloads to europe-west8 (Milan) or europe-west1/west4."
                ),
                "verifyCmd": f"gcloud resource-manager org-policies describe gcp.resourceLocations --project={pid}",
                "remediationCmd": f"gcloud org-policies set-policy --project={pid} policy-eu-only.yaml # Allow only in:eu-locations / in:europe-west8-locations"
            })
    elif global_locs and (inf_reqs > 0 or total_tokens > 0):
        score -= 5
        findings.append({
            "id": "GDPR_GLOBAL_ENDPOINT_ROUTING",
            "severity": "LOW",
            "category": "Data Residency & GDPR Sovereignty",
            "title": "LLM invocations on 'global' endpoint (Anycast Multi-Region)",
            "description": (
                "The Vertex AI / Gemini 'global' endpoint provides higher throughput but may route processing to non-EU data centers unless constrained by Data Residency."
            ),
            "verifyCmd": f"gcloud logging read 'protoPayload.serviceName=\"aiplatform.googleapis.com\"' --project={pid} --limit=5 --format=\"table(timestamp,resource.labels.location)\"",
            "remediationCmd": f"# Set location='europe-west8' (Milan) or 'europe-west1' in the Vertex AI SDK client configuration"
        })

    # 4. Static Service Account Keys (USER_MANAGED) vs SPIFFE Agent Identity / Workload Identity
    s_accounts = p.get("serviceAccounts", []) or []
    sa_with_user_keys = [sa for sa in s_accounts if (sa.get("userManagedKeysCount", 0) or 0) > 0]
    total_user_keys = sum((sa.get("userManagedKeysCount", 0) or 0) for sa in sa_with_user_keys)
    if sa_with_user_keys:
        score -= 15
        sa_emails = ", ".join(sa.get("email", "") for sa in sa_with_user_keys[:2])
        first_sa_email = sa_with_user_keys[0].get("email", "SA_EMAIL")
        first_sa_keys = sa_with_user_keys[0].get("keys") or []
        first_key_id = (first_sa_keys[0].get("keyId") if first_sa_keys and isinstance(first_sa_keys[0], dict) else None) or "KEY_ID"
        findings.append({
            "id": "STATIC_SA_USER_MANAGED_KEYS",
            "severity": "HIGH",
            "category": "Agent Identity & Zero-Trust (SPIFFE / WIF)",
            "title": f"{total_user_keys} Static JSON Keys (USER_MANAGED) on {len(sa_with_user_keys)} Service Accounts",
            "description": (
                f"The Service Accounts ({sa_emails}) hold manually exported private keys. "
                "Per Gemini Enterprise Agent Platform best practices, agents and workloads must use ephemeral SPIFFE identities (Agent Identity) or Workload Identity Federation."
            ),
            "verifyCmd": f"gcloud iam service-accounts keys list --iam-account={first_sa_email} --managed-by=user --project={pid}",
            "remediationCmd": f"gcloud iam service-accounts keys delete {first_key_id} --iam-account={first_sa_email} --project={pid}"
        })

    # 5. Attribution Blindness / Missing Data Access Audit Logs on AI APIs
    creds_usage = p.get("credentialsUsage", []) or []
    has_unattributed = any(c.get("credentialId") == "system:unattributed-audit-logs-disabled" for c in creds_usage)
    if has_unattributed or (total_tokens > 0 and len(creds_usage) == 0):
        score -= 15
        findings.append({
            "id": "AUDIT_LOGS_ATTRIBUTION_BLINDNESS",
            "severity": "MEDIUM",
            "category": "Forensics & FinOps Attribution",
            "title": "Identity Attribution Blindness (Data Access Audit Logs DATA_READ/DATA_WRITE disabled)",
            "description": (
                f"LLM usage detected ({total_tokens} tokens) that cannot be attributed to a specific user or Service Account in Cloud Audit Logs. "
                "Without DATA_READ/DATA_WRITE on aiplatform.googleapis.com, the caller cannot be traced in case of abuse or a security incident."
            ),
            "verifyCmd": f"gcloud projects get-iam-policy {pid} --format=\"json(auditConfigs)\"",
            "remediationCmd": f"gcloud projects get-iam-policy {pid} --format=json > policy.json && gcloud projects set-iam-policy {pid} policy.json # Enable DATA_READ/DATA_WRITE on aiplatform.googleapis.com"
        })

    # 6. Shadow AI / Unregistered Agents (Reasoning Engine / Dialogflow CX without Agent Registry)
    unregistered_agents = [r for r in deployed if _rtype(r) in ("REASONING_ENGINE", "DIALOGFLOW_CX_AGENT")]
    agent_registry_active = ("agentregistry.googleapis.com" in enabled_apis) or any(_rtype(r) in ("AGENT_REGISTRY_AGENT", "AGENT_REGISTRY_MCP") for r in deployed)
    if unregistered_agents and not agent_registry_active:
        score -= 12
        ag_names = ", ".join(r.get("displayName", r.get("name", "")) for r in unregistered_agents[:3])
        findings.append({
            "id": "SHADOW_AI_UNREGISTERED_AGENTS",
            "severity": "MEDIUM",
            "category": "Shadow AI & Agent Governance",
            "title": f"{len(unregistered_agents)} AI Agents deployed outside Gemini Enterprise Agent Registry",
            "description": (
                f"Detected {len(unregistered_agents)} active agents ({ag_names}) but the 'agentregistry.googleapis.com' API is not enabled. "
                "Registering agents and MCP servers in Agent Registry makes it possible to govern A2A protocols, lifecycle and authorized tools."
            ),
            "verifyCmd": f"gcloud alpha agent-registry agents list --project={pid} --location=global",
            "remediationCmd": f"gcloud services enable agentregistry.googleapis.com --project={pid}"
        })

    # 7. Active Runtime Violations Detected in Model Armor Logs
    flagged = ma_telemetry.get("flaggedCount", 0) or 0
    blocked = ma_telemetry.get("blockedCount", 0) or 0
    if flagged > 0:
        score -= min(20, 5 + flagged * 2)
        findings.append({
            "id": "ACTIVE_MODEL_ARMOR_THREATS",
            "severity": "HIGH" if blocked < flagged else "MEDIUM",
            "category": "Active Threat Telemetry",
            "title": f"{flagged} Runtime violations detected by Model Armor ({blocked} blocked)",
            "description": (
                f"Sanitization logs show {flagged} violation attempts (prompt injection, jailbreak, PII/DLP or malicious URLs) in recent days."
            ),
            "verifyCmd": f"gcloud logging read 'logName:\"modelarmor.googleapis.com\"' --project={pid} --limit=20 --format=json",
            "remediationCmd": f"gcloud model-armor floorsettings update --full-uri=projects/{pid}/locations/global/floorSetting --enable-floor-setting-enforcement=true --pi-and-jailbreak-filter-settings-enforcement=ENABLED --pi-and-jailbreak-filter-settings-confidence-level=LOW_AND_ABOVE"
        })

    # 8. Log Forensics: Ghost/Deleted Keys with Traffic, External Principals, Public Endpoints & Error/Quota Spikes
    forensics = p.get("aiLogForensics") or {}
    ghost_keys_cnt = forensics.get("ghostDeletedKeysWithTrafficCount", 0) or 0
    if ghost_keys_cnt > 0:
        score -= 10
        g_names = ", ".join(forensics.get("ghostDeletedKeysNames", [])[:3])
        findings.append({
            "id": "GHOST_DELETED_API_KEY_TRAFFIC",
            "severity": "MEDIUM",
            "category": "Cloud Audit Log Forensics",
            "title": f"{ghost_keys_cnt} deleted/external API Keys with detected traffic ({g_names})",
            "description": "AI calls recorded on API Keys that were revoked, deleted or external to the project during the observed period.",
            "verifyCmd": f"gcloud services api-keys list --show-deleted --project={pid}",
            "remediationCmd": f"gcloud logging read 'protoPayload.serviceName=\"apikeys.googleapis.com\"' --project={pid} --limit=20"
        })

    ext_users = forensics.get("externalUsers") or []
    if ext_users:
        score -= 8
        findings.append({
            "id": "EXTERNAL_GUEST_AI_ACCESS",
            "severity": "MEDIUM",
            "category": "Identity & Perimeter",
            "title": f"{len(ext_users)} External Users (@external) active on AI Apps/Agents ({', '.join(ext_users[:2])})",
            "description": "Principals outside the primary domain are invoking Discovery Engine / Agentspace or Vertex AI.",
            "verifyCmd": f"gcloud projects get-iam-policy {pid} --flatten=\"bindings[].members\" --filter=\"bindings.members:external\"",
            "remediationCmd": f"gcloud projects remove-iam-policy-binding {pid} --member=\"user:{ext_users[0]}\" --role=\"roles/discoveryengine.viewer\""
        })

    pub_eps = forensics.get("publicEndpoints") or []
    if pub_eps:
        score -= 8
        ep_regions = sorted(list({
            str(r.get("region") or r.get("location") or "europe-west8")
            for r in deployed
            if _rtype(r) in ("VERTEX_ENDPOINT", "VECTOR_SEARCH_INDEX_ENDPOINT") and (r.get("region") or r.get("location"))
        }))
        ep_reg = ep_regions[0] if ep_regions else "europe-west8"
        findings.append({
            "id": "PUBLIC_VERTEX_ENDPOINT_NO_PSC",
            "severity": "LOW",
            "category": "Network Perimeter (VPC-SC / PSC)",
            "title": f"{len(pub_eps)} Vertex/Vector Endpoints exposed without Private Service Connect ({', '.join(pub_eps[:2])})",
            "description": f"Endpoints registered in region '{ep_reg}' without a dedicated private VPC/PSC network or without CMEK keys.",
            "verifyCmd": f"gcloud ai index-endpoints list --project={pid} --region={ep_reg} && gcloud ai endpoints list --project={pid} --region={ep_reg}",
            "remediationCmd": f"gcloud access-context-manager perimeters update PERIMETER_NAME --add-restricted-services=aiplatform.googleapis.com # Or recreate the endpoint in '{ep_reg}' with --enable-private-service-connect"
        })

    err429 = forensics.get("errors429Count", 0) or 0
    err_fail = forensics.get("failedOrDeniedCallsCount", 0) or 0
    if err429 >= 10 or err_fail >= 20:
        score -= 6
        findings.append({
            "id": "API_QUOTA_OR_AUTH_ERROR_SPIKE",
            "severity": "LOW",
            "category": "Cloud Logging Error & Quota Telemetry",
            "title": f"HTTP anomalies: {err429} 429 errors (Quota) and {err_fail} failed calls (403/4xx/5xx)",
            "description": "Spikes of throttling (429 RESOURCE_EXHAUSTED) or rejected calls (403 PERMISSION_DENIED) in API logs.",
            "verifyCmd": f"gcloud logging read 'severity>=WARNING AND protoPayload.serviceName:(\"aiplatform\" OR \"discoveryengine\")' --project={pid} --limit=25",
            "remediationCmd": f"gcloud alpha services quota list --service=aiplatform.googleapis.com --consumer=projects/{pid}"
        })

    score = max(0, min(100, score))
    if score >= 90:
        grade, risk_lvl, risk_lbl = "A", "LOW", "🛡️ Secure / Compliant (Grade A)"
    elif score >= 75:
        grade, risk_lvl, risk_lbl = "B", "LOW", "✅ Good Posture (Grade B)"
    elif score >= 60:
        grade, risk_lvl, risk_lbl = "C", "MEDIUM", "⚠️ Moderate Risk (Grade C)"
    elif score >= 40:
        grade, risk_lvl, risk_lbl = "D", "HIGH", "🟠 High Risk (Grade D)"
    else:
        grade, risk_lvl, risk_lbl = "F", "CRITICAL", "🚨 Critical Risk (Grade F)"

    crit_c = sum(1 for f in findings if f["severity"] == "CRITICAL")
    high_c = sum(1 for f in findings if f["severity"] == "HIGH")
    med_c = sum(1 for f in findings if f["severity"] == "MEDIUM")
    low_c = sum(1 for f in findings if f["severity"] == "LOW")

    is_gdpr_ok = bool(residency.get("gdprCompliant", True)) and not non_eu_locs and non_eu_res_cnt == 0
    return {
        "evaluated": True,
        "score": score,
        "grade": grade,
        "riskLevel": risk_lvl,
        "riskLabel": risk_lbl,
        "findingsCount": len(findings),
        "criticalCount": crit_c,
        "highCount": high_c,
        "mediumCount": med_c,
        "lowCount": low_c,
        "findings": findings,
        "pillars": {
            "data_residency": {
                "status": "WARN" if not is_gdpr_ok else "OK",
                "detail": (
                    f"{non_eu_res_cnt} AI resources or calls in non-EU regions ({', '.join(non_eu_locs or [x.get('region', '') for x in non_eu_res[:2]])})"
                    if not is_gdpr_ok else "100% EU compliant / Global Anycast"
                )
            }
        },
        "governance": {
            "modelArmorProtected": ma_protected,
            "agentRegistryEnabled": agent_registry_active,
            "dlpEnabled": ("dlp.googleapis.com" in enabled_apis) or any(_rtype(r) == "DLP_INSPECT_TEMPLATE" for r in deployed),
            "iapGatewayEnabled": bool({"iap.googleapis.com", "networksecurity.googleapis.com", "serviceextensions.googleapis.com"} & enabled_apis),
            "apiKeysRestricted": len(unrestricted_keys) == 0,
            "unrestrictedApiKeysCount": len(unrestricted_keys),
            "zeroExportedSaKeys": len(sa_with_user_keys) == 0,
            "exportedSaKeysCount": len(sa_with_user_keys),
            "cmekEnabled": any(bool(r.get("cmekKey") or r.get("encryptionSpec")) for r in deployed),
            "gdprCompliant": is_gdpr_ok,
            "euDataResidencyCompliant": is_gdpr_ok
        }
    }


def enrich_scan_payload_security(payload: dict) -> dict:
    """
    Enriches every project in payload['projects'] and populates global summaries:
    - payload['summary']['securityPosture']
    - payload['summary']['dataResidency']
    - payload['summary']['finopsExtended']
    - payload['summary']['agentspaceTelemetry']
    - payload['summary']['httpStatusBreakdown'], payload['summary']['avgLatencyMs'], payload['summary']['serviceBreakdown']
    - payload['summary']['aiToolsOverview'] (AI Studio projects/keys/users, Colab Enterprise, Workbench, NotebookLM Enterprise)
    Works seamlessly on both live scans and existing cached JSON payloads.
    """
    projects = payload.get("projects", []) or []
    summary = payload.setdefault("summary", {})
    days_window = max(1, int(payload.get("days", summary.get("days", 30)) or 30))

    evaluated_scores = []
    crit_total = 0
    high_total = 0
    med_total = 0
    low_total = 0
    findings_total = 0

    ma_total_logs = 0
    ma_flagged = 0
    ma_blocked = 0
    ma_passed = 0
    ma_pi = 0
    ma_dlp = 0
    ma_rai = 0
    ma_uri = 0

    agent_reg_projects = 0
    dlp_projects = 0
    iap_projects = 0
    unprotected_ai_projects = 0
    gdpr_non_compliant_projects = 0

    # Global Data Residency aggregators
    global_reg_map = {}
    cat_weights = {"ITALY_LOCAL": 0.0, "EU_EEA": 0.0, "GLOBAL_ANYCAST": 0.0, "NON_EU_US_OTHER": 0.0}
    all_non_eu_resources = []
    total_non_eu_requests = 0

    # Global FinOps Extended aggregators
    tot_in_tok = 0
    tot_cached_tok = 0
    tot_cache_savings = 0.0
    tot_potential_extra_savings = 0.0
    all_idle_resources = []
    all_zombie_engines = []

    # Global Agentspace Telemetry aggregators
    global_as_apps = []
    global_as_ds = []
    global_as_queries = 0
    global_as_convs = 0

    # Global HTTP Status Breakdown, Latency & Service Breakdown aggregators
    global_http_status = {"200": 0, "400": 0, "403": 0, "404": 0, "429": 0, "500": 0, "other": 0}
    lat_weighted_sum_all = 0.0
    lat_requests_all = 0
    svc_breakdown_map = {}

    # Global AI Studio & Notebooks / Tools aggregators
    ai_studio_projects_list = []
    ai_studio_users_set = set()
    ai_studio_total_keys = 0
    ai_studio_total_calls = 0
    ai_studio_total_cost = 0.0

    notebooks_projects_list = []
    notebook_users_set = set()
    total_notebooklm_calls = 0
    total_colab_calls = 0
    total_colab_resources = 0
    total_code_assist_calls = 0
    total_code_assist_accepted_lines = 0
    total_code_assist_accepted_count = 0
    total_code_assist_exposed_count = 0
    code_assist_languages_set = set()
    code_assist_workspaces_set = set()
    code_assist_users_set = set()

    # Global AI Log Forensics & Security Signals aggregators
    lf_errors_429 = 0
    lf_failed_calls = 0
    lf_unrestricted_keys = 0
    lf_stale_keys = 0
    lf_ghost_keys = 0
    lf_ghost_keys_list = []
    lf_first_party_keys = 0
    lf_exported_sa_keys = 0
    lf_external_users_set = set()
    lf_unattr_projects = 0
    lf_unattr_tokens = 0
    lf_unattr_calls = 0
    lf_public_endpoints = 0
    lf_non_cmek_resources = 0
    lf_weekend_calls = 0
    lf_weekend_cost = 0.0
    lf_spike_days_list = []
    lf_admin_mutations_map = {}
    lf_keywords_counts = {}

    for p in projects:
        enrich_single_project_telemetry(p, scan_days=days_window)
        posture = evaluate_project_ai_security_posture(p)
        p["aiSecurityPosture"] = posture
        if posture.get("evaluated"):
            evaluated_scores.append(posture["score"])
            crit_total += posture.get("criticalCount", 0)
            high_total += posture.get("highCount", 0)
            med_total += posture.get("mediumCount", 0)
            low_total += posture.get("lowCount", 0)
            findings_total += posture.get("findingsCount", 0)
            gov = posture.get("governance", {})
            if gov.get("agentRegistryEnabled"):
                agent_reg_projects += 1
            if gov.get("dlpEnabled"):
                dlp_projects += 1
            if gov.get("iapGatewayEnabled"):
                iap_projects += 1
            if not gov.get("gdprCompliant", True):
                gdpr_non_compliant_projects += 1
            if any(f.get("id") == "MISSING_MODEL_ARMOR" for f in (posture.get("findings") or [])):
                unprotected_ai_projects += 1

        ma_tel = (p.get("modelArmor") or {}).get("threatTelemetry") or {}
        ma_total_logs += ma_tel.get("totalSanitizeLogs", 0)
        ma_flagged += ma_tel.get("flaggedCount", 0)
        ma_blocked += ma_tel.get("blockedCount", 0)
        ma_passed += ma_tel.get("passedCount", 0)
        cats = ma_tel.get("byCategory") or {}
        ma_pi += cats.get("promptInjectionAndJailbreak", 0)
        ma_dlp += cats.get("sdpDlp", 0)
        ma_rai += cats.get("rai", 0)
        ma_uri += cats.get("maliciousUri", 0)

        # Aggregate Data Residency
        dr = p.get("dataResidency") or {}
        for ne_r in (dr.get("nonEuDeployedResources") or []):
            all_non_eu_resources.append(ne_r)
        total_non_eu_requests += int(((dr.get("breakdown") or {}).get("NON_EU_US_OTHER") or {}).get("calls", 0) or 0)
        for r_entry in (dr.get("regions") or []):
            loc_k = r_entry["location"]
            cat_k = r_entry["category"]
            gb = global_reg_map.setdefault(loc_k, {
                "location": loc_k,
                "category": cat_k,
                "calls": 0,
                "tokens": 0,
                "costUsd": 0.0,
                "resourcesCount": 0,
                "projectsCount": 0,
                "projects": []
            })
            gb["calls"] += r_entry.get("calls", 0)
            gb["tokens"] += r_entry.get("tokens", 0)
            gb["costUsd"] = round(gb["costUsd"] + r_entry.get("costUsd", 0.0), 4)
            gb["resourcesCount"] += r_entry.get("resourcesCount", 0)
            gb["projectsCount"] += 1
            if p.get("projectId") not in gb["projects"]:
                gb["projects"].append(p.get("projectId"))
            w_sc = (r_entry.get("costUsd", 0.0) * 1000.0) + (r_entry.get("tokens", 0) / 1000.0) + r_entry.get("calls", 0) + (r_entry.get("resourcesCount", 0) * 50.0)
            if cat_k in cat_weights:
                cat_weights[cat_k] += max(1.0, w_sc)

        # Aggregate FinOps Extended
        fe = p.get("finopsExtended") or {}
        tot_in_tok += fe.get("uncachedInputTokens", 0)
        tot_cached_tok += fe.get("cachedTokens", 0)
        tot_cache_savings += fe.get("cacheSavingsUsd", 0.0)
        tot_potential_extra_savings += fe.get("potentialExtraCacheSavingsUsd", 0.0)
        for idl in (fe.get("idleResources") or []):
            all_idle_resources.append({**idl, "projectId": p.get("projectId")})
        for z_eng in (fe.get("zombieReasoningEngines") or []):
            all_zombie_engines.append(z_eng)

        # Aggregate Agentspace Telemetry
        ast = p.get("agentspaceTelemetry") or {}
        global_as_queries += int(ast.get("totalUserQueries", 0) or 0)
        global_as_convs += int(ast.get("totalConversations", 0) or 0)
        for a_item in (ast.get("apps") or []):
            global_as_apps.append(a_item)
        for d_item in (ast.get("dataStores") or []):
            global_as_ds.append(d_item)

        # Aggregate HTTP Status Breakdown, Latency & Service Breakdown
        p_hb = p.get("httpStatusBreakdown") or {}
        for k_hb in global_http_status:
            global_http_status[k_hb] += int(p_hb.get(k_hb, 0) or 0)
        p_reqs = int(p.get("totalRequests", 0) or 0)
        p_lat = float(p.get("avgLatencyMs", 0.0) or 0.0)
        if p_reqs > 0 and p_lat > 0:
            lat_weighted_sum_all += (p_lat * p_reqs)
            lat_requests_all += p_reqs

        p_svc_seen = set()
        for m_obj in (p.get("models") or []):
            s_name = m_obj.get("service") or "aiplatform.googleapis.com"
            sb = svc_breakdown_map.setdefault(s_name, {
                "service": s_name,
                "requests": 0,
                "inferenceRequests": 0,
                "tokens": 0,
                "costUsd": 0.0,
                "projects": set()
            })
            sb["tokens"] += int(m_obj.get("totalTokens", 0) or 0)
            sb["costUsd"] = round(sb["costUsd"] + float(m_obj.get("costUsd", 0.0) or 0.0), 4)
            sb["projects"].add(p.get("projectId"))
            p_svc_seen.add(s_name)

        for f_obj in (p.get("vertexFeatures") or []):
            s_name = f_obj.get("service") or "aiplatform.googleapis.com"
            f_req = int(f_obj.get("requests", 0) or 0)
            f_inf = int(f_obj.get("inferenceRequests", 0) or 0)
            if f_req > 0 or f_inf > 0:
                sb = svc_breakdown_map.setdefault(s_name, {
                    "service": s_name,
                    "requests": 0,
                    "inferenceRequests": 0,
                    "tokens": 0,
                    "costUsd": 0.0,
                    "projects": set()
                })
                sb["requests"] += f_req
                sb["inferenceRequests"] += f_inf
                sb["projects"].add(p.get("projectId"))

        # Aggregate AI Studio & Notebooks / Tools
        ats = p.get("aiToolsSummary") or {}
        if ats.get("isAiStudioProject"):
            ai_studio_total_keys += ats.get("aiStudioKeysCount", 0)
            ai_studio_total_calls += ats.get("geminiApiRequests", 0)
            ai_studio_total_cost += ats.get("geminiApiCostUsd", 0.0)
            for u_em in (ats.get("aiStudioUsers") or []):
                ai_studio_users_set.add(u_em)
            ai_studio_projects_list.append({
                "projectId": p.get("projectId"),
                "name": p.get("name"),
                "billingEnabled": bool(p.get("billingEnabled", False)),
                "isGenLangClientAutoProject": bool(ats.get("isGenLangClientAutoProject", False)),
                "geminiDeveloperApiEnabled": bool(ats.get("geminiDeveloperApiEnabled", False)),
                "geminiApiRequests": ats.get("geminiApiRequests", 0),
                "geminiApiCostUsd": ats.get("geminiApiCostUsd", 0.0),
                "geminiRequestBytes": ats.get("geminiRequestBytes", 0),
                "geminiResponseBytes": ats.get("geminiResponseBytes", 0),
                "aiStudioKeysCount": ats.get("aiStudioKeysCount", 0),
                "aiStudioKeys": ats.get("aiStudioKeys", []),
                "aiStudioUsers": ats.get("aiStudioUsers", []),
                "scanStatus": p.get("scanStatus", "SCANNED")
            })

        if ats.get("hasNotebooksOrColab"):
            total_notebooklm_calls += ats.get("notebookLmEnterpriseCalls", 0)
            total_colab_calls += ats.get("colabEnterpriseCalls", 0)
            total_colab_resources += ats.get("colabResourcesCount", 0)
            for u_em in (ats.get("notebookUsers") or []):
                notebook_users_set.add(u_em)
            notebooks_projects_list.append({
                "projectId": p.get("projectId"),
                "name": p.get("name"),
                "colabEnterpriseCalls": ats.get("colabEnterpriseCalls", 0),
                "colabResourcesCount": ats.get("colabResourcesCount", 0),
                "colabResources": ats.get("colabResources", []),
                "notebookLmEnterpriseCalls": ats.get("notebookLmEnterpriseCalls", 0),
                "notebookLmMethods": ats.get("notebookLmMethods", []),
                "notebookLmDataStores": ats.get("notebookLmDataStores", []),
                "notebookUsers": ats.get("notebookUsers", []),
                "notebooksApiEnabled": any(a.get("service") == "notebooks.googleapis.com" for a in (p.get("enabledAiApis") or []))
            })

        for u_obj in (p.get("usersUsage") or []):
            ca_c = int(u_obj.get("codeAssistCalls", 0) or 0)
            ca_lines = int(u_obj.get("codeAssistAcceptedLines", 0) or 0)
            ca_acc = int(u_obj.get("codeAssistAcceptedCount", 0) or 0)
            ca_exp = int(u_obj.get("codeAssistExposedCount", 0) or 0)
            if ca_c > 0 or ca_lines > 0 or ca_acc > 0:
                total_code_assist_calls += ca_c
                total_code_assist_accepted_lines += ca_lines
                total_code_assist_accepted_count += ca_acc
                total_code_assist_exposed_count += ca_exp
                for lg in (u_obj.get("codeAssistLanguages") or []):
                    if lg:
                        code_assist_languages_set.add(lg)
                for ws in (u_obj.get("codeAssistWorkspaces") or []):
                    if ws:
                        code_assist_workspaces_set.add(ws)
                if u_obj.get("userEmail"):
                    code_assist_users_set.add(u_obj["userEmail"])

        # Aggregate AI Log Forensics & Security Signals
        lf = p.get("aiLogForensics") or {}
        lf_errors_429 += lf.get("errors429Count", 0)
        lf_failed_calls += lf.get("failedOrDeniedCallsCount", 0)
        lf_unrestricted_keys += lf.get("unrestrictedKeysCount", 0)
        lf_stale_keys += lf.get("staleKeysOver90dCount", 0)
        lf_ghost_keys += lf.get("ghostDeletedKeysWithTrafficCount", 0)
        for gk_n in (lf.get("ghostDeletedKeysNames") or []):
            lf_ghost_keys_list.append(f"{p.get('projectId')}:{gk_n}")
        lf_first_party_keys += lf.get("firstPartyConsoleKeysCount", 0)
        lf_exported_sa_keys += lf.get("exportedSaKeysCount", 0)
        for ext_u in (lf.get("externalUsers") or []):
            lf_external_users_set.add(ext_u)
        if lf.get("unattributedAuditBlindness"):
            lf_unattr_projects += 1
            lf_unattr_tokens += lf.get("unattributedTokens", 0)
            lf_unattr_calls += lf.get("unattributedCalls", 0)
        lf_public_endpoints += lf.get("publicEndpointsCount", 0)
        lf_non_cmek_resources += lf.get("nonCmekResourcesCount", 0)
        lf_weekend_calls += lf.get("weekendCalls", 0)
        lf_weekend_cost += lf.get("weekendCostUsd", 0.0)
        for sp_d in (lf.get("costSpikeDays") or []):
            lf_spike_days_list.append({**sp_d, "projectId": p.get("projectId")})
        for mut_m in (lf.get("adminMutations") or []):
            lf_admin_mutations_map[mut_m] = lf_admin_mutations_map.get(mut_m, 0) + 1
        for kw_tag in (lf.get("securityKeywords") or []):
            base_kw = kw_tag.split(":")[0]
            val_num = 1
            if ":" in kw_tag:
                try:
                    val_num = int(kw_tag.split(":")[1])
                except Exception:
                    val_num = 1
            entry_kw = lf_keywords_counts.setdefault(base_kw, {"projectsCount": 0, "totalEvents": 0})
            entry_kw["projectsCount"] += 1
            entry_kw["totalEvents"] += val_num

    ai_studio_projects_list.sort(key=lambda x: (x["geminiApiCostUsd"], x["geminiApiRequests"], x["aiStudioKeysCount"], not x["billingEnabled"]), reverse=True)
    notebooks_projects_list.sort(key=lambda x: (x["notebookLmEnterpriseCalls"], x["colabResourcesCount"], x["colabEnterpriseCalls"]), reverse=True)

    avg_score = round(sum(evaluated_scores) / len(evaluated_scores)) if evaluated_scores else 100
    if avg_score >= 90:
        g_grade = "A"
    elif avg_score >= 75:
        g_grade = "B"
    elif avg_score >= 60:
        g_grade = "C"
    elif avg_score >= 40:
        g_grade = "D"
    else:
        g_grade = "F"

    tot_w_all = sum(cat_weights.values())
    global_regions_sorted = sorted(global_reg_map.values(), key=lambda x: (x["costUsd"], x["tokens"], x["calls"], x["resourcesCount"]), reverse=True)

    # Recalculate global Infra Cost & Total Bill / TCO after Step 1 normalization
    tot_ai_cost_usd = round(sum(float(p.get("estimatedCostUsd", p.get("costUsd", 0.0)) or 0.0) for p in projects), 4)
    if tot_ai_cost_usd == 0.0 and float(summary.get("estimatedCostUsd", summary.get("totalCostUsd", 0.0)) or 0.0) > 0:
        tot_ai_cost_usd = round(float(summary.get("estimatedCostUsd", summary.get("totalCostUsd", 0.0)) or 0.0), 4)
    tot_ai_gross_usd = round(sum(float(p.get("grossCostUsd", p.get("estimatedCostUsd", 0.0)) or 0.0) for p in projects), 4)
    tot_ai_savings_usd = round(tot_cache_savings, 4)
    tot_infra_cost_usd = round(sum(float(p.get("infraCostUsd", 0.0) or 0.0) for p in projects), 4)
    tot_infra_gross_usd = round(sum(float(p.get("infraGrossCostUsd", 0.0) or 0.0) for p in projects), 4)
    tot_infra_sav_usd = round(sum(float(p.get("infraSavingsUsd", 0.0) or 0.0) for p in projects), 4)
    tot_excl_infra_usd = round(sum(float(p.get("excludedNonAiInfraCostUsd", 0.0) or 0.0) for p in projects), 4)
    tot_bill_cost_usd = round(tot_ai_cost_usd + tot_infra_cost_usd, 4)
    tot_prompt_all = tot_in_tok + tot_cached_tok
    global_cache_hit_pct = round((tot_cached_tok / tot_prompt_all) * 100.0, 2) if tot_prompt_all > 0 else 0.0

    tot_vertex_cost_usd = round(sum(float(p.get("vertexCostUsd", 0.0) or 0.0) for p in projects), 4)
    tot_other_ai_cost_usd = round(sum(float(p.get("otherAiCostUsd", 0.0) or 0.0) for p in projects), 4)
    tot_gemini_cost_usd = round(sum(float(p.get("geminiCostUsd", 0.0) or 0.0) for p in projects), 4)

    summary["vertexCostUsd"] = tot_vertex_cost_usd
    summary["otherAiCostUsd"] = tot_other_ai_cost_usd
    summary["geminiCostUsd"] = tot_gemini_cost_usd
    summary["estimatedCostUsd"] = tot_ai_cost_usd
    summary["totalCostUsd"] = tot_ai_cost_usd
    summary["grossCostUsd"] = max(tot_ai_gross_usd, round(tot_ai_cost_usd + tot_ai_savings_usd, 4))
    summary["cacheSavingsUsd"] = tot_ai_savings_usd
    summary["savedByCachingUsd"] = tot_ai_savings_usd
    summary["cacheHitRatePct"] = global_cache_hit_pct
    summary["infraCostUsd"] = tot_infra_cost_usd
    summary["totalInfraCostUsd"] = tot_infra_cost_usd
    summary["infraGrossCostUsd"] = tot_infra_gross_usd
    summary["infraSavingsUsd"] = tot_infra_sav_usd
    summary["excludedNonAiInfraCostUsd"] = tot_excl_infra_usd
    summary["totalBillCostUsd"] = tot_bill_cost_usd
    summary["totalTcoUsd"] = tot_bill_cost_usd
    summary["totalBillGrossUsd"] = round(float(summary.get("grossCostUsd", tot_ai_cost_usd) or 0.0) + tot_infra_gross_usd, 4)
    summary["totalBillSavingsUsd"] = round(tot_ai_savings_usd + tot_infra_sav_usd, 4)

    summary["securityPosture"] = {
        "averageScore": avg_score,
        "grade": g_grade,
        "evaluatedProjects": len(evaluated_scores),
        "totalFindings": findings_total,
        "criticalFindings": crit_total,
        "highFindings": high_total,
        "mediumFindings": med_total,
        "lowFindings": low_total,
        "unprotectedAiProjects": unprotected_ai_projects,
        "gdprNonCompliantProjects": gdpr_non_compliant_projects,
        "agentRegistryProjects": agent_reg_projects,
        "dlpProjects": dlp_projects,
        "iapGatewayProjects": iap_projects,
        "threatTelemetry": {
            "totalSanitizeLogs": ma_total_logs,
            "flaggedCount": ma_flagged,
            "blockedCount": ma_blocked,
            "passedCount": ma_passed,
            "promptInjectionAndJailbreak": ma_pi,
            "sdpDlp": ma_dlp,
            "rai": ma_rai,
            "maliciousUri": ma_uri
        }
    }

    summary["dataResidency"] = {
        "gdprCompliantProjects": max(0, len(evaluated_scores) - gdpr_non_compliant_projects),
        "gdprNonCompliantProjects": gdpr_non_compliant_projects,
        "italySharePct": round((cat_weights["ITALY_LOCAL"] / tot_w_all) * 100.0, 1) if tot_w_all > 0 else 0.0,
        "euSharePct": round(((cat_weights["ITALY_LOCAL"] + cat_weights["EU_EEA"]) / tot_w_all) * 100.0, 1) if tot_w_all > 0 else 100.0,
        "globalSharePct": round((cat_weights["GLOBAL_ANYCAST"] / tot_w_all) * 100.0, 1) if tot_w_all > 0 else 0.0,
        "nonEuSharePct": round((cat_weights["NON_EU_US_OTHER"] / tot_w_all) * 100.0, 1) if tot_w_all > 0 else 0.0,
        "nonEuDeployedResources": all_non_eu_resources,
        "nonEuResourcesCount": len(all_non_eu_resources),
        "nonEuRequests": total_non_eu_requests,
        "regions": global_regions_sorted
    }

    # Compute 7-day trend vs previous 7 days from payload['timeline'] (Step 4)
    timeline = sorted(payload.get("timeline", []) or [], key=lambda x: str(x.get("date", "")))
    last7_slice = timeline[-7:] if len(timeline) >= 7 else timeline
    prev7_slice = timeline[-14:-7] if len(timeline) >= 14 else []
    last7_cost = round(sum(float(d.get("costUsd", 0.0) or 0.0) for d in last7_slice), 4)
    prev7_cost = round(sum(float(d.get("costUsd", 0.0) or 0.0) for d in prev7_slice), 4)
    cost_trend_7d_pct = round(((last7_cost - prev7_cost) / prev7_cost) * 100.0, 1) if prev7_cost > 0 else 0.0

    last7_reqs = sum(int(d.get("inferenceRequests", d.get("requests", 0)) or 0) for d in last7_slice)
    prev7_reqs = sum(int(d.get("inferenceRequests", d.get("requests", 0)) or 0) for d in prev7_slice)
    reqs_trend_7d_pct = round(((last7_reqs - prev7_reqs) / float(prev7_reqs)) * 100.0, 1) if prev7_reqs > 0 else 0.0

    global_daily_burn_ai = round(tot_ai_cost_usd / days_window, 4)
    global_daily_burn_tco = round(tot_bill_cost_usd / days_window, 4)

    # Compute Project Budgets status (Step 4)
    budgets_cfg = (load_budgets() or {}).get("projects", {}) or {}
    project_budgets_list = []
    for p in projects:
        pid_b = p.get("projectId", "")
        b_cfg_item = budgets_cfg.get(pid_b, {})
        b_val = float(b_cfg_item.get("budgetUsd", p.get("budgetUsd", 0.0)) or 0.0) if isinstance(b_cfg_item, dict) else float(b_cfg_item or p.get("budgetUsd", 0.0) or 0.0)
        spent_ai = round(float(p.get("estimatedCostUsd", p.get("costUsd", 0.0)) or 0.0), 4)
        spent_tco = round(float(p.get("totalBillCostUsd", p.get("totalTcoUsd", spent_ai)) or 0.0), 4)
        fc30 = float((p.get("finopsExtended") or {}).get("forecast30dTcoUsd", 0.0) or 0.0)
        if b_val > 0 and (spent_tco > 0 or int(p.get("inferenceRequests", 0) or 0) > 0 or len(p.get("deployedAiResources", []) or []) > 0 or pid_b in budgets_cfg):
            util_pct = round((spent_tco / b_val) * 100.0, 1)
            b_status_str = "OVER_BUDGET" if util_pct >= 100.0 else ("WARNING" if util_pct >= 80.0 else "OK")
            project_budgets_list.append({
                "projectId": pid_b,
                "projectName": p.get("name", pid_b),
                "budgetUsd": round(b_val, 2),
                "monthlyBudgetUsd": round(b_val, 2),
                "spentAiUsd": spent_ai,
                "costAiUsd": spent_ai,
                "spentTcoUsd": spent_tco,
                "totalTcoUsd": spent_tco,
                "currentSpendUsd": spent_tco,
                "utilizationPct": util_pct,
                "budgetUsedPct": util_pct,
                "forecast30dUsd": round(fc30, 2),
                "forecast30dTcoUsd": round(fc30, 2),
                "status": b_status_str
            })
    project_budgets_list.sort(key=lambda x: (x["utilizationPct"], x["spentTcoUsd"]), reverse=True)

    tot_prompt_all = tot_in_tok + tot_cached_tok
    summary["finopsExtended"] = {
        "cacheHitRatePct": round((tot_cached_tok / tot_prompt_all) * 100.0, 2) if tot_prompt_all > 0 else 0.0,
        "cachedTokens": tot_cached_tok,
        "uncachedInputTokens": tot_in_tok,
        "cacheSavingsUsd": round(tot_cache_savings, 4),
        "potentialExtraCacheSavingsUsd": round(tot_potential_extra_savings, 4),
        "idleResourcesCount": len(all_idle_resources),
        "idleResources": all_idle_resources,
        "estimatedMonthlyIdleWasteUsd": round(sum(x["estimatedMonthlyWasteUsd"] for x in all_idle_resources), 2),
        "zombieReasoningEngines": all_zombie_engines,
        "zombieReasoningEnginesCount": len(all_zombie_engines),
        "dailyBurnRateAiUsd": global_daily_burn_ai,
        "dailyBurnRateTcoUsd": global_daily_burn_tco,
        "forecast30dAiUsd": round(global_daily_burn_ai * 30.0, 2),
        "forecast30dTcoUsd": round(global_daily_burn_tco * 30.0, 2),
        "last7CostUsd": last7_cost,
        "last7dCostUsd": last7_cost,
        "prev7CostUsd": prev7_cost,
        "prev7dCostUsd": prev7_cost,
        "costTrend7dPct": cost_trend_7d_pct,
        "last7Requests": last7_reqs,
        "last7dRequests": last7_reqs,
        "prev7Requests": prev7_reqs,
        "prev7dRequests": prev7_reqs,
        "requestsTrend7dPct": reqs_trend_7d_pct,
        "excludedNonAiInfraCostUsd": tot_excl_infra_usd,
        "projectBudgets": project_budgets_list
    }

    global_as_apps.sort(key=lambda x: (x.get("queriesCount", 0), x.get("activeUsersCount", 0), x.get("name", "")), reverse=True)
    global_as_ds.sort(key=lambda x: (x.get("queriesCount", 0), x.get("activeUsersCount", 0), x.get("name", "")), reverse=True)
    summary["agentspaceTelemetry"] = {
        "totalApps": len(global_as_apps),
        "activeAppsCount": sum(1 for a in global_as_apps if a.get("queriesCount", 0) > 0),
        "totalDataStores": len(global_as_ds),
        "activeDataStoresCount": sum(1 for d in global_as_ds if d.get("queriesCount", 0) > 0),
        "unusedDataStoresCount": sum(1 for d in global_as_ds if d.get("queriesCount", 0) == 0),
        "totalUserQueries": max(global_as_queries, sum(a.get("queriesCount", 0) for a in global_as_apps)),
        "totalConversations": max(global_as_convs, sum(a.get("conversationsCount", 0) for a in global_as_apps)),
        "apps": global_as_apps,
        "dataStores": global_as_ds
    }

    with contextlib.suppress(KeyError, TypeError, ValueError):
        summary["geminiEnterpriseInventory"] = build_global_gemini_enterprise_inventory(projects)

    summary["httpStatusBreakdown"] = global_http_status
    summary["avgLatencyMs"] = round(lat_weighted_sum_all / lat_requests_all, 1) if lat_requests_all > 0 else 0.0
    svc_breakdown_list = []
    for sb_v in svc_breakdown_map.values():
        svc_breakdown_list.append({
            "service": sb_v["service"],
            "requests": sb_v["requests"],
            "inferenceRequests": sb_v["inferenceRequests"],
            "tokens": sb_v["tokens"],
            "costUsd": round(sb_v["costUsd"], 4),
            "projectsCount": len(sb_v["projects"])
        })
    svc_breakdown_list.sort(key=lambda x: (x["costUsd"], x["inferenceRequests"], x["tokens"], x["requests"]), reverse=True)
    summary["serviceBreakdown"] = svc_breakdown_list

    summary["aiToolsOverview"] = {
        "aiStudioProjectsCount": len(ai_studio_projects_list),
        "aiStudioActiveProjectsCount": sum(1 for x in ai_studio_projects_list if x["geminiApiRequests"] > 0 or x["aiStudioKeysCount"] > 0),
        "aiStudioTotalKeys": ai_studio_total_keys,
        "aiStudioTotalCalls": ai_studio_total_calls,
        "aiStudioTotalCostUsd": round(ai_studio_total_cost, 4),
        "aiStudioUsers": sorted(list(ai_studio_users_set)),
        "aiStudioProjects": ai_studio_projects_list,
        "notebooksProjectsCount": len(notebooks_projects_list),
        "notebookLmEnterpriseTotalCalls": total_notebooklm_calls,
        "colabEnterpriseTotalCalls": total_colab_calls,
        "colabResourcesTotalCount": total_colab_resources,
        "notebookUsers": sorted(list(notebook_users_set)),
        "notebooksProjects": notebooks_projects_list,
        "codeAssistTotalCalls": total_code_assist_calls,
        "codeAssistAcceptedLines": total_code_assist_accepted_lines,
        "codeAssistAcceptedCount": total_code_assist_accepted_count,
        "codeAssistExposedCount": total_code_assist_exposed_count,
        "codeAssistAcceptanceRatePct": round(min(100.0, (total_code_assist_accepted_count / float(total_code_assist_exposed_count)) * 100.0), 1) if total_code_assist_exposed_count > 0 else (100.0 if total_code_assist_accepted_count > 0 else 0.0),
        "codeAssistLanguages": sorted(list(code_assist_languages_set)),
        "codeAssistWorkspaces": sorted(list(code_assist_workspaces_set)),
        "codeAssistSeatMonthlyUsd": round(len(code_assist_users_set) * 19.0, 2),
        "codeAssistUsers": sorted(list(code_assist_users_set))
    }

    lf_spike_days_list.sort(key=lambda x: x.get("costUsd", 0.0), reverse=True)
    summary["aiLogForensics"] = {
        "total429Errors": lf_errors_429,
        "totalFailedOrDeniedCalls": lf_failed_calls,
        "unrestrictedKeysCount": lf_unrestricted_keys,
        "staleKeysOver90dCount": lf_stale_keys,
        "ghostDeletedKeysCount": lf_ghost_keys,
        "ghostDeletedKeys": lf_ghost_keys_list[:15],
        "firstPartyConsoleKeysCount": lf_first_party_keys,
        "exportedSaKeysCount": lf_exported_sa_keys,
        "externalUsersCount": len(lf_external_users_set),
        "externalUsers": sorted(list(lf_external_users_set)),
        "unattributedAuditProjectsCount": lf_unattr_projects,
        "unattributedTokens": lf_unattr_tokens,
        "unattributedCalls": lf_unattr_calls,
        "publicEndpointsCount": lf_public_endpoints,
        "nonCmekResourcesCount": lf_non_cmek_resources,
        "weekendCalls": lf_weekend_calls,
        "weekendCostUsd": round(lf_weekend_cost, 4),
        "costSpikeDaysCount": len(lf_spike_days_list),
        "costSpikeDays": lf_spike_days_list[:15],
        "adminMutations": [{"method": k, "projectsCount": v} for k, v in sorted(lf_admin_mutations_map.items(), key=lambda x: (-x[1], x[0]))],
        "securityKeywords": [{"tag": f"{k}:{v['totalEvents']}", "baseTag": k, "projectsCount": v["projectsCount"], "totalEvents": v["totalEvents"]} for k, v in sorted(lf_keywords_counts.items(), key=lambda x: (-x[1]["projectsCount"], -x[1]["totalEvents"], x[0]))]
    }

    # --- 1. summary["serviceAccountsInventory"]: Complete inventory of all Service Accounts across projects ---
    sa_inventory_items = []
    sa_with_keys = 0
    sa_with_expired_keys = 0
    sa_active = 0
    sa_disabled = 0
    for p in projects:
        pid = p.get("projectId", "")
        pname = p.get("name", pid)
        sa_creds_map = {}
        for c_item in (p.get("credentialsUsage") or []):
            if c_item.get("resolvedType") == "SERVICE_ACCOUNT":
                c_email = (c_item.get("email") or c_item.get("displayName") or "").strip().lower()
                if c_email:
                    sa_creds_map[c_email] = c_item
        for sa in (p.get("serviceAccounts") or []):
            sa_email = (sa.get("email") or "").strip()
            sa_c = sa_creds_map.get(sa_email.lower(), {})
            u_keys = int(sa.get("userManagedKeysCount", 0) or 0)
            exp_keys = int(sa.get("expiredOrOldKeysCount", 0) or 0)
            is_dis = bool(sa.get("disabled", False))
            inf_reqs = int(sa.get("inferenceRequests", sa_c.get("inferenceRequests", 0)) or 0)
            tot_reqs = int(sa.get("requests", sa_c.get("requests", 0)) or 0)
            tot_toks = int(sa.get("totalTokens", sa_c.get("totalTokens", 0)) or 0)
            est_cost = round(float(sa.get("estimatedCostUsd", sa_c.get("estimatedCostUsd", 0.0)) or 0.0), 4)
            if u_keys > 0:
                sa_with_keys += 1
            if exp_keys > 0:
                sa_with_expired_keys += 1
            if is_dis:
                sa_disabled += 1
            if inf_reqs > 0 or tot_reqs > 0 or est_cost > 0:
                sa_active += 1
            if exp_keys > 0:
                r_lvl = "CRITICAL"
            elif u_keys > 0:
                r_lvl = "HIGH"
            elif is_dis:
                r_lvl = "LOW"
            else:
                r_lvl = "OK"
            sa_inventory_items.append({
                "email": sa_email,
                "displayName": sa.get("displayName") or (sa_email.split("@")[0] if "@" in sa_email else sa_email),
                "projectId": pid,
                "projectName": pname,
                "disabled": is_dis,
                "userManagedKeysCount": u_keys,
                "expiredOrOldKeysCount": exp_keys,
                "keys": sa.get("keys") or [],
                "requests": tot_reqs,
                "inferenceRequests": inf_reqs,
                "totalTokens": tot_toks,
                "estimatedCostUsd": est_cost,
                "lastSeen": sa.get("lastSeen") or sa_c.get("lastSeen"),
                "modelsUsed": sa.get("modelsUsed") or sa_c.get("modelsUsed") or [],
                "riskLevel": r_lvl
            })
    sa_inventory_items.sort(
        key=lambda x: (
            x.get("expiredOrOldKeysCount", 0) > 0,
            x.get("userManagedKeysCount", 0) > 0,
            x.get("estimatedCostUsd", 0.0),
            x.get("inferenceRequests", 0),
            x.get("requests", 0),
            not x.get("disabled", False)
        ),
        reverse=True
    )
    summary["serviceAccountsInventory"] = {
        "totalCount": len(sa_inventory_items),
        "activeWithTrafficCount": sa_active,
        "withExportedKeysCount": sa_with_keys,
        "withExpiredKeysCount": sa_with_expired_keys,
        "disabledCount": sa_disabled,
        "items": sa_inventory_items
    }

    # --- 2. summary["mcpAndAgentRegistry"]: Dedicated aggregation for MCP servers, Agents, Reasoning Engines & Dialogflow CX ---
    mcp_servers_list = []
    agents_list = []
    reasoning_engines_list = []
    dialogflow_agents_list = []
    mcp_projects_set = set()
    dup_re_groups = 0
    for p in projects:
        pid = p.get("projectId", "")
        pname = p.get("name", pid)
        for r_obj in (p.get("deployedAiResources") or []):
            rt = str(r_obj.get("type") or r_obj.get("resourceType") or "").upper()
            if rt not in ("AGENT_REGISTRY_MCP", "AGENT_REGISTRY_MCP_SERVER", "AGENT_REGISTRY_AGENT", "REASONING_ENGINE", "DIALOGFLOW_CX_AGENT"):
                continue
            r_loc = str(r_obj.get("region") or r_obj.get("location") or "global")
            entry = {
                "projectId": pid,
                "projectName": pname,
                "type": rt,
                "resourceType": rt,
                "typeLabel": r_obj.get("typeLabel") or rt,
                "name": r_obj.get("name") or r_obj.get("displayName") or "",
                "displayName": r_obj.get("displayName") or r_obj.get("name") or "",
                "resourceId": r_obj.get("resourceId") or "",
                "region": r_loc,
                "location": r_loc,
                "residencyCategory": classify_gcp_region_residency(r_loc),
                "state": r_obj.get("state") or "ACTIVE",
                "detail": r_obj.get("detail") or "",
                "consoleUrl": r_obj.get("consoleUrl") or "",
                "createTime": r_obj.get("createTime"),
                "updateTime": r_obj.get("updateTime"),
                "isDuplicateGroup": bool(r_obj.get("isDuplicateGroup", False)),
                "duplicateGroupSize": int(r_obj.get("duplicateGroupSize", 1) or 1),
                "duplicateRegions": r_obj.get("duplicateRegions") or [r_loc],
                "duplicateBaseName": r_obj.get("duplicateBaseName") or (r_obj.get("name") or "")
            }
            mcp_projects_set.add(pid)
            if rt in ("AGENT_REGISTRY_MCP", "AGENT_REGISTRY_MCP_SERVER"):
                mcp_servers_list.append(entry)
            elif rt == "AGENT_REGISTRY_AGENT":
                agents_list.append(entry)
            elif rt == "REASONING_ENGINE":
                reasoning_engines_list.append(entry)
            elif rt == "DIALOGFLOW_CX_AGENT":
                dialogflow_agents_list.append(entry)
        p_dup = (p.get("dataResidency") or {}).get("duplicateDeployments") or (p.get("finopsExtended") or {}).get("zombieReasoningEngines") or []
        dup_re_groups += len(p_dup)

    all_agent_mcp_items = mcp_servers_list + agents_list + reasoning_engines_list + dialogflow_agents_list
    summary["mcpAndAgentRegistry"] = {
        "totalCount": len(all_agent_mcp_items),
        "mcpServersCount": len(mcp_servers_list),
        "agentRegistryAgentsCount": len(agents_list),
        "reasoningEnginesCount": len(reasoning_engines_list),
        "dialogflowAgentsCount": len(dialogflow_agents_list),
        "projectsCount": len(mcp_projects_set),
        "duplicateGroupsCount": dup_re_groups,
        "mcpServers": mcp_servers_list,
        "agents": agents_list,
        "reasoningEngines": reasoning_engines_list,
        "dialogflowAgents": dialogflow_agents_list,
        "items": all_agent_mcp_items
    }

    # --- 3. summary["modelArmorMatrix"]: Explicit regional coverage matrix across active Enterprise/Vertex AI projects ---
    ma_matrix_projects = []
    ma_protected_count = 0
    ma_unprotected_count = 0
    ma_partial_count = 0
    for p in projects:
        pid = p.get("projectId", "")
        pname = p.get("name", pid)
        v_reqs = int(p.get("vertexRequests", 0) or 0)
        g_reqs = int(p.get("geminiApiRequests", 0) or 0)
        inf_reqs_p = int(p.get("inferenceRequests", 0) or 0)
        other_reqs_p = max(0, inf_reqs_p - v_reqs - g_reqs)
        en_apis_p = {a.get("service", "") for a in (p.get("enabledAiApis", []) or [])}
        has_enterprise_ai = bool(
            v_reqs > 0
            or other_reqs_p > 0
            or len(p.get("deployedAiResources") or []) > 0
            or ("aiplatform.googleapis.com" in en_apis_p and (inf_reqs_p > g_reqs or (p.get("totalRequests", 0) or 0) > g_reqs))
            or ("discoveryengine.googleapis.com" in en_apis_p and (p.get("totalRequests", 0) or 0) > 0)
        )
        if not has_enterprise_ai and not p.get("modelArmorEnabled"):
            continue
        ma_obj = p.get("modelArmor") or {}
        ma_enabled = bool(p.get("modelArmorEnabled") or ma_obj.get("enabled"))
        templates = ma_obj.get("templates") or []
        covered_regions = sorted(list({str(t.get("location") or t.get("region") or "global") for t in templates if t.get("location") or t.get("region")}))
        rr = p.get("dataResidency") or {}
        active_regions = sorted([
            str(r_b.get("location"))
            for r_b in (rr.get("regions") or [])
            if (r_b.get("calls", 0) > 0 or r_b.get("tokens", 0) > 0 or r_b.get("costUsd", 0.0) > 0 or r_b.get("resourcesCount", 0) > 0)
            and r_b.get("location")
            and "AI Studio" not in str(r_b.get("location"))
        ])
        uncovered_regions = [r_loc for r_loc in active_regions if r_loc not in covered_regions and r_loc != "global"]
        floor_s = ma_obj.get("floorSetting") or {}
        floor_enforced = bool(
            (floor_s.get("enforcementEnabled") or floor_s.get("enableFloorSettingEnforcement")) if isinstance(floor_s, dict) else False
        ) or ma_obj.get("status") in ("INSPECT_AND_BLOCK", "FLOOR_PROTECTED")
        ma_tel_p = ma_obj.get("threatTelemetry") or {}
        san_logs_p = int(ma_tel_p.get("totalSanitizeLogs", 0) or 0)
        flag_cnt_p = int(ma_tel_p.get("flaggedCount", 0) or 0)
        blk_cnt_p = int(ma_tel_p.get("blockedCount", 0) or 0)

        if (ma_enabled and len(templates) > 0) or floor_enforced:
            if uncovered_regions and not floor_enforced:
                cov_status = "PARTIAL_REGIONAL_GAP"
                ma_partial_count += 1
            else:
                cov_status = "PROTECTED"
                ma_protected_count += 1
        elif ma_enabled:
            cov_status = "ENABLED_NO_TEMPLATES"
            ma_partial_count += 1
        else:
            cov_status = "UNPROTECTED"
            ma_unprotected_count += 1

        target_tpl_loc = uncovered_regions[0] if uncovered_regions else (active_regions[0] if active_regions and active_regions[0] != "global" else "europe-west8")
        if target_tpl_loc in ("eu", "us", "global"):
            target_tpl_loc = "europe-west1" if target_tpl_loc == "eu" else ("us-central1" if target_tpl_loc == "us" else "europe-west8")

        verify_cmd_p = f"gcloud model-armor floorsettings describe --full-uri=projects/{pid}/locations/global/floorSetting && gcloud model-armor templates list --project={pid} --location={target_tpl_loc}"
        if cov_status == "UNPROTECTED":
            rem_cmd_p = (
                f"gcloud services enable modelarmor.googleapis.com --project={pid} && "
                f"gcloud model-armor floorsettings update --full-uri=projects/{pid}/locations/global/floorSetting "
                f"--enable-floor-setting-enforcement=true "
                f"--pi-and-jailbreak-filter-settings-enforcement=ENABLED "
                f"--pi-and-jailbreak-filter-settings-confidence-level=MEDIUM_AND_ABOVE "
                f"--malicious-uri-filter-settings-enforcement=ENABLED"
            )
        elif cov_status in ("ENABLED_NO_TEMPLATES", "PARTIAL_REGIONAL_GAP"):
            rem_cmd_p = (
                f"gcloud model-armor templates create enterprise-guardrail --project={pid} --location={target_tpl_loc} "
                f"--pi-and-jailbreak-filter-settings-enforcement=ENABLED "
                f"--pi-and-jailbreak-filter-settings-confidence-level=MEDIUM_AND_ABOVE "
                f"--malicious-uri-filter-settings-enforcement=ENABLED "
                f"--rai-settings-filters=\"filterType=DANGEROUS,confidenceLevel=MEDIUM_AND_ABOVE\""
            )
        else:
            rem_cmd_p = verify_cmd_p

        ma_matrix_projects.append({
            "projectId": pid,
            "projectName": pname,
            "enabled": ma_enabled,
            "status": ma_obj.get("status", "ENABLED" if ma_enabled else "DISABLED"),
            "statusLabel": ma_obj.get("statusLabel", "Enabled" if ma_enabled else "Not enabled"),
            "coverageStatus": cov_status,
            "templatesCount": len(templates),
            "templates": templates,
            "coveredRegions": covered_regions,
            "templateRegions": covered_regions,
            "activeAiRegions": active_regions,
            "callRegions": active_regions,
            "uncoveredActiveRegions": uncovered_regions,
            "floorSetting": floor_s,
            "floorEnforcement": floor_enforced,
            "sanitizeLogs": san_logs_p,
            "flaggedCount": flag_cnt_p,
            "blockedCount": blk_cnt_p,
            "verifyCmd": verify_cmd_p,
            "remediationCmd": rem_cmd_p,
            "inferenceRequests": inf_reqs_p,
            "estimatedCostUsd": round(float(p.get("estimatedCostUsd", 0.0) or 0.0), 4),
            "resourcesCount": len(p.get("deployedAiResources") or [])
        })

    ma_matrix_projects.sort(
        key=lambda x: (
            x.get("enabled", False),
            x.get("templatesCount", 0),
            x.get("estimatedCostUsd", 0.0),
            x.get("inferenceRequests", 0)
        ),
        reverse=True
    )
    summary["modelArmorMatrix"] = {
        "totalEvaluatedProjects": len(ma_matrix_projects),
        "protectedProjectsCount": ma_protected_count,
        "partialCoverageProjectsCount": ma_partial_count,
        "unprotectedProjectsCount": ma_unprotected_count,
        "projects": ma_matrix_projects,
        "items": ma_matrix_projects
    }

    tl = payload.get("timeline") or []
    p_days = int(payload.get("days", 30) or 30)
    if tl:
        start_d = tl[0].get("date")
        end_d = tl[-1].get("date")
    else:
        end_d = get_today_date_str()
        start_d = (datetime.now() - timedelta(days=max(0, p_days - 1))).strftime("%Y-%m-%d")
    payload["periodRange"] = {
        "days": p_days,
        "startDate": start_d,
        "endDate": end_d
    }

    return payload


