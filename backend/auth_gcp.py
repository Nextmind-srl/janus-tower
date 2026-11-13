

def save_tokens_store(store: dict):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump({"accounts": store.get("accounts", {})}, f, indent=2, ensure_ascii=False)


def load_tokens_store() -> dict:
    """
    Loads stored OAuth tokens with strict Zero-Trust Daily Policy:
    Any token not created on today's local date (YYYY-MM-DD), expired past daily_expires_at,
    or lacking a session_id is immediately purged from memory and disk.
    """
    demo_ensure_token_store()  # demo mode only: renews the invented login after midnight (no-op otherwise)
    store = {"accounts": {}}
    today_str = get_today_date_str()
    now_ts = time.time()
    purged = False
    if os.path.exists(TOKENS_FILE):
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and isinstance(loaded.get("accounts"), dict):
                    for email, acc_info in list(loaded["accounts"].items()):
                        if not isinstance(acc_info, dict):
                            purged = True
                            continue
                        login_date = acc_info.get("login_date")
                        daily_exp = float(acc_info.get("daily_expires_at", 0) or 0)
                        sid = acc_info.get("session_id")
                        if login_date != today_str or daily_exp <= now_ts or not sid:
                            purged = True
                            continue
                        store["accounts"][email] = acc_info
    if purged:
        save_tokens_store(store)
    return store


def refresh_access_token_for_account(acc_info: dict) -> tuple[bool, str]:
    now = time.time()
    today_str = get_today_date_str()
    daily_exp = float(acc_info.get("daily_expires_at", 0) or 0)
    if acc_info.get("login_date") != today_str or daily_exp <= now or not acc_info.get("session_id"):
        return False, "Daily session expired. For security, the login is not kept across days: sign in with Google again."

    if is_demo_mode():
        # Demo mode: a placeholder token, never exchanged with Google (no network call is made here).
        acc_info["access_token"] = "demo-access-token-not-valid"
        acc_info["expires_at"] = daily_exp
        acc_info["needs_reauth"] = False
        return True, acc_info["access_token"]

    if acc_info.get("access_token") and acc_info.get("expires_at", 0) > now + 60:
        return True, acc_info["access_token"]

    if acc_info.get("needs_reauth"):
        return False, "Google session expired. Click 'Sign in with Google' to authenticate in this browser."

    ref_tok = acc_info.get("refresh_token")
    if not ref_tok:
        return False, "No token present: click 'Sign in with Google'."

    payload = urllib.parse.urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
        "refresh_token": ref_tok,
        "grant_type": "refresh_token"
    }).encode("utf-8")

    try:
        resp = HTTP_POOL.request(
            "POST",
            "https://oauth2.googleapis.com/token",
            body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=urllib3.Timeout(connect=4.0, read=5.0),
            retries=False
        )
        raw_body = resp.data.decode("utf-8", errors="replace") if resp.data else ""
        status_code = resp.status
        if status_code != 200:
            try:
                err_json = json.loads(raw_body)
                desc = err_json.get("error_description") or err_json.get("error") or f"HTTP {status_code}"
            except Exception:
                desc = f"HTTP {status_code}"
            acc_info["access_token"] = None
            acc_info["expires_at"] = 0
            acc_info["needs_reauth"] = True
            return False, f"Google session expired ({desc}). Click 'Sign in with Google' to re-authenticate."
        data = json.loads(raw_body)
        acc_info["access_token"] = data["access_token"]
        acc_info["expires_at"] = min(daily_exp, now + int(data.get("expires_in", 3500)))
        acc_info["needs_reauth"] = False
        return True, acc_info["access_token"]
    except Exception as e:
        return False, str(e)


