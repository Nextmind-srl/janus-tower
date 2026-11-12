# =============================================================================
# GEMINI ENTERPRISE (GOOGLE AGENTSPACE) 360° DEEP DISCOVERY & INVENTORY MODULE
# 100% Read-Only (GET / list / read-only v1alpha & v1beta + Cloud Audit Logs)
# =============================================================================

import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor


# Catalogo descrittivo delle Feature Flag di Gemini Enterprise / Agentspace
GEMINI_ENTERPRISE_FEATURES_CATALOG = {
    "model-selector": {
        "label": "LLM Model Selector (User Dropdown)",
        "category": "Models & Routing",
        "description": "Lets users choose the Gemini model (e.g. 2.5 Pro, 2.5 Flash) in the chat bar."
    },
    "agent-gallery": {
        "label": "Enterprise Agent Gallery",
        "category": "Agents & AI Assistants",
        "description": "Enables the catalog of enterprise and custom Agents inside the Gemini Enterprise interface."
    },
    "no-code-agent-builder": {
        "label": "No-Code Agent Builder (User-Created Agents)",
        "category": "Agents & AI Assistants",
        "description": "Allows authorized users to create, configure and test custom No-Code Agents."
    },
    "agent-sharing": {
        "label": "Agent Sharing Across Users/Teams",
        "category": "Agents & AI Assistants",
        "description": "Allows sharing created Agents with other users or submitting them for IAM approval."
    },
    "vertex-agent-builder": {
        "label": "Vertex AI Agent Builder (ADK) Integration",
        "category": "Agents & AI Assistants",
        "description": "Connects Agents built on Vertex AI Agent Engine / Dialogflow CX to Gemini Enterprise."
    },
    "deep-research": {
        "label": "Deep Research (In-Depth Multi-Step Research)",
        "category": "Search & RAG",
        "description": "Enables the autonomous multi-step research agent for complex reports on internal and web sources."
    },
    "notebook-lm": {
        "label": "NotebookLM Enterprise Workspace",
        "category": "Productivity & Notebooks",
        "description": "Integrates NotebookLM Enterprise for document summarization, Audio Overview and shared notebooks."
    },
    "grounding-with-google-search": {
        "label": "Grounding with Google Search (Live Web)",
        "category": "Search & RAG",
        "description": "Enriches assistant answers with up-to-date results from public Google Search."
    },
    "enterprise-search": {
        "label": "Unified Enterprise Search (Blended RAG)",
        "category": "Search & RAG",
        "description": "Federated search across all DataStores and enterprise connectors linked to the App."
    },
    "people-search": {
        "label": "People & Org Chart Search (People Search)",
        "category": "Workspace & Directory",
        "description": "Searches company profiles, contacts and roles via Google Workspace / Cloud Identity."
    },
    "workspace-Jumpstart-cards": {
        "label": "Google Workspace Smart Cards (Jumpstart)",
        "category": "Workspace & Directory",
        "description": "Shows quick summaries of Gmail, Calendar, Drive and Docs on the Gemini Enterprise home page."
    },
    "chat-history": {
        "label": "Persistent Conversation History",
        "category": "User Experience",
        "description": "Saves and syncs the user's chat sessions so previous conversations can be resumed."
    },
    "prompt-gallery": {
        "label": "Enterprise Prompt Gallery",
        "category": "User Experience",
        "description": "Suggests preconfigured prompts and best practices when the App opens."
    },
    "feedback": {
        "label": "Response Feedback (Thumbs Up/Down)",
        "category": "Governance & Quality",
        "description": "Allows users to submit feedback on the quality of generated responses."
    },
    "bi-connectors": {
        "label": "Business Intelligence Connectors (Looker / BI)",
        "category": "Connectors & Data",
        "description": "Enables conversational querying of BI sources and structured datasets."
    },
    "slack-bot": {
        "label": "Slack Bot Integration",
        "category": "Canali & ChatOps",
        "description": "Exposes the Gemini Enterprise assistant as a bot inside Slack channels."
    }
}


# Metodi Cloud Audit Logs che indicano creazione/gestione Agenti o OAuth Connettori
AGENT_LIFECYCLE_METHODS_MAP = {
    "CreateAgent": {"label": "Agent Creation", "badge": "CREATE", "severity": "HIGH"},
    "UpdateAgent": {"label": "Agent Configuration Update", "badge": "UPDATE", "severity": "MEDIUM"},
    "DeployLowCodeAgent": {"label": "Low-Code/No-Code Agent Deployment", "badge": "DEPLOY", "severity": "HIGH"},
    "DeleteAgent": {"label": "Agent Deletion", "badge": "DELETE", "severity": "MEDIUM"},
    "CreateAgentIntegrationProposal": {"label": "Agent Publication Proposal", "badge": "PROPOSAL", "severity": "HIGH"},
    "CancelAgentIntegrationProposal": {"label": "Agent Proposal Revocation", "badge": "CANCEL_PROPOSAL", "severity": "LOW"},
    "RequestAgentReview": {"label": "Agent Approval/Review Request", "badge": "REVIEW", "severity": "HIGH"},
    "ListAgentIamProposals": {"label": "Agent IAM Proposals Lookup", "badge": "IAM_AUDIT", "severity": "LOW"},
    "ListLowcodeAgents": {"label": "Low-Code Agents List", "badge": "LIST", "severity": "LOW"},
    "ListAvailableAgentViews": {"label": "Agent Views Catalog", "badge": "VIEWS", "severity": "LOW"},
    "RetrieveRequestableAgents": {"label": "Requestable Agents Search", "badge": "DISCOVER", "severity": "LOW"},
    "Agent:root_agent": {"label": "Root Agent Orchestrator Execution", "badge": "RUNTIME", "severity": "MEDIUM"}
}

CONNECTOR_OAUTH_METHODS_MAP = {
    "AcquireAndStoreRefreshToken": "Connector OAuth Refresh Token Registration / Storage",
    "AcquireAccessToken": "Third-Party Connector Access Token Acquisition",
    "CheckRefreshToken": "Connector Refresh Token Validity Check",
    "RemoveRefreshToken": "Connector Refresh Token Revocation / Removal",
    "GetWorkspaceSettings": "Workspace & Connectors Configuration Read"
}

if "classify_gcp_region_residency" not in globals():
    def classify_gcp_region_residency(loc: str) -> str:
        l_str = str(loc or "eu").lower()
        if l_str.startswith("eu") or l_str == "eu":
            return "EU"
        if l_str.startswith("us") or l_str == "us":
            return "US"
        if l_str == "global":
            return "GLOBAL"
        return "OTHER"



def _is_login_within_days(last_login, days: int = 30, now=None) -> bool:
    """True if an RFC3339 timestamp falls within the last `days` days (UTC). Empty/invalid = False."""
    text = str(last_login or "").strip()
    if not text:
        return False
    # Normalise 'Z' and trim fractional seconds to microseconds (APIs may send nanoseconds).
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return dt >= current - timedelta(days=days)

def _extract_epoch_ms_from_id(resource_id: str) -> str:
    """
    Estrae il timestamp di creazione da ID generati da Google Agentspace
    (es. 'confluence-wiki-v2_1775207764093_page' o 'docusign_1774732305683_documents').
    """
    if not resource_id:
        return ""
    m = re.search(r"(?:^|_)(1[6789]\d{11})(?:_|$)", str(resource_id))
    if not m:
        return ""
    try:
        ms = int(m.group(1))
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _mask_sensitive_connector_params(params: dict) -> dict:
    """
    Maschera eventuali chiavi segrete / password / token nei parametri del connettore,
    preservando URL, host, instance, client_id, account, tenant, progetti e flag.
    """
    if not isinstance(params, dict):
        return {}
    safe = {}
    sensitive_kw = ("secret", "password", "token", "private_key", "apikey", "api_key", "credential", "cert")
    for k, v in params.items():
        k_low = str(k).lower()
        if any(s in k_low for s in sensitive_kw):
            val_str = str(v or "")
            if len(val_str) > 6:
                safe[k] = f"{val_str[:3]}•••[MASKED len={len(val_str)}]"
            else:
                safe[k] = "•••[CONFIGURED]"
        else:
            safe[k] = v
    return safe