def get_auth_status_for_browser(requested_account: str = None, browser_accounts: list[str] = None, session_id: str = None) -> dict:
    """
    Returns authentication status scoped to the specific browser session under Zero-Trust Daily Policy.
    Never falls back to any stored account if requested_account is not explicitly provided by the browser,
    and requires cryptographic session_id verification (constant-time compare_digest).
    """
    store = load_tokens_store()
    all_stored = store.get("accounts", {})
    today_str = get_today_date_str()
    now_ts = time.time()

    active_email = (requested_account or "").strip() or None
    req_sid = (session_id or "").strip() or None
    token_valid = False
    access_token = None
    token_error = None
    acc_info = {}

    if active_email:
        if active_email in all_stored:
            acc_info = all_stored[active_email]
            expected_sid = str(acc_info.get("session_id") or "").strip()
            if (
                acc_info.get("login_date") != today_str or
                now_ts >= float(acc_info.get("daily_expires_at", 0) or 0) or
                not expected_sid
            ):
                all_stored.pop(active_email, None)
                save_tokens_store(store)
                acc_info = {}
                token_error = None
            elif not req_sid or not secrets.compare_digest(req_sid, expected_sid):
                # Strict Zero-Trust: caller did not present the cryptographic session_id for this account
                acc_info = {}
                active_email = None
                token_valid = False
                token_error = "Unauthorized session or missing session token."
            else:
                was_reauth = acc_info.get("needs_reauth")
                ok, tok_or_err = refresh_access_token_for_account(acc_info)
                if ok:
                    token_valid = True
                    access_token = tok_or_err
                    save_tokens_store(store)
                else:
                    token_error = None
                    if not was_reauth and acc_info.get("needs_reauth"):
                        save_tokens_store(store)
        else:
            token_error = None
            active_email = None
    else:
        token_error = None

    allowed_set = set(browser_accounts or [])
    if active_email and active_email in all_stored and token_valid:
        allowed_set.add(active_email)

    accounts_list = []
    for email in sorted(allowed_set):
        if email in all_stored:
            a_item = all_stored[email]
            a_sid = str(a_item.get("session_id") or "").strip()
            # Only expose account in browser's list if it belongs to today's valid session and caller is authenticated
            if (
                a_item.get("login_date") == today_str and
                now_ts < float(a_item.get("daily_expires_at", 0) or 0) and
                a_sid and
                (token_valid or (req_sid and secrets.compare_digest(req_sid, a_sid)))
            ):
                accounts_list.append({
                    "account": email,
                    "active": (email == active_email and token_valid),
                    "loginDate": a_item.get("login_date"),
                    "dailyExpiresAtIso": a_item.get("daily_expires_at_iso", "23:59")
                })

    return {
        "accounts": accounts_list,
        "activeAccount": active_email if token_valid else None,
        "tokenValid": token_valid,
        "needsLogin": not token_valid,
        "accessToken": access_token,
        "tokenError": None if token_valid else token_error,
        "loginDate": acc_info.get("login_date") if token_valid else None,
        "dailyExpiresAtIso": acc_info.get("daily_expires_at_iso", "23:59") if token_valid else "23:59",
        "sessionId": acc_info.get("session_id", "") if token_valid else "",
        "sessionToken": acc_info.get("session_id", "") if token_valid else "",
        "dailyZeroTrust": True,
        "usdToEurRate": get_usd_to_eur_rate()
    }


import random
import threading
import urllib3

class _GuardedPoolManager(urllib3.PoolManager):
    """Every request of the app to a remote host goes through this pool: in demo mode none may leave the machine."""

    def urlopen(self, method, url, redirect=True, **kw):
        demo_block_network("Network access")
        return super().urlopen(method, url, redirect=redirect, **kw)


HTTP_POOL = _GuardedPoolManager(
    num_pools=64,
    maxsize=256,
    block=False,
    headers={"Connection": "keep-alive"}
)

SCAN_PROGRESS_LOCK = threading.Lock()
LIVE_SCAN_EVENT = threading.Event()
LIVE_SCAN_EVENT.set()
LAST_LIVE_SCAN_RESULT = None

SCAN_PROGRESS = {
    "active": False,
    "scanId": 0,
    "account": None,
    "mode": "smart",
    "days": 30,
    "startedAt": 0.0,
    "finishedAt": 0.0,
    "finishedAtLocal": None,
    "lastElapsedSeconds": 0.0,
    "lastScannedAt": None,
    "lastError": None,
    "totalProjects": 0,
    "completedProjects": 0,
    "stepIndex": 1,
    "stepBadge": "Phase 1/4",
    "stepDesc": "Initializing scan...",
    "currentPhase": "Phase 1/4",
    "currentStep": "Initializing scan...",
    "pct": 5,
    "projectPhases": {}
}


def get_scan_progress_snapshot(account: str = None) -> dict:
    with SCAN_PROGRESS_LOCK:
        snap = dict(SCAN_PROGRESS)
        snap["projectPhases"] = dict(SCAN_PROGRESS.get("projectPhases", {}))
    # Prevent cross-account metadata bleed in SCAN_PROGRESS
    if account and snap.get("account") and snap.get("account") != account:
        return {
            "active": False,
            "scanId": snap.get("scanId", 0),
            "account": account,
            "mode": "smart",
            "days": 30,
            "elapsedSeconds": 0.0,
            "totalProjects": 0,
            "completedProjects": 0,
            "currentPhase": "Ready",
            "currentStep": "",
            "pct": 0,
            "projectPhases": {}
        }
    if snap.get("active") and snap.get("startedAt"):
        snap["elapsedSeconds"] = round(max(0.1, time.time() - snap["startedAt"]), 1)
    else:
        snap["elapsedSeconds"] = round(float(snap.get("lastElapsedSeconds", 0.0) or 0.0), 1)
    snap["currentPhase"] = snap.get("currentPhase") or snap.get("stepBadge") or "Phase 1/4"
    snap["currentStep"] = snap.get("currentStep") or snap.get("stepDesc") or ""
    return snap