def classify_connector_hub(ds_id: str, ds_name: str = "", raw_ds: dict = None) -> dict:
    """
    Classifica un DataStore o DataConnector di Gemini Enterprise / Agentspace
    identificando la famiglia del connettore (Confluence, DocuSign, Workspace, GCP Asset, ecc.),
    l'ID dell'Hub padre, l'entità specifica (es. space, page, envelopes, firewall_rules),
    il metodo di autenticazione e i dettagli tecnici recuperabili.
    """
    raw_ds = raw_ds or {}
    sid = str(ds_id or "").strip()
    sname = str(ds_name or sid).strip()
    combined_low = f"{sid} {sname}".lower()

    hub_id = sid
    entity_name = "default"
    m_hub = re.match(r"^([a-zA-Z0-9_-]+?_1[6789]\d{11})(?:_(.+))?$", sid)
    if m_hub:
        hub_id = m_hub.group(1)
        entity_name = m_hub.group(2) or "main"
    elif "_" in sid:
        parts = sid.split("_")
        if len(parts) >= 2:
            entity_name = parts[-1]

    created_iso = (raw_ds.get("createTime") or "") or _extract_epoch_ms_from_id(sid)

    if "wiki" in combined_low or "confluence" in combined_low:
        return {
            "family": "CONFLUENCE",
            "familyLabel": "📘 Atlassian Confluence / Wiki",
            "vendor": "Atlassian Confluence",
            "icon": "📘",
            "hubId": hub_id if "17" in hub_id else "confluence-wiki-hub",
            "hubDisplayName": "Confluence Wiki Enterprise Connector (" + (hub_id.split("_")[0] if "_" in hub_id else hub_id) + ")",
            "entityName": entity_name,
            "authModel": "OAuth 2.0 / Atlassian API Token (Secret Manager / Discovery Engine Federated Auth)",
            "syncProtocol": "Discovery Engine Third-Party Federated Connector (v1alpha DataConnector)",
            "createdTime": created_iso,
            "isThirdPartySaaS": True
        }

    if "docusign" in combined_low:
        return {
            "family": "DOCUSIGN",
            "familyLabel": "✍️ DocuSign eSignature",
            "vendor": "DocuSign",
            "icon": "✍️",
            "hubId": hub_id if "17" in hub_id else "docusign-hub",
            "hubDisplayName": "DocuSign Enterprise Connector (" + (hub_id.split("_")[0] if "_" in hub_id else hub_id) + ")",
            "entityName": entity_name,
            "authModel": "DocuSign OAuth 2.0 / Integration Key + Refresh Token (AcquireAndStoreRefreshToken)",
            "syncProtocol": "Discovery Engine Third-Party SaaS Connector (v1alpha DataConnector)",
            "createdTime": created_iso,
            "isThirdPartySaaS": True
        }

    if "gcp-asset" in combined_low or "asset-inven" in combined_low or "cloud_asset" in combined_low or sid.startswith("gcp-"):
        clean_ent = entity_name.replace("gcp_", "")
        return {
            "family": "GCP_ASSET_INVENTORY",
            "familyLabel": "☁️ GCP Cloud Asset Inventory",
            "vendor": "Google Cloud Platform",
            "icon": "☁️",
            "hubId": hub_id if "17" in hub_id else "gcp-asset-inventory-hub",
            "hubDisplayName": "GCP Cloud Asset Inventory Connector (" + (hub_id.split("_")[0] if "_" in hub_id else "gcp-asset-inven") + ")",
            "entityName": clean_ent,
            "authModel": "Service Agent IAM (service-PROJECT_NUMBER@gcp-sa-discoveryengine.iam.gserviceaccount.com)",
            "syncProtocol": "Cloud Asset Inventory Native Connector",
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "notebooklm" in combined_low:
        return {
            "family": "NOTEBOOKLM",
            "familyLabel": "📓 NotebookLM Enterprise",
            "vendor": "Google NotebookLM",
            "icon": "📓",
            "hubId": hub_id,
            "hubDisplayName": sname or "NotebookLM Enterprise Connection",
            "entityName": "notebook_corpus",
            "authModel": "Google Identity / Workforce Pool IAM",
            "syncProtocol": "NotebookLM Enterprise Grounding Store",
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    gws_suite_label = "Google Workspace Enterprise Connector Suite"
    gws_family_label = "✉️ Google Workspace (Gmail, Drive, Calendar, Chat)"
    gws_hub_id = "google-workspace-federated-hub"
    gws_sync_proto = "Google Workspace Real-Time Federated Connector"
    gws_oauth_model = "Google Workspace OAuth 3LO / Domain-Wide Delegation"

    if any(w in combined_low for w in ("gmail", "mail", "google_mail")):
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "✉️",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "gmail",
            "authModel": gws_oauth_model,
            "syncProtocol": gws_sync_proto,
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "drive" in combined_low:
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "📁",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "google_drive",
            "authModel": gws_oauth_model,
            "syncProtocol": gws_sync_proto,
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "calendar" in combined_low:
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "📅",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "google_calendar",
            "authModel": gws_oauth_model,
            "syncProtocol": gws_sync_proto,
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "chat" in combined_low:
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "💬",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "google_chat",
            "authModel": gws_oauth_model,
            "syncProtocol": gws_sync_proto,
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "groups" in combined_low:
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "👥",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "google_groups",
            "authModel": "Google Workspace Directory Sync",
            "syncProtocol": gws_sync_proto,
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if any(w in combined_low for w in ("contacts", "people", "users")):
        return {
            "family": "GOOGLE_WORKSPACE",
            "familyLabel": gws_family_label,
            "vendor": "Google Workspace",
            "icon": "🪪",
            "hubId": gws_hub_id,
            "hubDisplayName": gws_suite_label,
            "entityName": "directory_people_contacts",
            "authModel": "Google Cloud Identity / People Directory API",
            "syncProtocol": "Google Workspace People & Directory Connector",
            "createdTime": created_iso,
            "isThirdPartySaaS": False
        }

    if "jira" in combined_low:
        return {
            "family": "JIRA",
            "familyLabel": "🟦 Atlassian Jira",
            "vendor": "Atlassian Jira",
            "icon": "🟦",
            "hubId": hub_id,
            "hubDisplayName": f"Atlassian Jira Connector ({hub_id})",
            "entityName": entity_name,
            "authModel": "Atlassian OAuth 2.0 / API Token",
            "syncProtocol": "Discovery Engine Third-Party SaaS Connector",
            "createdTime": created_iso,
            "isThirdPartySaaS": True
        }

    if any(w in combined_low for w in ("sharepoint", "onedrive", "microsoft", "entra", "outlook", "teams")):
        return {
            "family": "MICROSOFT_365",
            "familyLabel": "🟦 Microsoft 365 / SharePoint",
            "vendor": "Microsoft 365",
            "icon": "🟦",
            "hubId": hub_id,
            "hubDisplayName": f"Microsoft 365 / SharePoint Connector ({hub_id})",
            "entityName": entity_name,
            "authModel": "Entra ID OAuth 2.0 (Client ID / Tenant ID / Secret)",
            "syncProtocol": "Discovery Engine Third-Party SaaS Connector",
            "createdTime": created_iso,
            "isThirdPartySaaS": True
        }

    return {
        "family": "ENTERPRISE_DATASTORE",
        "familyLabel": "🗄️ Enterprise DataStore / Custom RAG",
        "vendor": "Google Cloud Discovery Engine",
        "icon": "🗄️",
        "hubId": hub_id,
        "hubDisplayName": sname or sid,
        "entityName": entity_name,
        "authModel": "GCP IAM / Discovery Engine ACL",
        "syncProtocol": "Discovery Engine Native DataStore",
        "createdTime": created_iso,
        "isThirdPartySaaS": False
    }


def discover_gemini_enterprise_deep(pid: str, token: str, locations=None) -> dict:
    """
    Esegue una discovery approfondita 100% Read-Only su discoveryengine.googleapis.com (v1alpha / v1)
    per estrarre:
    - Collections (default_collection + tutte le collection di connettori es. confluence-wiki-v2_*, docusign_*, gcp-asset-inven_*)
    - DataConnector (GET /v1alpha/{collection}/dataConnector) con dataSource, params mascherati, stato sync, entità, errori
    - Engines (App Gemini Enterprise / Agentspace) + sub-resources (assistants, agents, widgetConfigs, servingConfigs, controls)
    - DataStores + attributi ACL, CMEK, contentConfig, schema
    """
    locs = locations or ["global", "eu", "us"]
    result = {
        "collections": [],
        "connectors": [],
        "engines": [],
        "assistants": [],
        "agents": [],
        "dataStores": [],
        "aclConfigs": [],
        "licensePools": {}
    }

    init_tasks = []
    for loc in locs:
        host = f"{loc}-discoveryengine.googleapis.com" if loc in ("eu", "us") else "discoveryengine.googleapis.com"
        base_loc = f"https://{host}/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}"
        init_tasks.append(("collections", loc, host, f"{base_loc}/collections"))
        init_tasks.append(("defaultEngines", loc, host, f"{base_loc}/collections/default_collection/engines"))
        init_tasks.append(("defaultDataStores", loc, host, f"{base_loc}/collections/default_collection/dataStores"))
        init_tasks.append(("aclConfig", loc, host, f"{base_loc}/aclConfig"))
        init_tasks.append(("userLicenses", loc, host, f"{base_loc}/userStores/default_user_store/userLicenses?pageSize=1000"))

    def _run_init(t):
        kind, loc, host, url = t
        st, data = gcp_api_get(url, token, timeout=5, user_project=pid)
        return kind, loc, host, st, data

    discovered_collections = []
    seen_cols = set()
    for loc in locs:
        host = f"{loc}-discoveryengine.googleapis.com" if loc in ("eu", "us") else "discoveryengine.googleapis.com"
        seen_cols.add((loc, "default_collection"))
        discovered_collections.append((loc, host, "default_collection", {"name": f"projects/{pid}/locations/{loc}/collections/default_collection", "displayName": "default_collection"}))

    raw_engines = []
    raw_datastores = []
    raw_user_licenses_by_loc = {}
    license_config_paths = set()
    seen_eng_names = set()
    seen_ds_names = set()

    with ThreadPoolExecutor(max_workers=min(20, max(1, len(init_tasks)))) as ex:
        for kind, loc, host, st, data in ex.map(_run_init, init_tasks):
            if st != 200 or not isinstance(data, dict):
                continue
            if kind == "collections":
                for col in data.get("collections", []):
                    c_name = col.get("name", "")
                    c_id = c_name.split("/")[-1] if c_name else ""
                    if c_id and (loc, c_id) not in seen_cols:
                        seen_cols.add((loc, c_id))
                        discovered_collections.append((loc, host, c_id, col))
                        result["collections"].append({
                            "collectionId": c_id,
                            "displayName": col.get("displayName") or c_id,
                            "location": loc,
                            "createTime": col.get("createTime") or _extract_epoch_ms_from_id(c_id)
                        })
            elif kind == "defaultEngines":
                for eng in data.get("engines", []):
                    e_name = eng.get("name", "")
                    if e_name and e_name not in seen_eng_names:
                        seen_eng_names.add(e_name)
                        raw_engines.append((loc, host, "default_collection", eng))
            elif kind == "defaultDataStores":
                for ds in data.get("dataStores", []):
                    d_name = ds.get("name", "")
                    if d_name and d_name not in seen_ds_names:
                        seen_ds_names.add(d_name)
                        raw_datastores.append((loc, host, "default_collection", ds))
            elif kind == "aclConfig":
                result["aclConfigs"].append({
                    "location": loc,
                    "name": data.get("name", ""),
                    "idpConfig": data.get("idpConfig", {})
                })
            elif kind == "userLicenses":
                ul_list = data.get("userLicenses") or []
                raw_user_licenses_by_loc[loc] = ul_list
                for ul in ul_list:
                    lc_path = ul.get("licenseConfig") or ""
                    if lc_path:
                        license_config_paths.add((loc, host, lc_path))

    # Fetch licenseConfigs details (state: ACTIVE vs EXPIRED, licenseCount, startDate, endDate, freeTrial)
    license_configs_by_path = {}
    if license_config_paths:
        def _fetch_lc(item):
            loc, host, lc_path = item
            st, d = gcp_api_get(f"https://{host}/v1alpha/{lc_path}", token, timeout=4, user_project=pid)
            return lc_path, st, d
        with ThreadPoolExecutor(max_workers=min(8, len(license_config_paths))) as ex:
            for lc_path, st, d in ex.map(_fetch_lc, license_config_paths):
                if st == 200 and isinstance(d, dict):
                    sd = d.get("startDate") or {}
                    ed = d.get("endDate") or {}
                    start_str = f"{sd.get('year', 0):04d}-{sd.get('month', 1):02d}-{sd.get('day', 1):02d}" if sd.get("year") else ""
                    end_str = f"{ed.get('year', 0):04d}-{ed.get('month', 1):02d}-{ed.get('day', 1):02d}" if ed.get("year") else ""
                    license_configs_by_path[lc_path] = {
                        "name": lc_path,
                        "licenseConfigId": lc_path.split("/")[-1],
                        "state": d.get("state") or "UNKNOWN",
                        "licenseCount": int(d.get("licenseCount", 0) or 0),
                        "freeTrial": bool(d.get("freeTrial", False)),
                        "subscriptionTier": str(d.get("subscriptionTier") or "").replace("SUBSCRIPTION_TIER_", ""),
                        "subscriptionTerm": str(d.get("subscriptionTerm") or "").replace("SUBSCRIPTION_TERM_", ""),
                        "startDate": start_str,
                        "endDate": end_str
                    }

    # Build licensePool summary per location
    for loc, ul_list in raw_user_licenses_by_loc.items():
        loc_configs = [cfg for path, cfg in license_configs_by_path.items() if f"/locations/{loc}/" in path]
        has_active_cfg = any(c.get("state") == "ACTIVE" for c in loc_configs)
        has_expired_cfg = any(c.get("state") == "EXPIRED" for c in loc_configs)
        pool_state = "ACTIVE" if has_active_cfg else ("EXPIRED" if has_expired_cfg else ("ASSIGNED" if ul_list else "NONE"))
        total_seats = sum(c.get("licenseCount", 0) for c in loc_configs if c.get("state") == "ACTIVE") or sum(c.get("licenseCount", 0) for c in loc_configs)
        assigned_users = []
        blocked_users = []
        active_30d = 0
        for ul in ul_list:
            u_princ = str(ul.get("userPrincipal") or "").strip()
            a_state = str(ul.get("licenseAssignmentState") or "")
            last_login = str(ul.get("lastLoginTime") or "")
            lc_ref = license_configs_by_path.get(ul.get("licenseConfig") or "", {})
            if a_state == "ASSIGNED":
                assigned_users.append({"email": u_princ, "lastLoginTime": last_login, "configState": lc_ref.get("state") or pool_state})
                if _is_login_within_days(last_login, 30):
                    active_30d += 1
            elif a_state == "NO_LICENSE_ATTEMPTED_LOGIN":
                blocked_users.append({"email": u_princ, "lastLoginTime": last_login})
        assigned_users.sort(key=lambda x: x.get("lastLoginTime") or "", reverse=True)
        blocked_users.sort(key=lambda x: x.get("lastLoginTime") or "", reverse=True)
        result["licensePools"][loc] = {
            "location": loc,
            "state": pool_state,
            "totalSeats": total_seats,
            "assignedCount": len(assigned_users),
            "activeLogins30dCount": active_30d,
            "unassignedBlockedCount": len(blocked_users),
            "unassignedBlockedUsers": blocked_users,
            "assignedUsersSample": assigned_users[:25],
            "configs": loc_configs
        }

    sub_tasks = []
    for loc, host, col_id, col_obj in discovered_collections:
        base_col = f"https://{host}/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}/collections/{urllib.parse.quote(col_id)}"
        sub_tasks.append(("dataConnector", loc, host, col_id, f"{base_col}/dataConnector"))
        if col_id != "default_collection":
            sub_tasks.append(("colEngines", loc, host, col_id, f"{base_col}/engines"))
            sub_tasks.append(("colDataStores", loc, host, col_id, f"{base_col}/dataStores"))

    engine_disp_by_id = {}
    for loc, host, col_id, eng in raw_engines:
        eng_id = (eng.get("name") or "").split("/")[-1]
        if not eng_id:
            continue
        engine_disp_by_id[eng_id] = eng.get("displayName") or eng_id
        base_eng = f"https://{host}/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}/collections/{urllib.parse.quote(col_id)}/engines/{urllib.parse.quote(eng_id)}"
        sub_tasks.append(("engAssistants", loc, host, eng_id, f"{base_eng}/assistants"))
        sub_tasks.append(("engDefaultAgents", loc, host, eng_id, f"{base_eng}/assistants/default_assistant/agents?pageSize=100"))
        sub_tasks.append(("engAgentViews", loc, host, eng_id, f"{base_eng}/assistants/default_assistant:listAvailableAgentViews"))
        sub_tasks.append(("engWidgetConfig", loc, host, eng_id, f"{base_eng}/widgetConfigs/default_search_widget_config"))
        sub_tasks.append(("engServingConfigs", loc, host, eng_id, f"{base_eng}/servingConfigs"))
        sub_tasks.append(("engSessions", loc, host, eng_id, f"{base_eng}/sessions?pageSize=100"))

    def _parse_agent_raw(ag, ref_id, loc, host):
        ag_name = ag.get("name") or ""
        ag_id = ag_name.split("/")[-1] if ag_name else ""
        lc_def = ag.get("lowCodeAgentDefinition") or {}
        adk_def = ag.get("adkAgentDefinition") or {}
        df_def = ag.get("dialogflowAgentDefinition") or {}
        mg_def = ag.get("managedAgentDefinition") or {}
        root_node = lc_def.get("rootAgentNode") or {}
        llm_node = root_node.get("llmAgentNode") or {}
        llm_model = str(llm_node.get("model") or "")
        instr = str(llm_node.get("instruction") or "")
        instr_preview = (instr[:280] + "...") if len(instr) > 280 else instr
        sel_tools = (llm_node.get("selectedTools") or {}).get("tool") or []
        tools_names = [str(t.get("name") or "") for t in sel_tools if isinstance(t, dict) and t.get("name")]
        ds_specs = [str(d.get("dataStore") or "").split("/")[-1] for d in (lc_def.get("dataStoreSpecs") or []) if isinstance(d, dict) and d.get("dataStore")]
        starter_prompts = [str(sp.get("text") or "") for sp in (ag.get("starterPrompts") or []) if isinstance(sp, dict) and sp.get("text")]
        sh_cfg = ag.get("sharingConfig") or {}
        sh_scope = str(sh_cfg.get("scope") or "")
        if lc_def:
            ag_type = "LOW_CODE_AGENT"
        elif adk_def:
            ag_type = "ADK_AGENT"
        elif df_def:
            ag_type = "DIALOGFLOW_AGENT"
        elif mg_def:
            ag_type = "MANAGED_SYSTEM_AGENT"
        else:
            ag_type = "ASSISTANT_AGENT"
        return {
            "name": ag_name,
            "host": host,
            "agentId": ag_id,
            "displayName": ag.get("displayName") or ag_id,
            "description": ag.get("description") or "",
            "engineId": ref_id,
            "engineName": engine_disp_by_id.get(ref_id, ref_id),
            "location": loc,
            "state": ag.get("state") or "ENABLED",
            "agentType": ag_type,
            "llmModel": llm_model,
            "instructionPreview": instr_preview,
            "tools": tools_names,
            "dataStoreSpecs": ds_specs,
            "starterPrompts": starter_prompts[:4],
            "sharingScope": sh_scope,
            "sharingConfig": sh_cfg,
            "lowCodeAgentDefinition": lc_def,
            "adkAgentDefinition": adk_def,
            "dialogflowAgentDefinition": df_def,
            "managedAgentDefinition": mg_def,
            "createTime": ag.get("createTime") or "",
            "updateTime": ag.get("updateTime") or "",
            "creatorEmail": "",
            "owners": [],
            "iamGroups": []
        }

    def _run_sub(t):
        kind, loc, host, ref_id, url = t
        st, data = gcp_api_get(url, token, timeout=5, user_project=pid)
        if kind == "engDefaultAgents" and st == 200 and isinstance(data, dict):
            all_ags = list(data.get("agents") or [])
            nxt = data.get("nextPageToken")
            pages = 1
            base_u = url.split("?")[0]
            while nxt and pages < 10:
                pages += 1
                st2, d2 = gcp_api_get(f"{base_u}?pageSize=100&pageToken={urllib.parse.quote(nxt)}", token, timeout=5, user_project=pid)
                if st2 == 200 and isinstance(d2, dict):
                    all_ags.extend(d2.get("agents") or [])
                    nxt = d2.get("nextPageToken")
                else:
                    break
            data = {"agents": all_ags}
        return kind, loc, host, ref_id, st, data

    engine_extras = {}

    if sub_tasks:
        with ThreadPoolExecutor(max_workers=min(24, len(sub_tasks))) as ex:
            for kind, loc, host, ref_id, st, data in ex.map(_run_sub, sub_tasks):
                if st != 200 or not isinstance(data, dict):
                    continue
                if kind == "dataConnector":
                    dc_source = data.get("dataSource") or ""
                    if dc_source or data.get("entities") or data.get("params"):
                        safe_params = _mask_sensitive_connector_params(data.get("params") or {})
                        entities_list = []
                        for ent in (data.get("entities") or []):
                            entities_list.append({
                                "entityName": ent.get("entityName") or ent.get("name") or "",
                                "dataStore": ent.get("dataStore") or "",
                                "keyPropertyMappings": ent.get("keyPropertyMappings") or {},
                                "params": _mask_sensitive_connector_params(ent.get("params") or {})
                            })
                        conn_obj = {
                            "collectionId": ref_id,
                            "location": loc,
                            "name": data.get("name") or "",
                            "dataSource": dc_source,
                            "state": data.get("state") or "ACTIVE",
                            "refreshInterval": data.get("refreshInterval") or "",
                            "syncMode": data.get("syncMode") or "",
                            "params": safe_params,
                            "entities": entities_list,
                            "entitiesCount": len(entities_list),
                            "createTime": data.get("createTime") or _extract_epoch_ms_from_id(ref_id),
                            "updateTime": data.get("updateTime") or "",
                            "lastSyncTime": data.get("lastSyncTime") or "",
                            "errors": (data.get("errors") or [])[:5],
                            "aclEnabled": bool(data.get("aclEnabled", False))
                        }
                        result["connectors"].append(conn_obj)
                elif kind == "colEngines":
                    for eng in data.get("engines", []):
                        e_name = eng.get("name", "")
                        if e_name and e_name not in seen_eng_names:
                            seen_eng_names.add(e_name)
                            raw_engines.append((loc, host, ref_id, eng))
                elif kind == "colDataStores":
                    for ds in data.get("dataStores", []):
                        d_name = ds.get("name", "")
                        if d_name and d_name not in seen_ds_names:
                            seen_ds_names.add(d_name)
                            raw_datastores.append((loc, host, ref_id, ds))
                elif kind == "engAssistants":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    for ast in data.get("assistants", []):
                        ast_id = (ast.get("name") or "").split("/")[-1]
                        ast_item = {
                            "assistantId": ast_id,
                            "displayName": ast.get("displayName") or ast_id,
                            "engineId": ref_id,
                            "location": loc,
                            "generationConfig": ast.get("generationConfig") or {},
                            "customerPolicy": ast.get("customerPolicy") or {},
                            "webGroundingType": ast.get("webGroundingType") or ""
                        }
                        ext["assistants"].append(ast_item)
                        result["assistants"].append(ast_item)
                elif kind == "engDefaultAgents":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    for ag in data.get("agents", []):
                        ag_item = _parse_agent_raw(ag, ref_id, loc, host)
                        ext["agents"].append(ag_item)
                        result["agents"].append(ag_item)
                elif kind == "engAgentViews":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    for av in (data.get("agentViews") or data.get("availableAgentViews") or []):
                        ag_obj = av.get("agent") or av
                        ag_id = (ag_obj.get("name") or "").split("/")[-1]
                        if ag_id and not any(x.get("agentId") == ag_id for x in ext["agents"]):
                            ag_item = _parse_agent_raw(ag_obj, ref_id, loc, host)
                            ag_item["agentOrigin"] = av.get("agentOrigin") or "AGENTSPACE"
                            ext["agents"].append(ag_item)
                            result["agents"].append(ag_item)
                elif kind == "engWidgetConfig":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    ext["widgetConfig"] = {
                        "configId": data.get("configId") or "",
                        "displayName": data.get("displayName") or "",
                        "enableAutocomplete": data.get("enableAutocomplete"),
                        "allowPublicAccess": data.get("allowPublicAccess", False),
                        "enableWebApp": data.get("enableWebApp", True),
                        "llmEnabled": data.get("llmEnabled", True),
                        "accessSettings": data.get("accessSettings") or {},
                        "uiSettings": data.get("uiSettings") or {}
                    }
                elif kind == "engServingConfigs":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    for sc in data.get("servingConfigs", []):
                        sc_id = (sc.get("name") or "").split("/")[-1]
                        ext["servingConfigs"].append({
                            "servingConfigId": sc_id,
                            "displayName": sc.get("displayName") or sc_id,
                            "solutionType": sc.get("solutionType") or "",
                            "modelId": (sc.get("promptSpec") or {}).get("modelId") or sc.get("rankingExpression") or "",
                            "filterControlIds": sc.get("filterControlIds") or [],
                            "boostControlIds": sc.get("boostControlIds") or [],
                            "redirectControlIds": sc.get("redirectControlIds") or [],
                            "synonymsControlIds": sc.get("synonymsControlIds") or []
                        })
                elif kind == "engSessions":
                    ext = engine_extras.setdefault(ref_id, {"assistants": [], "agents": [], "widgetConfig": {}, "servingConfigs": [], "sessions": []})
                    sess_list = data.get("sessions") or []
                    ext["sessions"] = [
                        {
                            "sessionId": (s.get("name") or "").split("/")[-1],
                            "state": s.get("state") or "IN_PROGRESS",
                            "userPseudoId": s.get("userPseudoId") or "",
                            "turnsCount": len(s.get("turns") or []),
                            "startTime": s.get("startTime") or "",
                            "endTime": s.get("endTime") or ""
                        }
                        for s in sess_list
                    ]

    # Enrich all discovered agents with IAM Policy (:getIamPolicy) to identify real creatorEmail / agentOwner & shared IAM groups
    agents_with_name = [ag for ag in result["agents"] if ag.get("name") and ag.get("host")]
    if agents_with_name:
        def _fetch_ag_iam(ag_ref):
            u = f"https://{ag_ref['host']}/v1alpha/{ag_ref['name']}:getIamPolicy"
            st, d = gcp_api_get(u, token, timeout=4, user_project=pid)
            owners = []
            groups = []
            if st == 200 and isinstance(d, dict):
                for b in (d.get("bindings") or []):
                    role = str(b.get("role") or "")
                    for m in (b.get("members") or []):
                        if m.startswith("user:"):
                            em = m.split("user:", 1)[1].strip().lower()
                            if em and em not in owners:
                                owners.append(em)
                        elif m.startswith("group:"):
                            grp = m.split("group:", 1)[1].strip().lower()
                            if grp and grp not in groups:
                                groups.append(grp)
                        elif m == "allUsers" and "allUsers" not in groups:
                            groups.append("allUsers")
            return ag_ref, owners, groups

        with ThreadPoolExecutor(max_workers=min(24, len(agents_with_name))) as ex:
            for ag_ref, owners, groups in ex.map(_fetch_ag_iam, agents_with_name):
                ag_ref["owners"] = owners
                ag_ref["iamGroups"] = groups
                if owners:
                    ag_ref["creatorEmail"] = owners[0]
                elif groups:
                    ag_ref["creatorEmail"] = f"Group: {groups[0]}"
                else:
                    ag_ref["creatorEmail"] = "Google Managed / Admin"

    for loc, host, col_id, eng in raw_engines:
        eng_id = (eng.get("name") or "").split("/")[-1]
        ext = engine_extras.get(eng_id, {})
        eng_agents = ext.get("agents", [])
        owners_counter = {}
        eng_groups_set = set()
        for ag in eng_agents:
            for ow in (ag.get("owners") or []):
                rec = owners_counter.setdefault(ow, {"email": ow, "agentsCount": 0, "sampleAgents": []})
                rec["agentsCount"] += 1
                if len(rec["sampleAgents"]) < 5:
                    rec["sampleAgents"].append(ag.get("displayName") or ag.get("agentId"))
            for grp in (ag.get("iamGroups") or []):
                eng_groups_set.add(grp)
        owners_sorted = sorted(owners_counter.values(), key=lambda x: (x["agentsCount"], x["email"]), reverse=True)
        eng["_collectionId"] = col_id
        eng["_location"] = loc
        eng["_assistants"] = ext.get("assistants", [])
        eng["_agents"] = eng_agents
        eng["_agentOwners"] = owners_sorted
        eng["_agentOwnersCount"] = len(owners_sorted)
        eng["_agentGroups"] = sorted(list(eng_groups_set))
        eng["_sessions"] = ext.get("sessions", [])
        eng["_sessionsCount"] = len(ext.get("sessions", []))
        eng["_widgetConfig"] = ext.get("widgetConfig", {})
        eng["_servingConfigs"] = ext.get("servingConfigs", [])
        eng["_licensePool"] = result["licensePools"].get(loc, {})
        result["engines"].append(eng)

    for loc, host, col_id, ds in raw_datastores:
        ds["_collectionId"] = col_id
        ds["_location"] = loc
        result["dataStores"].append(ds)

    return result


def build_project_gemini_enterprise_inventory(p: dict) -> dict:
    """
    Costruisce l'inventario 360° di Gemini Enterprise (Google Agentspace) per un progetto `p`.
    """
    pid = str(p.get("projectId") or "")
    pname = str(p.get("name") or pid)
    deployed = p.get("deployedAiResources") or []
    as_tele = p.get("agentspaceTelemetry") or {}
    users_usage = p.get("usersUsage") or []
    creds_usage = p.get("credentialsUsage") or []

    tele_apps_by_id = {}
    for ta in (as_tele.get("apps") or []):
        eid = str(ta.get("engineId") or ta.get("id") or "")
        if eid:
            tele_apps_by_id[eid] = ta

    tele_ds_by_id = {}
    for td in (as_tele.get("dataStores") or []):
        did = str(td.get("dataStoreId") or td.get("id") or "")
        if did:
            tele_ds_by_id[did] = td

    raw_ds_map = {}
    for r in deployed:
        rt = str(r.get("resourceType") or r.get("type") or "")
        if rt == "AGENTSPACE_DATASTORE":
            did = str(r.get("resourceId") or r.get("id") or r.get("displayName") or "")
            if did:
                raw_ds_map[did] = dict(r)

    for did, td in tele_ds_by_id.items():
        if did not in raw_ds_map:
            raw_ds_map[did] = {
                "resourceType": "AGENTSPACE_DATASTORE",
                "resourceId": did,
                "displayName": td.get("displayName") or td.get("name") or did,
                "location": td.get("location") or td.get("region") or "eu",
                "details": f"Content: {td.get('connectorType') or 'Structured/Unstructured'}",
                "createTime": td.get("createTime")
            }

    explicit_connectors_by_col = {}
    for r in deployed:
        if str(r.get("resourceType") or "") == "GEMINI_ENTERPRISE_CONNECTOR":
            cid_col = str(r.get("collectionId") or r.get("resourceId") or "")
            if cid_col:
                explicit_connectors_by_col[cid_col] = r

    raw_apps_map = {}
    for r in deployed:
        rt = str(r.get("resourceType") or r.get("type") or "")
        if rt == "AGENTSPACE_APP":
            eid = str(r.get("resourceId") or r.get("id") or r.get("displayName") or "")
            if eid:
                raw_apps_map[eid] = dict(r)

    for eid, ta in tele_apps_by_id.items():
        if eid not in raw_apps_map:
            raw_apps_map[eid] = {
                "resourceType": "AGENTSPACE_APP",
                "resourceId": eid,
                "displayName": ta.get("displayName") or ta.get("name") or eid,
                "location": ta.get("location") or ta.get("region") or "eu",
                "cid": ta.get("cid") or "",
                "enabledModels": [ta.get("defaultModel")] if ta.get("defaultModel") else ["gemini-2.5-pro"],
                "disabledModels": [],
                "enabledFeatures": [],
                "disabledFeatures": [],
                "dataStoresCount": ta.get("linkedDataStoresCount", 0),
                "dataStoreIds": []
            }

    ds_to_apps = {}
    for eid, app_r in raw_apps_map.items():
        app_disp = str(app_r.get("displayName") or eid)
        for did in (app_r.get("dataStoreIds") or []):
            ds_to_apps.setdefault(str(did), []).append({
                "engineId": eid,
                "displayName": app_disp,
                "location": app_r.get("location") or "eu"
            })

    datastores_enriched = []
    connector_hubs_map = {}

    for did, ds_r in raw_ds_map.items():
        td = tele_ds_by_id.get(did, {})
        disp = str(ds_r.get("displayName") or td.get("displayName") or did)
        loc = str(ds_r.get("location") or td.get("location") or "eu")
        queries_cnt = int(td.get("queriesCount", td.get("queries", 0)) or 0)
        users_list = td.get("users") or td.get("activeUsers") or []
        users_cnt = int(td.get("activeUsersCount", len(users_list)) or 0)
        det_str = str(ds_r.get("details") or "")
        content_cfg = ds_r.get("contentConfig") or (det_str.replace("Content:", "").strip() if "Content:" in det_str else "CONTENT_REQUIRED")

        hub_meta = classify_connector_hub(did, disp, ds_r)
        hub_id = hub_meta["hubId"]
        linked_apps = ds_to_apps.get(did, [])

        ds_item = {
            "projectId": pid,
            "projectName": pname,
            "dataStoreId": did,
            "displayName": disp,
            "location": loc,
            "residencyCategory": classify_gcp_region_residency(loc),
            "connectorFamily": hub_meta["family"],
            "connectorFamilyLabel": hub_meta["familyLabel"],
            "vendor": hub_meta["vendor"],
            "icon": hub_meta["icon"],
            "hubId": hub_id,
            "hubDisplayName": hub_meta["hubDisplayName"],
            "entityName": hub_meta["entityName"],
            "authModel": hub_meta["authModel"],
            "syncProtocol": hub_meta["syncProtocol"],
            "isThirdPartySaaS": hub_meta["isThirdPartySaaS"],
            "contentConfig": content_cfg,
            "aclEnabled": bool(ds_r.get("aclEnabled", True)),
            "kmsKeyName": ds_r.get("kmsKeyName") or "",
            "createTime": hub_meta["createdTime"] or ds_r.get("createTime") or "",
            "updateTime": ds_r.get("updateTime") or "",
            "queriesCount": queries_cnt,
            "activeUsersCount": users_cnt,
            "activeUsers": users_list[:15],
            "linkedApps": linked_apps,
            "linkedAppsCount": len(linked_apps),
            "status": "ACTIVE" if queries_cnt > 0 else ("LINKED_READY" if linked_apps else "UNLINKED_IDLE"),
            "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/locations/{loc}/data-stores/{did}?project={pid}",
            "inspectApiUrl": f"https://{loc + '-' if loc in ('eu', 'us') else ''}discoveryengine.googleapis.com/v1alpha/projects/{pid}/locations/{loc}/collections/default_collection/dataStores/{did}"
        }
        datastores_enriched.append(ds_item)

        hub_entry = connector_hubs_map.get(hub_id)
        if not hub_entry:
            exp_conn = explicit_connectors_by_col.get(hub_id, {})
            hub_entry = {
                "projectId": pid,
                "projectName": pname,
                "hubId": hub_id,
                "hubDisplayName": hub_meta["hubDisplayName"],
                "family": hub_meta["family"],
                "familyLabel": hub_meta["familyLabel"],
                "vendor": hub_meta["vendor"],
                "icon": hub_meta["icon"],
                "location": loc,
                "residencyCategory": classify_gcp_region_residency(loc),
                "authModel": hub_meta["authModel"],
                "syncProtocol": hub_meta["syncProtocol"],
                "isThirdPartySaaS": hub_meta["isThirdPartySaaS"],
                "createTime": hub_meta["createdTime"],
                "connectorState": exp_conn.get("state") or "ACTIVE",
                "refreshInterval": exp_conn.get("refreshInterval") or "Continuous / Scheduled Sync",
                "dataSource": exp_conn.get("dataSource") or hub_meta["family"].lower(),
                "recoveredParams": exp_conn.get("params") or {
                    "collection_id": hub_id,
                    "location": loc,
                    "auth_mode": hub_meta["authModel"],
                    "acl_enforcement": "ENABLED (Identity-Aware RAG)",
                    "api_endpoint": f"https://{loc + '-' if loc in ('eu', 'us') else ''}discoveryengine.googleapis.com/v1alpha/projects/{pid}/locations/{loc}/collections/{hub_id}/dataConnector"
                },
                "entities": [],
                "dataStoreIds": [],
                "linkedAppsMap": {},
                "totalQueries": 0,
                "activeUsersSet": set(),
                "activeEntitiesCount": 0,
                "consoleUrl": f"https://console.cloud.google.com/gen-app-builder/data-stores?project={pid}",
                "cliVerifyCmd": f"curl -s -H \"Authorization: Bearer $(gcloud auth print-access-token)\" \"https://{loc + '-' if loc in ('eu', 'us') else ''}discoveryengine.googleapis.com/v1alpha/projects/{pid}/locations/{loc}/collections/{hub_id}/dataConnector\""
            }
            connector_hubs_map[hub_id] = hub_entry

        hub_entry["entities"].append({
            "entityName": hub_meta["entityName"],
            "dataStoreId": did,
            "displayName": disp,
            "contentConfig": content_cfg,
            "queriesCount": queries_cnt,
            "activeUsersCount": users_cnt,
            "linkedAppsCount": len(linked_apps),
            "status": ds_item["status"]
        })
        hub_entry["dataStoreIds"].append(did)
        hub_entry["totalQueries"] += queries_cnt
        if queries_cnt > 0:
            hub_entry["activeEntitiesCount"] += 1
        for u_em in users_list:
            if u_em:
                hub_entry["activeUsersSet"].add(u_em)
        for la in linked_apps:
            hub_entry["linkedAppsMap"][la["engineId"]] = la

    connector_hubs_list = []
    for h_val in connector_hubs_map.values():
        h_val["entities"].sort(key=lambda x: (x["queriesCount"], x["linkedAppsCount"], x["entityName"]), reverse=True)
        h_val["entitiesCount"] = len(h_val["entities"])
        h_val["activeUsers"] = sorted(list(h_val.pop("activeUsersSet", set())))
        h_val["activeUsersCount"] = len(h_val["activeUsers"])
        h_val["linkedApps"] = list(h_val.pop("linkedAppsMap", {}).values())
        h_val["linkedAppsCount"] = len(h_val["linkedApps"])
        h_val["status"] = "ACTIVE_TRAFFIC" if h_val["totalQueries"] > 0 else ("MOUNTED_READY" if h_val["linkedAppsCount"] > 0 else "CONFIGURED_IDLE")
        connector_hubs_list.append(h_val)

    connector_hubs_list.sort(key=lambda x: (x["isThirdPartySaaS"], x["totalQueries"], x["entitiesCount"], x["hubDisplayName"]), reverse=True)
    datastores_enriched.sort(key=lambda x: (x["queriesCount"], x["linkedAppsCount"], x["displayName"]), reverse=True)

    ds_lookup_by_id = {d["dataStoreId"]: d for d in datastores_enriched}

    apps_enriched = []
    for eid, app_r in raw_apps_map.items():
        ta = tele_apps_by_id.get(eid, {})
        disp = str(app_r.get("displayName") or ta.get("displayName") or eid)
        loc = str(app_r.get("location") or ta.get("location") or "eu")
        cid = str(app_r.get("cid") or ta.get("cid") or "")
        sel_state = str(app_r.get("modelSelector") or "DEFAULT")
        en_models = app_r.get("enabledModels") or ([ta.get("defaultModel")] if ta.get("defaultModel") else ["gemini-2.5-pro"])
        dis_models = app_r.get("disabledModels") or []
        en_feats = app_r.get("enabledFeatures") or []
        dis_feats = app_r.get("disabledFeatures") or []
        ds_ids = app_r.get("dataStoreIds") or []

        features_detailed = []
        all_feat_keys = sorted(list(set(en_feats) | set(dis_feats) | ({"model-selector"} if sel_state in ("ON", "OFF") else set())))
        for fk in all_feat_keys:
            if fk == "model-selector":
                is_on = (sel_state == "ON")
            else:
                is_on = (fk in en_feats)
            cat_meta = GEMINI_ENTERPRISE_FEATURES_CATALOG.get(fk, {
                "label": fk.replace("-", " ").title(),
                "category": "App Features",
                "description": f"Feature flag '{fk}' configured on the Gemini Enterprise Engine."
            })
            features_detailed.append({
                "key": fk,
                "state": "ON" if is_on else "OFF",
                "label": cat_meta["label"],
                "category": cat_meta["category"],
                "description": cat_meta["description"]
            })
        features_detailed.sort(key=lambda x: (x["state"] == "ON", x["category"], x["key"]), reverse=True)

        linked_ds_details = []
        linked_hubs_summary = {}
        for did in ds_ids:
            d_obj = ds_lookup_by_id.get(str(did))
            if d_obj:
                linked_ds_details.append({
                    "dataStoreId": d_obj["dataStoreId"],
                    "displayName": d_obj["displayName"],
                    "connectorFamily": d_obj["connectorFamily"],
                    "connectorFamilyLabel": d_obj["connectorFamilyLabel"],
                    "icon": d_obj["icon"],
                    "hubId": d_obj["hubId"],
                    "entityName": d_obj["entityName"],
                    "queriesCount": d_obj["queriesCount"],
                    "activeUsersCount": d_obj["activeUsersCount"],
                    "status": d_obj["status"]
                })
                hid = d_obj["hubId"]
                h_sum = linked_hubs_summary.setdefault(hid, {
                    "hubId": hid,
                    "hubDisplayName": d_obj["hubDisplayName"],
                    "family": d_obj["connectorFamily"],
                    "familyLabel": d_obj["connectorFamilyLabel"],
                    "icon": d_obj["icon"],
                    "entities": [],
                    "queriesCount": 0
                })
                h_sum["entities"].append(d_obj["entityName"])
                h_sum["queriesCount"] += d_obj["queriesCount"]
            else:
                hm = classify_connector_hub(str(did), str(did))
                linked_ds_details.append({
                    "dataStoreId": str(did),
                    "displayName": str(did),
                    "connectorFamily": hm["family"],
                    "connectorFamilyLabel": hm["familyLabel"],
                    "icon": hm["icon"],
                    "hubId": hm["hubId"],
                    "entityName": hm["entityName"],
                    "queriesCount": 0,
                    "activeUsersCount": 0,
                    "status": "LINKED_READY"
                })

        queries_cnt = int(ta.get("queriesCount", ta.get("queries", 0)) or 0)
        convs_cnt = int(ta.get("conversationsCount", 0) or 0)
        users_list = ta.get("users") or ta.get("activeUsers") or []
        users_cnt = int(ta.get("activeUsersCount", len(users_list)) or 0)

        obs_enabled = bool(app_r.get("observabilityEnabled", queries_cnt > 0))
        sens_logging = bool(app_r.get("sensitiveLoggingEnabled", False))
        company_name = str(app_r.get("companyName") or "")
        lic_pool = app_r.get("licensePool") or {}
        app_agents = app_r.get("agents") or []
        app_agent_owners = app_r.get("agentOwners") or []
        if not app_agent_owners and app_agents:
            ow_map = {}
            for ag_o in app_agents:
                for ow_em in (ag_o.get("owners") or ([ag_o["creatorEmail"]] if ag_o.get("creatorEmail") and "@" in str(ag_o.get("creatorEmail")) else [])):
                    rec_o = ow_map.setdefault(ow_em, {"email": ow_em, "agentsCount": 0, "sampleAgents": []})
                    rec_o["agentsCount"] += 1
                    if len(rec_o["sampleAgents"]) < 5:
                        rec_o["sampleAgents"].append(ag_o.get("displayName") or ag_o.get("agentId"))
            app_agent_owners = sorted(ow_map.values(), key=lambda x: (x["agentsCount"], x["email"]), reverse=True)
        app_agent_groups = app_r.get("agentGroups") or []
        sessions_list = app_r.get("sessions") or []
        sessions_cnt = int(app_r.get("sessionsCount", len(sessions_list)) or 0)

        # Find users in users_usage who have audit or runtime activity on this specific engineId
        audit_users_for_eng = []
        for u_obj in users_usage:
            u_engs = u_obj.get("engines") or []
            eng_keys = list(u_engs.keys()) if isinstance(u_engs, dict) else (list(u_engs) if isinstance(u_engs, (list, set)) else [])
            if eid in eng_keys:
                u_em_val = str(u_obj.get("userEmail") or "").strip().lower()
                if u_em_val:
                    audit_users_for_eng.append({
                        "email": u_em_val,
                        "requests": int(u_obj.get("requests", u_obj.get("totalInteractions", 0)) or 0),
                        "methods": (u_obj.get("methods") or [])[:6],
                        "lastSeen": u_obj.get("lastSeen") or ""
                    })

        all_principals_set = set(str(u).lower() for u in users_list if u)
        for ow_item in app_agent_owners:
            if ow_item.get("email"):
                all_principals_set.add(ow_item["email"].lower())
        for au_item in audit_users_for_eng:
            if au_item.get("email"):
                all_principals_set.add(au_item["email"].lower())

        lic_state = str(lic_pool.get("state") or "ACTIVE")
        if queries_cnt > 0:
            app_status = "ACTIVE"
        elif lic_state == "EXPIRED":
            app_status = "EXPIRED_LICENSE"
        elif (len(app_agents) > 0 or sessions_cnt > 0 or len(audit_users_for_eng) > 0) and not obs_enabled:
            app_status = "ACTIVE_NO_OBS"
        else:
            app_status = "ZERO_TRAFFIC"

        if eid in tele_apps_by_id:
            tele_apps_by_id[eid]["observabilityEnabled"] = obs_enabled
            tele_apps_by_id[eid]["agentsCount"] = len(app_agents)
            tele_apps_by_id[eid]["agentOwnersCount"] = len(app_agent_owners)
            tele_apps_by_id[eid]["sessionsCount"] = sessions_cnt
            tele_apps_by_id[eid]["licenseState"] = lic_state
            tele_apps_by_id[eid]["totalDetectedPrincipalsCount"] = len(all_principals_set)
            tele_apps_by_id[eid]["status"] = app_status

        web_loc = loc if loc in ("eu", "us") else "global"
        web_url = app_r.get("webAppUrl") or (f"https://vertexaisearch.cloud.google.com/{web_loc}/home/cid/{cid}" if cid else "")
        cfg_url = app_r.get("configUrl") or f"https://console.cloud.google.com/gen-app-builder/locations/{loc}/engines/{eid}/configurations?project={pid}"
        ov_url = app_r.get("overviewUrl") or f"https://console.cloud.google.com/gen-app-builder/locations/{loc}/engines/{eid}/overview?project={pid}"

        apps_enriched.append({
            "projectId": pid,
            "projectName": pname,
            "engineId": eid,
            "displayName": disp,
            "location": loc,
            "residencyCategory": classify_gcp_region_residency(loc),
            "appType": app_r.get("appType") or "INTRANET",
            "solutionType": app_r.get("solutionType") or "GENERATIVE_CHAT",
            "isGeminiEnterprise": bool(app_r.get("isGeminiEnterprise", True)),
            "cid": cid,
            "companyName": company_name,
            "observabilityEnabled": obs_enabled,
            "sensitiveLoggingEnabled": sens_logging,
            "licensePool": lic_pool,
            "licenseState": lic_state,
            "modelSelector": sel_state,
            "defaultModel": en_models[0] if en_models else "gemini-2.5-pro",
            "enabledModels": en_models,
            "disabledModels": dis_models,
            "enabledFeatures": en_feats,
            "disabledFeatures": dis_feats,
            "featuresDetailed": features_detailed,
            "enabledFeaturesCount": len(en_feats) + (1 if sel_state == "ON" else 0),
            "disabledFeaturesCount": len(dis_feats) + (1 if sel_state == "OFF" else 0),
            "dataStoreIds": ds_ids,
            "linkedDataStoresCount": max(len(ds_ids), int(app_r.get("dataStoresCount", 0) or 0)),
            "linkedDataStores": linked_ds_details,
            "linkedConnectorHubs": list(linked_hubs_summary.values()),
            "queriesCount": queries_cnt,
            "conversationsCount": max(convs_cnt, sessions_cnt),
            "sessionsCount": sessions_cnt,
            "sessions": sessions_list[:20],
            "activeUsersCount": users_cnt,
            "activeUsers": users_list[:25],
            "agentsCount": len(app_agents),
            "agentOwnersCount": len(app_agent_owners),
            "agentOwners": app_agent_owners[:30],
            "agentGroups": app_agent_groups,
            "auditUsers": audit_users_for_eng[:20],
            "totalDetectedPrincipalsCount": len(all_principals_set),
            "status": app_status,
            "assistants": app_r.get("assistants") or [{"assistantId": "default_assistant", "displayName": "Default Assistant"}],
            "agents": app_agents,
            "widgetConfig": app_r.get("widgetConfig") or {"configId": cid, "llmEnabled": True, "enableWebApp": bool(cid)},
            "servingConfigs": app_r.get("servingConfigs") or [{"servingConfigId": "default_config", "solutionType": "GENERATIVE_CHAT"}],
            "createTime": app_r.get("createTime") or _extract_epoch_ms_from_id(eid),
            "updateTime": app_r.get("updateTime") or "",
            "webAppUrl": web_url,
            "configUrl": cfg_url,
            "overviewUrl": ov_url,
            "inspectApiUrl": f"https://{loc + '-' if loc in ('eu', 'us') else ''}discoveryengine.googleapis.com/v1alpha/projects/{pid}/locations/{loc}/collections/default_collection/engines/{eid}",
            "cliVerifyCmd": f"curl -s -H \"Authorization: Bearer $(gcloud auth print-access-token)\" \"https://{loc + '-' if loc in ('eu', 'us') else ''}discoveryengine.googleapis.com/v1alpha/projects/{pid}/locations/{loc}/collections/default_collection/engines/{eid}\""
        })

    apps_enriched.sort(key=lambda x: (x.get("isGeminiEnterprise", False), x["queriesCount"], x.get("agentsCount", 0), x["linkedDataStoresCount"], x["displayName"]), reverse=True)

    gemini_enterprise_agents = []
    seen_ge_agent_ids = set()

    for app_item in apps_enriched:
        for ag in (app_item.get("agents") or []):
            ag_id = str(ag.get("agentId") or ag.get("resourceId") or "")
            ag_key = (app_item["engineId"], ag_id)
            if ag_id and ag_key not in seen_ge_agent_ids:
                seen_ge_agent_ids.add(ag_key)
                ag_type = ag.get("agentType") or ("LOW_CODE_AGENT" if ag.get("lowCodeAgentDefinition") else "ASSISTANT_AGENT")
                gemini_enterprise_agents.append({
                    "projectId": pid,
                    "projectName": pname,
                    "agentId": ag_id,
                    "displayName": ag.get("displayName") or ag_id,
                    "category": "GEMINI_ENTERPRISE_AGENT",
                    "categoryLabel": "🧑‍💻 Low-Code Agent (LLM Node)" if ag_type == "LOW_CODE_AGENT" else ("🌐 Google System Agent" if ag_type == "MANAGED_SYSTEM_AGENT" else "🤖 Gemini Enterprise Agent (Assistants API)"),
                    "agentType": ag_type,
                    "engineId": app_item["engineId"],
                    "engineName": app_item["displayName"],
                    "location": app_item["location"],
                    "llmModel": ag.get("llmModel") or app_item.get("defaultModel") or "gemini-2.5-pro",
                    "creatorEmail": ag.get("creatorEmail") or ((ag.get("owners") or [""])[0]) or "Admin / Engine Config",
                    "owners": ag.get("owners") or [],
                    "iamGroups": ag.get("iamGroups") or [],
                    "sharingScope": ag.get("sharingScope") or "",
                    "instructionPreview": ag.get("instructionPreview") or "",
                    "tools": ag.get("tools") or [],
                    "dataStoreSpecs": ag.get("dataStoreSpecs") or [],
                    "starterPrompts": ag.get("starterPrompts") or [],
                    "lifecycleActions": ["Configured in Assistant"],
                    "state": ag.get("state") or "ENABLED",
                    "description": ag.get("description") or ag.get("instructionPreview") or "Agent registered in the Gemini Enterprise Assistant",
                    "queriesCount": 0,
                    "createTime": ag.get("createTime") or "",
                    "lastSeen": ag.get("updateTime") or ag.get("createTime") or "",
                    "consoleUrl": app_item["configUrl"]
                })

    for r in deployed:
        if str(r.get("resourceType") or "") == "GEMINI_ENTERPRISE_ASSISTANT_AGENT":
            ag_id = str(r.get("resourceId") or "")
            ag_key = (str(r.get("engineId") or ""), ag_id)
            if ag_id and ag_key not in seen_ge_agent_ids:
                seen_ge_agent_ids.add(ag_key)
                ag_type = r.get("agentType") or "ASSISTANT_AGENT"
                gemini_enterprise_agents.append({
                    "projectId": pid,
                    "projectName": pname,
                    "agentId": ag_id,
                    "displayName": r.get("displayName") or ag_id,
                    "category": "GEMINI_ENTERPRISE_AGENT",
                    "categoryLabel": "🧑‍💻 Low-Code Agent (LLM Node)" if ag_type == "LOW_CODE_AGENT" else "🤖 Gemini Enterprise Agent (Assistants API)",
                    "agentType": ag_type,
                    "engineId": r.get("engineId") or "",
                    "engineName": r.get("engineName") or "",
                    "location": r.get("location") or "eu",
                    "llmModel": r.get("llmModel") or "gemini-2.5-pro",
                    "creatorEmail": r.get("creatorEmail") or "Admin / Engine Config",
                    "owners": r.get("owners") or [],
                    "iamGroups": r.get("iamGroups") or [],
                    "sharingScope": r.get("sharingScope") or "",
                    "instructionPreview": r.get("instructionPreview") or "",
                    "tools": r.get("tools") or [],
                    "dataStoreSpecs": r.get("dataStoreSpecs") or [],
                    "starterPrompts": r.get("starterPrompts") or [],
                    "lifecycleActions": ["Configured in Assistant"],
                    "state": r.get("state") or "ENABLED",
                    "description": r.get("details") or "",
                    "queriesCount": 0,
                    "createTime": r.get("createTime") or "",
                    "lastSeen": r.get("updateTime") or r.get("createTime") or "",
                    "consoleUrl": r.get("consoleUrl") or ""
                })

    # Map IAM agent ownership per user email across all discovered Assistant Agents
    iam_owned_agents_by_user = {}
    for ge_ag in gemini_enterprise_agents:
        for ow_em in (ge_ag.get("owners") or ([ge_ag["creatorEmail"]] if ge_ag.get("creatorEmail") and "@" in str(ge_ag.get("creatorEmail")) else [])):
            ow_clean = str(ow_em).strip().lower()
            if not ow_clean or "@" not in ow_clean:
                continue
            u_ag_rec = iam_owned_agents_by_user.setdefault(ow_clean, {
                "agents": [],
                "engines": {},
                "models": set(),
                "lastSeen": ""
            })
            u_ag_rec["agents"].append({
                "agentId": ge_ag["agentId"],
                "displayName": ge_ag["displayName"],
                "engineId": ge_ag["engineId"],
                "engineName": ge_ag["engineName"],
                "state": ge_ag["state"],
                "llmModel": ge_ag.get("llmModel") or ""
            })
            u_ag_rec["engines"][ge_ag["engineId"]] = ge_ag["engineName"]
            if ge_ag.get("llmModel"):
                u_ag_rec["models"].add(ge_ag["llmModel"])
            if (ge_ag.get("lastSeen") or "") > u_ag_rec["lastSeen"]:
                u_ag_rec["lastSeen"] = ge_ag.get("lastSeen") or ""

    agent_creators_audit = []
    seen_creator_emails = set()
    root_agent_runtime_users_count = 0
    users_usage_by_email = {str(u.get("userEmail") or "").strip().lower(): u for u in users_usage if u.get("userEmail")}

    for u in users_usage:
        u_em = str(u.get("userEmail") or "").strip().lower()
        u_methods = u.get("methods") or []
        matched_actions = []
        has_create_or_deploy = False
        has_runtime_only = False
        for m_name in u_methods:
            for kw, meta in AGENT_LIFECYCLE_METHODS_MAP.items():
                if kw.lower() in str(m_name).lower():
                    if meta["badge"] not in [x["badge"] for x in matched_actions]:
                        matched_actions.append({
                            "method": m_name,
                            "label": meta["label"],
                            "badge": meta["badge"],
                            "severity": meta["severity"]
                        })
                    if meta["badge"] in ("CREATE", "DEPLOY", "UPDATE", "PROPOSAL", "REVIEW", "DELETE"):
                        has_create_or_deploy = True
                    elif meta["badge"] == "RUNTIME":
                        has_runtime_only = True

        if has_runtime_only or has_create_or_deploy:
            root_agent_runtime_users_count += 1

        iam_owned_info = iam_owned_agents_by_user.get(u_em)
        if iam_owned_info:
            has_create_or_deploy = True
            if not any(x["badge"] == "IAM_OWNER" for x in matched_actions):
                matched_actions.insert(0, {
                    "method": f"agentOwner ({len(iam_owned_info['agents'])} agents)",
                    "label": f"IAM owner of {len(iam_owned_info['agents'])} agents in Assistants API",
                    "badge": "CREATE",
                    "severity": "HIGH"
                })

        if matched_actions and (has_create_or_deploy or any(x["badge"] != "RUNTIME" for x in matched_actions)):
            seen_creator_emails.add(u_em)
            u_engs = u.get("engines") or {}
            eng_ids = list(u_engs.keys()) if isinstance(u_engs, dict) else (list(u_engs) if isinstance(u_engs, list) else [])
            if iam_owned_info:
                for ie_id in iam_owned_info["engines"].keys():
                    if ie_id not in eng_ids:
                        eng_ids.insert(0, ie_id)
            primary_eng_id = eng_ids[0] if eng_ids else (apps_enriched[0]["engineId"] if apps_enriched else "gemini-enterprise")
            primary_eng_name = primary_eng_id
            for a_it in apps_enriched:
                if a_it["engineId"] == primary_eng_id:
                    primary_eng_name = a_it["displayName"]
                    break

            badges_list = [x["badge"] for x in matched_actions]
            if iam_owned_info:
                ag_status = f"OWNER ({len(iam_owned_info['agents'])} AGENTS)"
                ag_cat_label = f"🧑‍💻 IAM Owner ({len(iam_owned_info['agents'])} Configured Agents)"
            elif "DEPLOY" in badges_list or "CREATE" in badges_list:
                ag_status = "DEPLOYED / CREATED"
                ag_cat_label = "🧑‍💻 No-Code / Low-Code Agent Created by User"
            elif "PROPOSAL" in badges_list or "REVIEW" in badges_list:
                ag_status = "PENDING_APPROVAL / PROPOSAL"
                ag_cat_label = "📋 Agent Integration Proposal / Review"
            elif "UPDATE" in badges_list or "DELETE" in badges_list:
                ag_status = "MODIFIED / MANAGED"
                ag_cat_label = "🛠️ Managed / Updated Custom Agent"
            else:
                ag_status = "DISCOVERY / VIEW"
                ag_cat_label = "🔎 Agent Gallery Lookup"

            owned_agents_list = iam_owned_info["agents"] if iam_owned_info else []
            models_combined = list(dict.fromkeys(list(iam_owned_info["models"] if iam_owned_info else []) + (u.get("modelsUsed") or [])))

            creator_entry = {
                "projectId": pid,
                "projectName": pname,
                "userEmail": u_em,
                "isServiceAccount": bool(u.get("isServiceAccount", False)),
                "engineIds": eng_ids,
                "engineNames": [ next((a["displayName"] for a in apps_enriched if a["engineId"] == eid_x), eid_x) for eid_x in eng_ids ],
                "primaryEngineId": primary_eng_id,
                "primaryEngineName": primary_eng_name,
                "ownedAgentsCount": len(owned_agents_list),
                "ownedAgents": owned_agents_list[:10],
                "actions": matched_actions,
                "actionBadges": badges_list,
                "hasCreateOrDeploy": has_create_or_deploy,
                "status": ag_status,
                "categoryLabel": ag_cat_label,
                "requests": int(u.get("requests", 0) or 0),
                "queriesCount": int(u.get("queriesCount", 0) or 0),
                "conversationsCount": int(u.get("conversationsCount", 0) or 0),
                "modelsUsed": models_combined,
                "lastSeen": u.get("lastSeen") or (iam_owned_info["lastSeen"] if iam_owned_info else "")
            }
            agent_creators_audit.append(creator_entry)

    # Also include any IAM agentOwner who wasn't in the recent Cloud Logging window (e.g., created agents on engines with observabilityEnabled=false)
    for ow_em, iam_owned_info in iam_owned_agents_by_user.items():
        if ow_em in seen_creator_emails:
            continue
        seen_creator_emails.add(ow_em)
        u_ref = users_usage_by_email.get(ow_em, {})
        eng_ids = list(iam_owned_info["engines"].keys())
        primary_eng_id = eng_ids[0] if eng_ids else (apps_enriched[0]["engineId"] if apps_enriched else "gemini-enterprise")
        primary_eng_name = iam_owned_info["engines"].get(primary_eng_id, primary_eng_id)
        owned_agents_list = iam_owned_info["agents"]
        agent_creators_audit.append({
            "projectId": pid,
            "projectName": pname,
            "userEmail": ow_em,
            "isServiceAccount": False,
            "engineIds": eng_ids,
            "engineNames": [iam_owned_info["engines"].get(eid_x, eid_x) for eid_x in eng_ids],
            "primaryEngineId": primary_eng_id,
            "primaryEngineName": primary_eng_name,
            "ownedAgentsCount": len(owned_agents_list),
            "ownedAgents": owned_agents_list[:10],
            "actions": [{
                "method": f"agentOwner ({len(owned_agents_list)} agents)",
                "label": f"IAM owner of {len(owned_agents_list)} agents in Assistants API",
                "badge": "CREATE",
                "severity": "HIGH"
            }],
            "actionBadges": ["CREATE"],
            "hasCreateOrDeploy": True,
            "status": f"OWNER ({len(owned_agents_list)} AGENTS)",
            "categoryLabel": f"🧑‍💻 IAM Owner ({len(owned_agents_list)} Configured Agents)",
            "requests": int(u_ref.get("requests", 0) or 0),
            "queriesCount": int(u_ref.get("queriesCount", 0) or 0),
            "conversationsCount": int(u_ref.get("conversationsCount", 0) or 0),
            "modelsUsed": sorted(list(iam_owned_info["models"])) or (u_ref.get("modelsUsed") or []),
            "lastSeen": (u_ref.get("lastSeen") or iam_owned_info["lastSeen"] or "")
        })

    # Inspect credentialsUsage for low-code agent deploys, agent review requests, and IAM proposals
    for c in creds_usage:
        c_id = str(c.get("credentialId") or "")
        c_name = str(c.get("resolvedName") or c_id or "API / OAuth Credential")
        c_methods = c.get("methods") or []
        matched_actions = []
        has_create_or_deploy = False
        for m_name in c_methods:
            for kw, meta in AGENT_LIFECYCLE_METHODS_MAP.items():
                if kw.lower() in str(m_name).lower():
                    if meta["badge"] not in [x["badge"] for x in matched_actions]:
                        matched_actions.append({
                            "method": m_name,
                            "label": meta["label"],
                            "badge": meta["badge"],
                            "severity": meta["severity"]
                        })
                    if meta["badge"] in ("CREATE", "DEPLOY", "UPDATE", "PROPOSAL", "REVIEW", "DELETE"):
                        has_create_or_deploy = True
        if matched_actions and has_create_or_deploy:
            primary_eng_id = apps_enriched[0]["engineId"] if apps_enriched else "gemini-enterprise"
            primary_eng_name = apps_enriched[0]["displayName"] if apps_enriched else "Gemini Enterprise"
            badges_list = [x["badge"] for x in matched_actions]
            ag_status = "DEPLOYED_LOW_CODE" if "DEPLOY" in badges_list else ("REVIEW_REQUESTED" if "REVIEW" in badges_list else "CREATED_VIA_KEY")
            ag_cat_label = "🚀 Low-Code Agent Deployment / Review Workflow (Credential)"
            agent_creators_audit.append({
                "projectId": pid,
                "projectName": pname,
                "userEmail": c_name,
                "credentialId": c_id,
                "isServiceAccount": c.get("resolvedType") == "SERVICE_ACCOUNT",
                "engineIds": [primary_eng_id],
                "primaryEngineId": primary_eng_id,
                "primaryEngineName": primary_eng_name,
                "actions": matched_actions,
                "actionBadges": badges_list,
                "hasCreateOrDeploy": True,
                "status": ag_status,
                "categoryLabel": ag_cat_label,
                "requests": int(c.get("requests", 0) or 0),
                "queriesCount": int(c.get("inferenceRequests", c.get("requests", 0)) or 0),
                "conversationsCount": 0,
                "modelsUsed": [],
                "lastSeen": c.get("todayDate") or c.get("yesterdayDate") or ""
            })

    agent_creators_audit.sort(key=lambda x: (x["hasCreateOrDeploy"], x.get("ownedAgentsCount", 0), len(x["actions"]), x["requests"]), reverse=True)

    dialogflow_agents = []
    reasoning_engines = []
    mcp_and_registry = []

    for r in deployed:
        rt = str(r.get("resourceType") or r.get("type") or "")
        if rt == "DIALOGFLOW_CX_AGENT":
            dialogflow_agents.append({
                "projectId": pid,
                "projectName": pname,
                "agentId": r.get("resourceId") or "",
                "displayName": r.get("displayName") or r.get("resourceId") or "",
                "location": r.get("location") or "eu",
                "llmModel": r.get("llmModel") or "gemini-2.5-flash",
                "playbooks": r.get("playbooks") or [],
                "details": r.get("details") or "",
                "consoleUrl": r.get("consoleUrl") or f"https://conversational-agents.cloud.google.com/projects/{pid}"
            })
        elif rt == "REASONING_ENGINE":
            reasoning_engines.append({
                "projectId": pid,
                "projectName": pname,
                "resourceId": r.get("resourceId") or "",
                "displayName": r.get("displayName") or r.get("resourceId") or "",
                "baseName": r.get("baseName") or r.get("displayName") or "",
                "location": r.get("location") or "europe-west1",
                "framework": r.get("framework") or "vertex-agent",
                "pythonVersion": r.get("pythonVersion") or "",
                "isZombieVersion": bool(r.get("isZombieVersion", False)),
                "zombieStatus": r.get("zombieStatus") or "ACTIVE_LATEST",
                "createTime": r.get("createTime") or "",
                "updateTime": r.get("updateTime") or "",
                "details": r.get("details") or "",
                "consoleUrl": r.get("consoleUrl") or f"https://console.cloud.google.com/vertex-ai/agents/agent-engines?project={pid}"
            })
        elif rt in ("AGENT_REGISTRY_AGENT", "AGENT_REGISTRY_MCP", "AGENT_REGISTRY_MCP_SERVER"):
            mcp_and_registry.append({
                "projectId": pid,
                "projectName": pname,
                "resourceType": rt,
                "resourceId": r.get("resourceId") or "",
                "displayName": r.get("displayName") or r.get("resourceId") or "",
                "location": r.get("location") or "global",
                "details": r.get("details") or "",
                "consoleUrl": r.get("consoleUrl") or ""
            })

    connector_oauth_events = []
    for u in users_usage:
        u_em = str(u.get("userEmail") or "")
        u_methods = u.get("methods") or []
        matched_oauth = []
        for m_name in u_methods:
            for okw, odesc in CONNECTOR_OAUTH_METHODS_MAP.items():
                if okw.lower() in str(m_name).lower():
                    matched_oauth.append({"method": m_name, "description": odesc})
        if matched_oauth:
            connector_oauth_events.append({
                "projectId": pid,
                "principalEmail": u_em,
                "principalType": "SERVICE_ACCOUNT" if u.get("isServiceAccount") else "USER",
                "methods": matched_oauth,
                "requests": int(u.get("requests", 0) or 0),
                "lastSeen": u.get("lastSeen") or ""
            })

    for c in creds_usage:
        c_em = str(c.get("resolvedName") or c.get("credentialId") or c.get("email") or c.get("displayName") or "OAuth Credential / API Key")
        c_id = str(c.get("credentialId") or "")
        c_methods = c.get("methods") or []
        matched_oauth = []
        for m_name in c_methods:
            for okw, odesc in CONNECTOR_OAUTH_METHODS_MAP.items():
                if okw.lower() in str(m_name).lower():
                    matched_oauth.append({"method": m_name, "description": odesc})
        if matched_oauth and not any(x["principalEmail"].lower() == c_em.lower() for x in connector_oauth_events):
            connector_oauth_events.append({
                "projectId": pid,
                "principalEmail": c_em,
                "credentialId": c_id,
                "principalType": c.get("resolvedType") or "CREDENTIAL",
                "methods": matched_oauth,
                "requests": int(c.get("requests", 0) or 0),
                "lastSeen": c.get("todayDate") or c.get("yesterdayDate") or c.get("lastSeen") or ""
            })

    apps_with_selector_off = [a for a in apps_enriched if a["modelSelector"] == "OFF"]
    apps_in_global = [a for a in apps_enriched if a["location"] == "global"]
    third_party_hubs = [h for h in connector_hubs_list if h["isThirdPartySaaS"]]

    inv = {
        "projectId": pid,
        "projectName": pname,
        "hasGeminiEnterprise": bool(len(apps_enriched) > 0 or len(datastores_enriched) > 0 or len(gemini_enterprise_agents) > 0),
        "summary": {
            "totalApps": len(apps_enriched),
            "geminiEnterpriseAppsCount": sum(1 for a in apps_enriched if a.get("isGeminiEnterprise", False)),
            "vertexSearchAppsCount": sum(1 for a in apps_enriched if not a.get("isGeminiEnterprise", False)),
            "activeAppsCount": sum(1 for a in apps_enriched if a["queriesCount"] > 0),
            "appsWithSelectorOn": sum(1 for a in apps_enriched if a["modelSelector"] == "ON"),
            "appsWithSelectorOff": len(apps_with_selector_off),
            "totalConnectorHubs": len(connector_hubs_list),
            "thirdPartySaaSHubsCount": len(third_party_hubs),
            "totalDataStores": len(datastores_enriched),
            "activeDataStoresCount": sum(1 for d in datastores_enriched if d["queriesCount"] > 0),
            "unusedDataStoresCount": sum(1 for d in datastores_enriched if d["queriesCount"] == 0),
            "geminiEnterpriseAgentsCount": len(gemini_enterprise_agents),
            "dialogflowAgentsCount": len(dialogflow_agents),
            "reasoningEnginesCount": len([r for r in reasoning_engines if not r["isZombieVersion"]]),
            "totalReasoningEnginesBuilds": len(reasoning_engines),
            "mcpAndRegistryCount": len(mcp_and_registry),
            "totalAgentsAllTypes": len(gemini_enterprise_agents) + len(dialogflow_agents) + len([r for r in reasoning_engines if not r["isZombieVersion"]]) + len(mcp_and_registry),
            "agentCreatorsCount": sum(1 for c in agent_creators_audit if c["hasCreateOrDeploy"]),
            "rootAgentRuntimeUsersCount": root_agent_runtime_users_count,
            "connectorOAuthPrincipalsCount": len(connector_oauth_events)
        },
        "apps": apps_enriched,
        "connectorHubs": connector_hubs_list,
        "dataStores": datastores_enriched,
        "agentsAndAssistants": {
            "geminiEnterpriseAgents": gemini_enterprise_agents,
            "agentCreatorsAudit": agent_creators_audit,
            "dialogflowAgents": dialogflow_agents,
            "reasoningEngines": reasoning_engines,
            "mcpAndRegistry": mcp_and_registry
        },
        "securityAndGovernance": {
            "connectorOAuthEvents": connector_oauth_events,
            "appsWithModelSelectorOff": [{"engineId": a["engineId"], "displayName": a["displayName"], "location": a["location"]} for a in apps_with_selector_off],
            "appsInGlobalMultiRegion": [{"engineId": a["engineId"], "displayName": a["displayName"], "location": a["location"]} for a in apps_in_global],
            "thirdPartyConnectors": [{"hubId": h["hubId"], "hubDisplayName": h["hubDisplayName"], "vendor": h["vendor"], "entitiesCount": h["entitiesCount"], "authModel": h["authModel"]} for h in third_party_hubs]
        }
    }
    p["geminiEnterpriseInventory"] = inv
    return inv


def build_global_gemini_enterprise_inventory(projects: list) -> dict:
    """
    Aggrega `geminiEnterpriseInventory` su tutti i progetti scansionati per la vista globale.
    """
    all_apps = []
    all_hubs = []
    all_ds = []
    all_ge_agents = []
    all_creators = []
    all_df_agents = []
    all_re_agents = []
    all_mcp = []
    all_oauth = []
    tot_root_runtime = 0

    for p in (projects or []):
        inv = p.get("geminiEnterpriseInventory")
        if not isinstance(inv, dict):
            inv = build_project_gemini_enterprise_inventory(p)
        all_apps.extend(inv.get("apps") or [])
        all_hubs.extend(inv.get("connectorHubs") or [])
        all_ds.extend(inv.get("dataStores") or [])
        ag_sec = inv.get("agentsAndAssistants") or {}
        all_ge_agents.extend(ag_sec.get("geminiEnterpriseAgents") or [])
        all_creators.extend(ag_sec.get("agentCreatorsAudit") or [])
        all_df_agents.extend(ag_sec.get("dialogflowAgents") or [])
        all_re_agents.extend(ag_sec.get("reasoningEngines") or [])
        all_mcp.extend(ag_sec.get("mcpAndRegistry") or [])
        sec_g = inv.get("securityAndGovernance") or {}
        all_oauth.extend(sec_g.get("connectorOAuthEvents") or [])
        tot_root_runtime += int((inv.get("summary") or {}).get("rootAgentRuntimeUsersCount", 0) or 0)

    all_apps.sort(key=lambda x: (x.get("isGeminiEnterprise", False), x.get("queriesCount", 0), x.get("linkedDataStoresCount", 0), x.get("displayName", "")), reverse=True)
    all_hubs.sort(key=lambda x: (x.get("isThirdPartySaaS", False), x.get("totalQueries", 0), x.get("entitiesCount", 0)), reverse=True)
    all_ds.sort(key=lambda x: (x.get("queriesCount", 0), x.get("linkedAppsCount", 0), x.get("displayName", "")), reverse=True)

    active_re = [r for r in all_re_agents if not r.get("isZombieVersion", False)]

    return {
        "summary": {
            "totalApps": len(all_apps),
            "geminiEnterpriseAppsCount": sum(1 for a in all_apps if a.get("isGeminiEnterprise", False)),
            "vertexSearchAppsCount": sum(1 for a in all_apps if not a.get("isGeminiEnterprise", False)),
            "activeAppsCount": sum(1 for a in all_apps if a.get("queriesCount", 0) > 0),
            "appsWithSelectorOn": sum(1 for a in all_apps if a.get("modelSelector") == "ON"),
            "appsWithSelectorOff": sum(1 for a in all_apps if a.get("modelSelector") == "OFF"),
            "totalConnectorHubs": len(all_hubs),
            "thirdPartySaaSHubsCount": sum(1 for h in all_hubs if h.get("isThirdPartySaaS")),
            "totalDataStores": len(all_ds),
            "activeDataStoresCount": sum(1 for d in all_ds if d.get("queriesCount", 0) > 0),
            "unusedDataStoresCount": sum(1 for d in all_ds if d.get("queriesCount", 0) == 0),
            "geminiEnterpriseAgentsCount": len(all_ge_agents),
            "dialogflowAgentsCount": len(all_df_agents),
            "reasoningEnginesCount": len(active_re),
            "totalReasoningEnginesBuilds": len(all_re_agents),
            "mcpAndRegistryCount": len(all_mcp),
            "totalAgentsAllTypes": len(all_ge_agents) + len(all_df_agents) + len(active_re) + len(all_mcp),
            "agentCreatorsCount": sum(1 for c in all_creators if c.get("hasCreateOrDeploy")),
            "rootAgentRuntimeUsersCount": tot_root_runtime,
            "connectorOAuthPrincipalsCount": len(all_oauth)
        },
        "apps": all_apps,
        "connectorHubs": all_hubs,
        "dataStores": all_ds,
        "agentsAndAssistants": {
            "geminiEnterpriseAgents": all_ge_agents,
            "agentCreatorsAudit": all_creators,
            "dialogflowAgents": all_df_agents,
            "reasoningEngines": all_re_agents,
            "mcpAndRegistry": all_mcp
        },
        "securityAndGovernance": {
            "connectorOAuthEvents": all_oauth
        }
    }


def deep_inspect_gemini_resource_live(pid: str, location: str, resource_type: str, resource_id: str, token: str) -> dict:
    """
    Endpoint Live On-Demand (100% Read-Only) chiamato da GET /api/gemini-enterprise/inspect.
    """
    loc = (location or "eu").strip().lower()
    if loc not in ("global", "eu", "us"):
        loc = "eu" if loc.startswith("eu") else ("us" if loc.startswith("us") else "global")
    host = f"{loc}-discoveryengine.googleapis.com" if loc in ("eu", "us") else "discoveryengine.googleapis.com"
    base_loc = f"https://{host}/v1alpha/projects/{urllib.parse.quote(pid)}/locations/{loc}"
    rtype = (resource_type or "ENGINE").strip().upper()
    rid = (resource_id or "").strip()

    urls_to_probe = []
    if rtype in ("ENGINE", "APP", "AGENTSPACE_APP"):
        base_eng = f"{base_loc}/collections/default_collection/engines/{urllib.parse.quote(rid)}"
        urls_to_probe = [
            ("engine", base_eng),
            ("assistants", f"{base_eng}/assistants"),
            ("agents", f"{base_eng}/assistants/default_assistant/agents?pageSize=100"),
            ("availableAgentViews", f"{base_eng}/assistants/default_assistant:listAvailableAgentViews"),
            ("sessions", f"{base_eng}/sessions?pageSize=50"),
            ("widgetConfig", f"{base_eng}/widgetConfigs/default_search_widget_config"),
            ("servingConfigs", f"{base_eng}/servingConfigs"),
            ("controls", f"{base_eng}/controls"),
            ("userLicenses", f"{base_loc}/userStores/default_user_store/userLicenses?pageSize=50"),
            ("aclConfig", f"{base_loc}/aclConfig")
        ]
    elif rtype in ("CONNECTOR", "HUB", "COLLECTION"):
        col_id = rid
        base_col = f"{base_loc}/collections/{urllib.parse.quote(col_id)}"
        urls_to_probe = [
            ("collection", base_col),
            ("dataConnector", f"{base_col}/dataConnector"),
            ("collectionDataStores", f"{base_col}/dataStores"),
            ("collectionEngines", f"{base_col}/engines"),
            ("aclConfig", f"{base_loc}/aclConfig")
        ]
    else:
        base_ds = f"{base_loc}/collections/default_collection/dataStores/{urllib.parse.quote(rid)}"
        m_hub = re.match(r"^([a-zA-Z0-9_-]+?_1[6789]\d{11})(?:_(.+))?$", rid)
        col_id = m_hub.group(1) if m_hub else "default_collection"
        urls_to_probe = [
            ("dataStore", base_ds),
            ("schemas", f"{base_ds}/schemas"),
            ("targetSites", f"{base_ds}/siteSearchEngine/targetSites"),
            ("servingConfigs", f"{base_ds}/servingConfigs")
        ]
        if col_id != "default_collection":
            urls_to_probe.append(("parentDataConnector", f"{base_loc}/collections/{urllib.parse.quote(col_id)}/dataConnector"))
            urls_to_probe.append(("colDataStore", f"{base_loc}/collections/{urllib.parse.quote(col_id)}/dataStores/{urllib.parse.quote(rid)}"))

    def _fetch(item):
        k, u = item
        st, d = gcp_api_get(u, token, timeout=6, user_project=pid)
        return k, u, st, d

    live_results = {}
    http_statuses = {}
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(urls_to_probe)))) as ex:
        for k, u, st, d in ex.map(_fetch, urls_to_probe):
            http_statuses[k] = {"status": st, "url": u}
            if st == 200 and isinstance(d, dict):
                live_results[k] = _mask_sensitive_connector_params(d)

    return {
        "success": True,
        "inspectedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "projectId": pid,
        "location": loc,
        "resourceType": rtype,
        "resourceId": rid,
        "httpProbes": http_statuses,
        "liveData": live_results
    }