def update_scan_progress(
    active: bool = None,
    mode: str = None,
    total_projects: int = None,
    completed_delta: int = 0,
    pid: str = None,
    project_phase: str = None,
    force_step: tuple[int, str, str] = None,
    force_pct: int = None,
    **kwargs
):
    with SCAN_PROGRESS_LOCK:
        if active is not None:
            SCAN_PROGRESS["active"] = active
            if active:
                SCAN_PROGRESS["startedAt"] = kwargs.get("startedAt") or time.time()
                SCAN_PROGRESS["completedProjects"] = 0
                SCAN_PROGRESS["projectPhases"] = {}
            else:
                now_ts = time.time()
                SCAN_PROGRESS["finishedAt"] = now_ts
                SCAN_PROGRESS["finishedAtLocal"] = datetime.now().strftime("%H:%M:%S")
                if SCAN_PROGRESS.get("startedAt"):
                    SCAN_PROGRESS["lastElapsedSeconds"] = round(max(0.1, now_ts - SCAN_PROGRESS["startedAt"]), 1)
                SCAN_PROGRESS["pct"] = 100
        if mode is not None:
            SCAN_PROGRESS["mode"] = mode
        if "days" in kwargs and kwargs["days"] is not None:
            SCAN_PROGRESS["days"] = int(kwargs["days"])
        if total_projects is not None:
            SCAN_PROGRESS["totalProjects"] = total_projects
        elif "totalProjects" in kwargs and kwargs["totalProjects"] is not None:
            SCAN_PROGRESS["totalProjects"] = kwargs["totalProjects"]
        if "completedProjects" in kwargs and kwargs["completedProjects"] is not None:
            SCAN_PROGRESS["completedProjects"] = kwargs["completedProjects"]
        elif completed_delta:
            SCAN_PROGRESS["completedProjects"] = min(
                SCAN_PROGRESS.get("totalProjects", 0),
                SCAN_PROGRESS.get("completedProjects", 0) + completed_delta
            )
        if pid:
            if project_phase == "DONE":
                SCAN_PROGRESS["projectPhases"].pop(pid, None)
            elif project_phase:
                SCAN_PROGRESS["projectPhases"][pid] = project_phase

        explicit_phase = kwargs.get("currentPhase")
        explicit_step = kwargs.get("currentStep")

        if force_step:
            SCAN_PROGRESS["stepIndex"] = force_step[0]
            SCAN_PROGRESS["stepBadge"] = force_step[1]
            SCAN_PROGRESS["stepDesc"] = force_step[2]
            SCAN_PROGRESS["currentPhase"] = force_step[1]
            SCAN_PROGRESS["currentStep"] = force_step[2]
        elif SCAN_PROGRESS["active"]:
            tot = max(1, SCAN_PROGRESS.get("totalProjects", 1))
            done = SCAN_PROGRESS.get("completedProjects", 0)
            phases = list(SCAN_PROGRESS.get("projectPhases", {}).items())
            active_pids_str = ", ".join(p for p, _ in phases[:3])
            if len(phases) > 3:
                active_pids_str += f" (+{len(phases) - 3})"

            stage_weights = {
                "BILLING_IAM": 0.15,
                "MONITORING": 0.45,
                "RESOURCES_LOGS": 0.80,
                "MERGE": 0.95
            }
            in_flight_weight = sum(stage_weights.get(ph, 0.3) for _, ph in phases)
            raw_ratio = min(0.96, (done + in_flight_weight) / float(tot))
            SCAN_PROGRESS["pct"] = max(6, min(96, int(round(8 + raw_ratio * 88))))

            if any(ph == "RESOURCES_LOGS" for _, ph in phases):
                SCAN_PROGRESS["stepIndex"] = 3
                SCAN_PROGRESS["stepBadge"] = f"Phase 3/4 • {done}/{tot} projects"
                SCAN_PROGRESS["stepDesc"] = (
                    f"Parallel audit of AI Resources, API Keys, Service Accounts and Cloud Logging ({active_pids_str})..."
                    if active_pids_str else "Parallel audit of AI Resources, API Keys and Cloud Logging..."
                )
            elif any(ph == "MONITORING" for _, ph in phases):
                SCAN_PROGRESS["stepIndex"] = 2
                SCAN_PROGRESS["stepBadge"] = f"Phase 2/4 • {done}/{tot} projects"
                SCAN_PROGRESS["stepDesc"] = (
                    f"Parallel Cloud Monitoring prefetch: Vertex AI calls, Gemini and Tokens ({active_pids_str})..."
                    if active_pids_str else "Parallel Cloud Monitoring telemetry prefetch..."
                )
            elif done < tot:
                SCAN_PROGRESS["stepIndex"] = 1
                SCAN_PROGRESS["stepBadge"] = f"Phase 1/4 • {done}/{tot} projects"
                SCAN_PROGRESS["stepDesc"] = (
                    f"Checking Billing, enabled AI APIs and IAM permissions ({active_pids_str})..."
                    if active_pids_str else "Checking Google Cloud projects, Billing status and IAM permissions..."
                )
            else:
                SCAN_PROGRESS["stepIndex"] = 4
                SCAN_PROGRESS["stepBadge"] = f"Phase 4/4 • {tot}/{tot} projects"
                SCAN_PROGRESS["stepDesc"] = "Final FinOps and Data Residency aggregation, saving cache..."

            if explicit_phase:
                SCAN_PROGRESS["stepBadge"] = explicit_phase
            if explicit_step:
                SCAN_PROGRESS["stepDesc"] = explicit_step
            SCAN_PROGRESS["currentPhase"] = SCAN_PROGRESS["stepBadge"]
            SCAN_PROGRESS["currentStep"] = SCAN_PROGRESS["stepDesc"]
        else:
            if explicit_phase:
                SCAN_PROGRESS["stepBadge"] = explicit_phase
                SCAN_PROGRESS["currentPhase"] = explicit_phase
            if explicit_step:
                SCAN_PROGRESS["stepDesc"] = explicit_step
                SCAN_PROGRESS["currentStep"] = explicit_step

        if force_pct is not None:
            SCAN_PROGRESS["pct"] = force_pct


# Google answers 429 (quota / rate limit) or 5xx under load: these are retried with growing waits,
# honouring Retry-After, so a busy minute is not mistaken for "no permission" or "no data".
GCP_RETRY_STATUSES = (429, 500, 502, 503, 504)
GCP_MAX_ATTEMPTS = 4
GCP_MAX_RETRY_WAIT_S = 8.0
GCP_RETRY_SLEEP = time.sleep


def _gcp_retry_wait(attempt: int, resp=None) -> float:
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    if retry_after:
        with contextlib.suppress(ValueError, TypeError):
            return min(GCP_MAX_RETRY_WAIT_S, max(0.0, float(retry_after)))
    return min(GCP_MAX_RETRY_WAIT_S, float(2 ** attempt)) + random.uniform(0.0, 0.5)  # noqa: S311  # nosec B311 - jitter, not crypto


def gcp_api_get(url: str, token: str, timeout: int = 12, user_project: str = None) -> tuple[int, dict]:
    """100% Read-Only HTTP GET wrapper for Google Cloud APIs (with persistent Keep-Alive pool)."""
    demo_block_network("Google Cloud API access")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }
    if user_project:
        headers["x-goog-user-project"] = user_project
    for attempt in range(GCP_MAX_ATTEMPTS):
        try:
            resp = HTTP_POOL.request(
                "GET",
                url,
                headers=headers,
                timeout=urllib3.Timeout(connect=4.0, read=float(timeout)),
                retries=False
            )
        except Exception as e:
            return 0, {"error": str(e)}
        if resp.status in GCP_RETRY_STATUSES and attempt < GCP_MAX_ATTEMPTS - 1:
            GCP_RETRY_SLEEP(_gcp_retry_wait(attempt, resp))
            continue
        raw = resp.data.decode("utf-8", errors="replace") if resp.data else ""
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"error": raw} if resp.status >= 400 else {}
        return resp.status, data
    return 0, {"error": "max_attempts_exceeded"}


def gcp_api_post(url: str, token: str, payload_dict: dict, timeout: int = 10, user_project: str = None) -> tuple[int, dict]:
    """100% Read-Only HTTP POST wrapper for Google Cloud query APIs (testIamPermissions, entries:list)."""
    demo_block_network("Google Cloud API access")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }
    if user_project:
        headers["x-goog-user-project"] = user_project
    body = json.dumps(payload_dict).encode("utf-8")
    max_attempts = 3 if "logging.googleapis.com" in url else 2  # network errors
    for attempt in range(GCP_MAX_ATTEMPTS):
        try:
            resp = HTTP_POOL.request(
                "POST",
                url,
                body=body,
                headers=headers,
                timeout=urllib3.Timeout(connect=4.0, read=float(timeout)),
                retries=False
            )
            if resp.status in GCP_RETRY_STATUSES and attempt < GCP_MAX_ATTEMPTS - 1:
                GCP_RETRY_SLEEP(_gcp_retry_wait(attempt, resp))
                continue
            raw = resp.data.decode("utf-8", errors="replace") if resp.data else ""
            try:
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {"error": raw} if resp.status >= 400 else {}
            return resp.status, data
        except Exception as e:
            if attempt < max_attempts - 1:
                time.sleep(0.35 * (attempt + 1))
                continue
            return 0, {"error": str(e)}
    return 0, {"error": "max_attempts_exceeded"}


PROJECT_IAM_PERMISSIONS_TO_CHECK = [
    "resourcemanager.projects.get",
    "serviceusage.services.list",
    "serviceusage.apiKeys.list",
    "monitoring.timeSeries.list",
    "logging.logEntries.list",
    "iam.serviceAccounts.list",
    "aiplatform.endpoints.list",
    "aiplatform.reasoningEngines.list",
    "dialogflow.agents.list",
    "discoveryengine.engines.list",
    "modelarmor.floorSettings.get",
    "modelarmor.templates.list"
]

IAM_CHECK_SEMAPHORE = threading.Semaphore(4)
BA_CACHE_LOCK = threading.Lock()


def check_project_iam_permissions(pid: str, token: str) -> set[str] | None:
    """
    100% Read-Only IAM permission check via cloudresourcemanager projects:testIamPermissions.
    Returns the set of granted permissions out of PROJECT_IAM_PERMISSIONS_TO_CHECK, or None when the
    check could not be completed (429 / 5xx / network error after retries): "unknown", not "denied".
    Uses a concurrency semaphore (gcp_api_post retries with backoff) to avoid Cloud Resource Manager 429 bursts.
    """
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{urllib.parse.quote(pid)}:testIamPermissions"
    payload = {"permissions": PROJECT_IAM_PERMISSIONS_TO_CHECK}
    with IAM_CHECK_SEMAPHORE:
        st, data = gcp_api_post(url, token, payload, timeout=10)
    if st == 200 and isinstance(data, dict):
        return set(data.get("permissions", []))
    if st == 0 or st in GCP_RETRY_STATUSES:
        return None
    return set()


def check_billing_account_access(billing_account_name: str, token: str, ba_cache: dict) -> bool:
    """
    100% Read-Only check on whether the current user has roles/billing.viewer on the Billing Account
    to read direct billing account details/invoices. Cached per Billing Account across the scan.
    """
    if not billing_account_name:
        return False
    with BA_CACHE_LOCK:
        if billing_account_name in ba_cache:
            return ba_cache[billing_account_name]
    url = f"https://cloudbilling.googleapis.com/v1/{billing_account_name}"
    st, _ = gcp_api_get(url, token, timeout=6)
    granted = (st == 200)
    with BA_CACHE_LOCK:
        ba_cache[billing_account_name] = granted
    return granted


def list_all_accessible_projects(token: str) -> list[dict]:
    projects = []
    page_token = None
    while True:
        url = "https://cloudresourcemanager.googleapis.com/v1/projects?filter=lifecycleState:ACTIVE&pageSize=200"
        if page_token:
            url += f"&pageToken={urllib.parse.quote(page_token)}"
        status, data = gcp_api_get(url, token, timeout=15)
        if status != 200:
            break
        for p in data.get("projects", []):
            projects.append({
                "projectId": p.get("projectId"),
                "name": p.get("name") or p.get("projectId"),
                "projectNumber": p.get("projectNumber"),
                "createTime": p.get("createTime"),
                "labels": p.get("labels", {})
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return projects


def fetch_monitoring_timeseries(project_id: str, token: str, metric_filter: str, start_iso: str, end_iso: str, group_by_fields: list[str] = None, aligner: str = "ALIGN_SUM") -> list[dict]:
    params = {
        "filter": metric_filter,
        "interval.startTime": start_iso,
        "interval.endTime": end_iso,
        "aggregation.alignmentPeriod": "3600s",
        "aggregation.perSeriesAligner": aligner,
    }
    if group_by_fields:
        params["aggregation.crossSeriesReducer"] = "REDUCE_SUM"
        base_query_items = list(params.items()) + [("aggregation.groupByFields", f) for f in group_by_fields]
    else:
        base_query_items = list(params.items())

    all_series = []
    page_token = None
    for _ in range(4):
        query_items = list(base_query_items)
        if page_token:
            query_items.append(("pageToken", page_token))
        qs = urllib.parse.urlencode(query_items)
        url = f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(project_id)}/timeSeries?{qs}"
        status, data = gcp_api_get(url, token, timeout=22, user_project=None)
        if status != 200:
            status, data = gcp_api_get(url, token, timeout=22, user_project=project_id)
        if status != 200 or not isinstance(data, dict):
            break
        all_series.extend(data.get("timeSeries", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return all_series


def empty_day_bucket() -> dict:
    return {
        "requests": 0,
        "inferenceRequests": 0,
        "vertexInferenceRequests": 0,
        "systemRequests": 0,
        "vertexRequests": 0,
        "geminiApiRequests": 0,
        "ok200": 0,
        "ok200Inference": 0,
        "errors429": 0,
        "tokens": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cachedTokens": 0,
        "thinkingTokens": 0,
        "costUsd": 0.0,
        "vertexCostUsd": 0.0,
        "geminiCostUsd": 0.0,
        "otherAiCostUsd": 0.0
    }


