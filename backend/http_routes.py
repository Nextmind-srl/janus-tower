def _host_only(value: str) -> str:
    """Lower-cased host part of 'host', 'host:port' or '[::1]:port' (no scheme, no path)."""
    value = (value or "").strip().lower()
    if "@" in value or "/" in value or " " in value:
        return ""  # userinfo, path or spaces never belong in a Host/Origin: never match an allowed host
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


CSP_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def build_csp(html_bytes: bytes) -> str:
    """Content-Security-Policy for the app page. Scripts: only the inline blocks present in the served HTML
    (authorised by their sha256, so no 'unsafe-inline') and the pinned CDN libraries; no 'unsafe-eval'.
    Styles keep 'unsafe-inline' (Tailwind CDN injects <style> at runtime and templates use style attributes)."""
    import hashlib
    # The HTML parser normalises CRLF/CR to LF before hashing the script text: do the same, so a CRLF checkout still matches.
    hashes = [
        "'sha256-" + base64.b64encode(hashlib.sha256(m.group(1).replace(b"\r\n", b"\n").replace(b"\r", b"\n")).digest()).decode("ascii") + "'"
        for m in CSP_INLINE_SCRIPT_RE.finditer(html_bytes or b"")
        if m.group(1).strip()
    ]
    script_src = " ".join(hashes + ["https://cdn.jsdelivr.net"])
    return "; ".join([
        "default-src 'none'",
        f"script-src {script_src}",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com data:",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'self'",
        "object-src 'none'",
        "frame-ancestors 'self'",
    ])


def csp_header_name() -> str:
    """CSP_REPORT_ONLY=1 sends the same policy without blocking anything (violations show in the console)."""
    if os.environ.get("CSP_REPORT_ONLY", "").strip().lower() in ("1", "true", "yes"):
        return "Content-Security-Policy-Report-Only"
    return "Content-Security-Policy"


def allowed_request_hosts(extra_hosts=None) -> set:
    """Hosts the app may be reached on: loopback names, LOOPBACK_HOST, PUBLIC_BASE_URL host, ALLOWED_HOSTS."""
    hosts = {"localhost", "127.0.0.1", "[::1]"}
    if is_demo_mode():
        return hosts  # demo mode answers loopback names only (no LOOPBACK_HOST / PUBLIC_BASE_URL / ALLOWED_HOSTS extras)
    loopback = os.environ.get("LOOPBACK_HOST", "").strip()
    if loopback:
        hosts.add(_host_only(loopback))
    public = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if public:
        hosts.add(_host_only(urllib.parse.urlparse(public).netloc.rsplit("@", 1)[-1]))
    for raw in os.environ.get("ALLOWED_HOSTS", "").split(","):
        if raw.strip():
            hosts.add(_host_only(raw))
    for raw in extra_hosts or ():
        if str(raw).strip():
            hosts.add(_host_only(str(raw)))
    return hosts


def request_origin_allowed(method: str, path: str, headers, extra_hosts=None) -> tuple:
    """Returns (allowed, reason). Checks Host on every request (DNS rebinding) and Origin on
    state-changing requests (POST and GET /api/scan). Absent Origin is allowed; 'null' is refused."""
    allowed = allowed_request_hosts(extra_hosts)
    host = headers.get("Host")
    if not host or _host_only(host) not in allowed:
        return False, "Host header not allowed"
    if method.upper() == "POST" or urllib.parse.urlparse(path).path == "/api/scan":
        origin = headers.get("Origin")
        if origin is not None:
            netloc = urllib.parse.urlparse(origin.strip()).netloc
            if not netloc or _host_only(netloc) not in allowed:
                return False, "Origin not allowed"
    return True, ""


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


# POST routes that need Google (live scans, price list sync) or would remove the demo login / data: refused in demo mode.
DEMO_BLOCKED_POST_PATHS = {
    "/api/projects-sync/force-scan": "Project re-scan",
    "/api/project-scan": "Project re-scan",
    "/api/models-pricing/sync": "Price list sync",
    "/api/models-pricing/calibrate-bigquery": "BigQuery billing calibration",
    "/api/data/purge": "Local data purge",
    "/api/auth/logout": "Sign out",
}


class MonitorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=RESOURCE_DIR, **kwargs)

    def log_message(self, format, *args):
        # Access log without query strings: they may carry OAuth codes, emails or project ids.
        if args and isinstance(args[0], str):
            args = (re.sub(r"\?\S*", "", args[0]),) + args[1:]
        super().log_message(format, *args)

    def get_browser_account_context(self, qs: dict = None, body_dict: dict = None) -> tuple[str | None, list[str]]:
        """
        Reads the active account, known account list, and cryptographic session token for THIS browser
        from HTTP headers, query string, or the browser's daily cookie.
        Strict Zero-Trust: never falls back to server-side accounts if browser sends none,
        and always requires matching cryptographic session_id.
        """
        qs = qs or {}
        body_dict = body_dict or {}

        # 1. Explicit header or query param from browser JS session
        acc = (
            self.headers.get("X-GCP-Account") or
            (qs.get("account", [None])[0] if "account" in qs else None) or
            body_dict.get("account")
        )

        # 2. Browser's known accounts list header
        browser_accs_hdr = self.headers.get("X-GCP-Browser-Accounts", "")
        browser_accs = [x.strip() for x in browser_accs_hdr.split(",") if x.strip()]

        # 3. Extract session token from header or HttpOnly cookie
        header_sid = (self.headers.get("X-GCP-Session-Token") or "").strip() or None
        cookie_raw = self.headers.get("Cookie", "")
        cookie_sid = None
        cookie_acc = None
        if cookie_raw:
            c = SimpleCookie()
            with contextlib.suppress( Exception):
                c.load(cookie_raw)
                if SESSION_COOKIE_NAME in c and c[SESSION_COOKIE_NAME].value:
                    cookie_sid = urllib.parse.unquote(c[SESSION_COOKIE_NAME].value).strip()
                if COOKIE_NAME in c and c[COOKIE_NAME].value:
                    cookie_acc = urllib.parse.unquote(c[COOKIE_NAME].value).strip()

        self._current_req_sid = header_sid or cookie_sid

        if cookie_acc:
            store = load_tokens_store()
            acc_entry = store.get("accounts", {}).get(cookie_acc)
            if acc_entry and acc_entry.get("login_date") == get_today_date_str():
                expected_sid = acc_entry.get("session_id")
                if cookie_sid and expected_sid and secrets.compare_digest(str(cookie_sid), str(expected_sid)):
                    if not acc:
                        acc = cookie_acc
                    if cookie_acc not in browser_accs:
                        browser_accs.append(cookie_acc)

        if acc and acc not in browser_accs:
            browser_accs.append(acc)

        return (acc.strip() if acc else None), browser_accs

    def send_json(self, data: dict, status: int = 200, set_account_cookie: str = None, set_session_cookie: str = None, clear_cookie: bool = False):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        ttl_sec = get_seconds_until_midnight()
        if set_account_cookie:
            encoded = urllib.parse.quote(set_account_cookie)
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={encoded}; Path=/; Max-Age={ttl_sec}; HttpOnly; SameSite=Lax")
        if set_session_cookie:
            encoded_sid = urllib.parse.quote(set_session_cookie)
            self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}={encoded_sid}; Path=/; Max-Age={ttl_sec}; HttpOnly; SameSite=Lax")
        if clear_cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _send_demo_blocked(self, what: str, status: int = 403):
        """Answer for every action that needs Google or would delete the demo data (demo mode only)."""
        self.send_json({"success": False, "demo": True, "error": demo_disabled_message(what)}, status)

    def _redirect_home(self):
        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def _handle_oauth_callback_get(self, qs: dict):
        code = qs.get("code", [None])[0]
        err = qs.get("error", [None])[0]
        returned_state = (qs.get("state", [None])[0] or "").strip()

        expected_state = None
        cookie_raw = self.headers.get("Cookie", "")
        if cookie_raw:
            c = SimpleCookie()
            with contextlib.suppress(Exception):
                c.load(cookie_raw)
                if OAUTH_STATE_COOKIE_NAME in c and c[OAUTH_STATE_COOKIE_NAME].value:
                    expected_state = c[OAUTH_STATE_COOKIE_NAME].value.strip()

        if not OAUTH_CONFIGURED:
            err = OAUTH_NOT_CONFIGURED_MSG

        if err or not code:
            self.send_response(302)
            self.send_header("Set-Cookie", f"{OAUTH_STATE_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/?auth_error=" + urllib.parse.quote(str(err or "missing_code")))
            self.end_headers()
            return

        if not expected_state or not returned_state or not secrets.compare_digest(expected_state, returned_state):
            self.send_response(302)
            self.send_header("Set-Cookie", f"{OAUTH_STATE_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/?auth_error=" + urllib.parse.quote("invalid_oauth_state"))
            self.end_headers()
            return

        token_payload = urllib.parse.urlencode({
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI
        }).encode("utf-8")

        try:
            resp = HTTP_POOL.request(
                "POST",
                "https://oauth2.googleapis.com/token",
                body=token_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=urllib3.Timeout(connect=4.0, read=10.0),
                retries=False
            )
            raw_tok_body = resp.data.decode("utf-8", errors="replace") if resp.data else ""
            if resp.status != 200:
                raise RuntimeError(f"OAuth token exchange HTTP {resp.status}: {raw_tok_body}")
            tok_data = json.loads(raw_tok_body)

            access_tok = tok_data["access_token"]
            refresh_tok = tok_data.get("refresh_token")
            expires_in = int(tok_data.get("expires_in", 3500))

            u_status, u_info = gcp_api_get("https://www.googleapis.com/oauth2/v2/userinfo", access_tok, timeout=6)
            email = u_info.get("email") or "google-user@gcp"

            now_ts = time.time()
            today_str = get_today_date_str()
            ttl_midnight = get_seconds_until_midnight()
            daily_exp_ts = now_ts + ttl_midnight
            session_id = secrets.token_urlsafe(24)

            store = load_tokens_store()
            existing = store.setdefault("accounts", {}).get(email, {})
            store["accounts"][email] = {
                "email": email,
                "access_token": access_tok,
                "refresh_token": refresh_tok or existing.get("refresh_token"),
                "expires_at": min(now_ts + expires_in, daily_exp_ts),
                "login_date": today_str,
                "daily_expires_at": daily_exp_ts,
                "session_id": session_id,
                "needs_reauth": False
            }
            save_tokens_store(store)
            RAM_PAYLOAD_CACHE.clear()

            # Bind the logged-in account ONLY to THIS browser via daily Set-Cookie (expires at midnight).
            # Session id and email stay out of the URL (browser history, proxy and access logs).
            encoded_email = urllib.parse.quote(email)
            encoded_sid = urllib.parse.quote(session_id)
            self.send_response(302)
            self.send_header("Set-Cookie", f"{OAUTH_STATE_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={encoded_email}; Path=/; Max-Age={ttl_midnight}; HttpOnly; SameSite=Lax")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}={encoded_sid}; Path=/; Max-Age={ttl_midnight}; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/?autostart=1")
            self.end_headers()
        except Exception as ex:
            self.send_response(302)
            self.send_header("Set-Cookie", f"{OAUTH_STATE_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/?auth_error=" + urllib.parse.quote(str(ex)))
            self.end_headers()

    @staticmethod
    def _attach_sync_meta_to_projects(projects: list, reg_projects: dict):
        for p_obj in projects:
            pid = p_obj.get("projectId")
            if pid in reg_projects:
                r_meta = reg_projects[pid]
                p_obj["syncMeta"] = {
                    "scanEnabled": r_meta.get("scanEnabled", False),
                    "hasAiData": r_meta.get("hasAiData", False),
                    "scanRule": r_meta.get("scanRule", "AUTO_EXCLUDE_NO_DATA"),
                    "dataReason": r_meta.get("dataReason", ""),
                    "isNewProject": r_meta.get("isNewProject", False),
                    "lastScannedAt": r_meta.get("lastScannedAt")
                }

    def _handle_api_scan_get(self, qs: dict):
        try:
            days = max(1, int(qs.get("days", ["30"])[0]))
        except (ValueError, TypeError):
            days = 30
        use_cache = qs.get("cached", ["0"])[0] == "1"
        if is_demo_mode() and not use_cache:
            self._send_demo_blocked("Live scan")
            return
        scan_mode = qs.get("mode", ["smart"])[0]
        preset = (qs.get("preset", [""])[0] or "").strip().lower()
        start_date = (qs.get("startDate", [""])[0] or "").strip()[:10] or None
        end_date = (qs.get("endDate", [""])[0] or "").strip()[:10] or None

        now_utc = datetime.now(timezone.utc)
        if preset == "today":
            start_date = end_date = now_utc.strftime("%Y-%m-%d")
            days = 1
        elif preset == "yesterday":
            y_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")
            start_date = end_date = y_str
            days = 1
        elif start_date or end_date:
            try:
                s_dt = datetime.strptime((start_date or end_date)[:10], "%Y-%m-%d")
                e_dt = datetime.strptime((end_date or start_date)[:10], "%Y-%m-%d")
                if s_dt > e_dt:
                    s_dt, e_dt = e_dt, s_dt
                start_date = s_dt.strftime("%Y-%m-%d")
                end_date = e_dt.strftime("%Y-%m-%d")
                days = max(1, (e_dt - s_dt).days + 1)
                if not preset:
                    preset = "single" if start_date == end_date else "custom"
            except ValueError:
                start_date = None
                end_date = None

        is_custom_window = bool(start_date and end_date)
        req_acc, browser_accs = self.get_browser_account_context(qs=qs)
        req_sid = getattr(self, "_current_req_sid", None)
        st = get_auth_status_for_browser(req_acc, browser_accs, session_id=req_sid)
        st.pop("accessToken", None)
        active_acc = st.get("activeAccount")

        # Strict Daily Zero-Trust Gate: NEVER serve cached or live project data without a valid today login
        if not active_acc or not st.get("tokenValid"):
            self.send_json({
                "success": False,
                "needsLogin": True,
                "error": st.get("tokenError") or "Session not authenticated today. Click 'Sign in with Google' to get started.",
                "auth": st
            }, 401, clear_cookie=True)
            return

        if use_cache:
            reg = ensure_account_sync_registry(active_acc)
            reg_projects = reg.get("accounts", {}).get(active_acc, {}).get("projects", {})
            sync_mtime = os.path.getmtime(SYNC_REGISTRY_FILE) if os.path.exists(SYNC_REGISTRY_FILE) else 0.0
            cache_key_id = f"range_{start_date}_{end_date}" if is_custom_window else days
            acc_cache = get_account_cache_path(active_acc, cache_key_id)
            cache_30_path = get_account_cache_path(active_acc, 30)

            prefer_slice_from_30 = False
            if (days < 30 or is_custom_window) and os.path.exists(cache_30_path):
                if not os.path.exists(acc_cache):
                    prefer_slice_from_30 = True
                else:
                    with contextlib.suppress(OSError):
                        if os.path.getmtime(cache_30_path) > os.path.getmtime(acc_cache) + 2.0:
                            prefer_slice_from_30 = True

            if os.path.exists(acc_cache) and not prefer_slice_from_30:
                with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                    c_mtime = os.path.getmtime(acc_cache)
                    ram_key = ("exact", active_acc, str(cache_key_id), preset, round(c_mtime, 3), round(sync_mtime, 3))
                    if ram_key in RAM_PAYLOAD_CACHE:
                        cached_resp = RAM_PAYLOAD_CACHE[ram_key]
                        cached_resp["auth"] = st
                        cached_resp["scanProgress"] = get_scan_progress_snapshot(active_acc)
                        cached_resp["billingCalibration"] = get_billing_calibration_summary()
                        self.send_json(cached_resp)
                        return

                    with open(acc_cache, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)
                    if (
                        "billedProjects" in cached_data.get("summary", {}) and
                        cached_data.get("auth", {}).get("activeAccount") == active_acc
                    ):
                        cached_data["auth"] = st
                        cached_data["fromCache"] = True
                        if is_custom_window:
                            cached_data["periodStart"] = start_date
                            cached_data["periodEnd"] = end_date
                            cached_data["periodRange"] = {
                                "preset": preset or ("single" if start_date == end_date else "custom"),
                                "startDate": start_date,
                                "endDate": end_date,
                                "days": days,
                            }
                        self._attach_sync_meta_to_projects(cached_data.get("projects", []), reg_projects)
                        cached_data["sync"] = build_sync_summary_for_account(active_acc, reg)
                        enrich_scan_payload_security(cached_data)
                        RAM_PAYLOAD_CACHE[ram_key] = cached_data
                        cached_data["scanProgress"] = get_scan_progress_snapshot(active_acc)
                        cached_data["billingCalibration"] = get_billing_calibration_summary()
                        self.send_json(cached_data)
                        return

            # Fallback: slice from existing 30d or 90d cache so changing period NEVER forces a live scan!
            pref_base = 30 if days <= 30 else 90
            base_path = get_account_cache_path(active_acc, pref_base)
            base_mtime = os.path.getmtime(base_path) if os.path.exists(base_path) else 0.0
            ram_slice_key = ("sliced", active_acc, days, preset, start_date or "", end_date or "", round(base_mtime, 3), round(sync_mtime, 3))
            if ram_slice_key in RAM_PAYLOAD_CACHE:
                sliced_resp = RAM_PAYLOAD_CACHE[ram_slice_key]
                sliced_resp["auth"] = st
                sliced_resp["scanProgress"] = get_scan_progress_snapshot(active_acc)
                sliced_resp["billingCalibration"] = get_billing_calibration_summary()
                self.send_json(sliced_resp)
                return

            fallback_cache = load_best_cached_payload_for_account(active_acc, preferred_days=pref_base)
            if fallback_cache:
                eff_preset = preset or (str(days) if not is_custom_window else ("single" if start_date == end_date else "custom"))
                sliced_data = slice_cached_payload_for_days(
                    fallback_cache,
                    target_days=days,
                    auth=st,
                    start_date=start_date,
                    end_date=end_date,
                    preset=eff_preset
                )
                self._attach_sync_meta_to_projects(sliced_data.get("projects", []), reg_projects)
                sliced_data["sync"] = build_sync_summary_for_account(active_acc, reg)
                RAM_PAYLOAD_CACHE[ram_slice_key] = sliced_data
                sliced_data["scanProgress"] = get_scan_progress_snapshot(active_acc)
                sliced_data["billingCalibration"] = get_billing_calibration_summary()
                self.send_json(sliced_data)
                return

            self.send_json({
                "success": False,
                "noCacheYet": True,
                "auth": st,
                "scanProgress": get_scan_progress_snapshot(active_acc),
                "billingCalibration": get_billing_calibration_summary(),
            })
            return

        async_mode = qs.get("async", ["0"])[0] == "1"
        eff_preset = preset or (str(days) if not is_custom_window else ("single" if start_date == end_date else "custom"))
        res = start_or_join_live_scan(
            days=days,
            requested_account=active_acc,
            browser_accounts=browser_accs,
            scan_mode=scan_mode,
            async_mode=async_mode,
            session_id=req_sid,
            start_date=start_date,
            end_date=end_date,
            preset=eff_preset
        )
        if isinstance(res, dict):
            res["billingCalibration"] = get_billing_calibration_summary()
        self.send_json(res)

    def _reject_bad_origin(self, method: str) -> bool:
        ok, reason = request_origin_allowed(method, self.path, self.headers)
        if not ok:
            self.send_json({"success": False, "error": reason}, status=403)
        return not ok

    def do_GET(self):
        if self._reject_bad_origin("GET"):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if is_demo_mode() and parsed.path in ("/auth/google/start", "/oauth2callback", "/auth/google/callback"):
            self._redirect_home()  # demo mode: no Google sign-in, the demo login is already active
            return

        if parsed.path == "/auth/google/start":
            if not OAUTH_CONFIGURED:
                self.send_response(302)
                self.send_header("Location", "/?auth_error=" + urllib.parse.quote(OAUTH_NOT_CONFIGURED_MSG))
                self.end_headers()
                return
            login_hint = qs.get("login_hint", [None])[0]
            oauth_state = secrets.token_urlsafe(24)
            params = {
                "client_id": OAUTH_CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(OAUTH_SCOPES),
                "access_type": "offline",
                "prompt": "select_account consent",
                "state": oauth_state
            }
            if login_hint:
                params["login_hint"] = login_hint
            auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
            self.send_response(302)
            self.send_header("Set-Cookie", f"{OAUTH_STATE_COOKIE_NAME}={oauth_state}; Path=/; Max-Age=600; HttpOnly; SameSite=Lax")
            self.send_header("Location", auth_url)
            self.end_headers()
            return

        if parsed.path in ("/oauth2callback", "/auth/google/callback"):
            self._handle_oauth_callback_get(qs)
            return

        if parsed.path == "/api/auth/status":
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            req_sid = getattr(self, "_current_req_sid", None)
            demo_cookies = {}
            if is_demo_mode():
                # Demo mode: every browser is logged in as the invented demo account (the session cookie is issued here).
                demo_acc, demo_sid = demo_session_credentials()
                if not (req_sid and secrets.compare_digest(str(req_sid), str(demo_sid))):
                    req_acc, browser_accs, req_sid = demo_acc, [demo_acc], demo_sid
                    demo_cookies = {"set_account_cookie": demo_acc, "set_session_cookie": demo_sid}
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=req_sid)
            st.pop("accessToken", None)
            active_acc = st.get("activeAccount")
            self.send_json({
                "success": True,
                "auth": st,
                "scanProgress": get_scan_progress_snapshot(active_acc) if st.get("tokenValid") else None,
                "demo": is_demo_mode(),
                "oauthConfigured": OAUTH_CONFIGURED_AT_STARTUP,
            }, clear_cookie=not st.get("tokenValid"), **demo_cookies)
            return

        if parsed.path == "/api/scan/progress":
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            active_acc = st.get("activeAccount")
            if not active_acc or not st.get("tokenValid"):
                self.send_json({"success": False, "needsLogin": True}, 401)
                return
            self.send_json({"success": True, "progress": get_scan_progress_snapshot(active_acc)})
            return

        if parsed.path == "/api/projects-sync":
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            active_acc = st.get("activeAccount")
            if not active_acc or not st.get("tokenValid"):
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required. Sign in with Google.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            reg = ensure_account_sync_registry(active_acc)
            sync_summary = build_sync_summary_for_account(active_acc, reg)
            self.send_json({"success": True, "auth": st, "sync": sync_summary})
            return

        if parsed.path == "/api/budgets":
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            if not st.get("activeAccount") or not st.get("tokenValid"):
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            self.send_json({"success": True, "budgets": load_budgets(), "auth": st})
            return

        if parsed.path == "/api/models-pricing":
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            if not st.get("activeAccount") or not st.get("tokenValid"):
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            cfg = load_models_pricing_config()
            observed = compute_observed_models_summary(st.get("activeAccount"), cfg=cfg)
            self.send_json({
                "success": True,
                "config": sanitize_models_pricing_config_for_http(cfg),
                "modelsCount": len((cfg or {}).get("models") or {}),
                "observed": observed,
                "auth": st,
            })
            return

        if parsed.path == "/api/scan":
            self._handle_api_scan_get(qs)
            return

        if parsed.path == "/api/gemini-enterprise/inspect":
            if is_demo_mode():
                self._send_demo_blocked("Live resource inspection")
                return
            qs = urllib.parse.parse_qs(parsed.query)
            req_acc, browser_accs = self.get_browser_account_context(qs=qs)
            req_sid = getattr(self, "_current_req_sid", None)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=req_sid)
            token = st.get("accessToken")
            if not st.get("activeAccount") or not st.get("tokenValid") or not token:
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "OAuth session not authenticated today. Click 'Sign in with Google'.",
                }, 401)
                return
            pid = (qs.get("projectId", [""])[0] or "").strip()
            loc = (qs.get("location", ["eu"])[0] or "eu").strip()
            rtype = (qs.get("resourceType", ["ENGINE"])[0] or "ENGINE").strip()
            rid = (qs.get("resourceId", [""])[0] or "").strip()
            if not pid or not rid:
                self.send_json({"success": False, "error": "projectId and resourceId parameters are required"}, 400)
                return
            inspect_res = deep_inspect_gemini_resource_live(pid, loc, rtype, rid, token)
            self.send_json(inspect_res)
            return

        # Strict Static Whitelist: ONLY serve index.html. Block access to /data/*, /server.py, etc.
        if parsed.path in ("/", "/index.html"):
            index_path = os.path.join(RESOURCE_DIR, "index.html")
            try:
                with open(index_path, "rb") as f:
                    raw_html = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw_html)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
                self.send_header(csp_header_name(), build_csp(raw_html))
                self.end_headers()
                self.wfile.write(raw_html)
            except Exception as ex:
                self.send_json({"success": False, "error": f"Unable to load index.html: {ex}"}, 500)
            return

        if parsed.path.startswith("/Design/logos/") and parsed.path.endswith(".svg"):
            logo_name = parsed.path[len("/Design/logos/"):]
            if logo_name and logo_name == os.path.basename(logo_name) and "/" not in logo_name and "\\" not in logo_name:
                logo_path = os.path.join(RESOURCE_DIR, "Design", "logos", logo_name)
                if os.path.isfile(logo_path):
                    try:
                        with open(logo_path, "rb") as f:
                            raw_svg = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                        self.send_header("Content-Length", str(len(raw_svg)))
                        self.send_header("Cache-Control", "public, max-age=3600")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("X-Frame-Options", "SAMEORIGIN")
                        self.send_header("Referrer-Policy", "no-referrer")
                        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
                        self.end_headers()
                        self.wfile.write(raw_svg)
                        return
                    except OSError:
                        self.send_json({"success": False, "error": "Unable to load SVG resource."}, 500)
                        return

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_json({"success": False, "error": "Resource not found or access denied."}, 404)

    def do_POST(self):
        if self._reject_bad_origin("POST"):
            return
        parsed = urllib.parse.urlparse(self.path)
        if is_demo_mode() and parsed.path in DEMO_BLOCKED_POST_PATHS:
            self._send_demo_blocked(DEMO_BLOCKED_POST_PATHS[parsed.path])
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 20_000_000:
            self.send_json({"success": False, "error": "Request body exceeds the 20 MB limit."}, 413)
            return
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
        try:
            req = json.loads(body) if body else {}
        except Exception:
            req = {}

        if parsed.path == "/api/auth/switch":
            account = (req.get("account") or "").strip()
            _, browser_accs = self.get_browser_account_context(body_dict=req)
            req_sid = getattr(self, "_current_req_sid", None)
            if not account:
                self.send_json({"success": False, "error": "Missing account"}, 400)
                return
            if account not in browser_accs:
                browser_accs.append(account)
            st = get_auth_status_for_browser(account, browser_accs, session_id=req_sid)
            st.pop("accessToken", None)
            if not st.get("tokenValid") or st.get("activeAccount") != account:
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or f"Account {account} has no active session for today ({get_today_date_str()}). Please sign in.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            self.send_json({"success": True, "auth": st}, set_account_cookie=account, set_session_cookie=st.get("sessionId"))
            return

        if parsed.path == "/api/auth/logout":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            req_sid = getattr(self, "_current_req_sid", None)
            store = load_tokens_store()
            accounts_map = store.get("accounts", {})
            target_logout = (req.get("account") or req_acc or "").strip()
            if target_logout and target_logout in accounts_map:
                expected_sid = accounts_map[target_logout].get("session_id")
                if req_sid and expected_sid and secrets.compare_digest(str(req_sid), str(expected_sid)):
                    accounts_map.pop(target_logout, None)
                    save_tokens_store(store)
            RAM_PAYLOAD_CACHE.clear()
            self.send_json({
                "success": True,
                "auth": {
                    "accounts": [],
                    "activeAccount": None,
                    "tokenValid": False,
                    "needsLogin": True,
                    "dailyZeroTrust": True,
                    "loginDate": get_today_date_str(),
                    "tokenError": "Session disconnected in this browser. Click 'Sign in with Google' to connect an account."
                }
            }, clear_cookie=True)
            return

        if parsed.path == "/api/data/purge":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            active_acc = st.get("activeAccount")
            if not active_acc or not st.get("tokenValid"):
                self.send_json({"success": False, "needsLogin": True, "error": "Invalid daily session. Please sign in."}, 401, clear_cookie=True)
                return
            res = purge_account_local_data(active_acc)
            self.send_json(res, 200 if res.get("success") else (409 if res.get("scanInProgress") else 400))
            return

        if parsed.path == "/api/projects-sync/toggle":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            st.pop("accessToken", None)
            active_acc = st.get("activeAccount")
            if not active_acc or not st.get("tokenValid"):
                self.send_json({"success": False, "needsLogin": True, "error": "Invalid daily session. Please sign in."}, 401, clear_cookie=True)
                return

            reg = ensure_account_sync_registry(active_acc)
            acc_reg = reg.setdefault("accounts", {}).setdefault(active_acc, {"account": active_acc, "projects": {}})
            reg_projects = acc_reg.setdefault("projects", {})

            action = req.get("action")  # optional: 'apply_auto_rule', 'enable_all', 'disable_all', 'only_with_cost'
            project_ids = req.get("projectIds") or ([] if not req.get("projectId") else [req.get("projectId")])
            scan_enabled = req.get("scanEnabled")

            if action == "apply_auto_rule":
                for _pid, entry in reg_projects.items():
                    has_d = bool(
                        entry.get("hasAiData", False)
                        or entry.get("aiActive", False)
                        or (entry.get("enabledApisCount", 0) or 0) > 0
                        or (entry.get("estimatedCostUsd", 0.0) or 0.0) > 0
                        or (entry.get("inferenceRequests", 0) or 0) > 0
                    )
                    entry["hasAiData"] = has_d
                    entry["scanEnabled"] = has_d
                    entry["scanRule"] = "AUTO_INCLUDE_HAS_DATA" if has_d else "AUTO_EXCLUDE_NO_DATA"
            elif action == "enable_all":
                for _pid, entry in reg_projects.items():
                    entry["scanEnabled"] = True
                    entry["scanRule"] = "MANUAL_INCLUDE"
            elif action == "disable_empty":
                for _pid, entry in reg_projects.items():
                    has_d = bool(
                        entry.get("hasAiData", False)
                        or entry.get("aiActive", False)
                        or (entry.get("enabledApisCount", 0) or 0) > 0
                        or (entry.get("estimatedCostUsd", 0.0) or 0.0) > 0
                        or (entry.get("inferenceRequests", 0) or 0) > 0
                    )
                    entry["hasAiData"] = has_d
                    if not has_d:
                        entry["scanEnabled"] = False
                        entry["scanRule"] = "AUTO_EXCLUDE_NO_DATA"
            elif action == "only_with_cost":
                for _pid, entry in reg_projects.items():
                    has_cost = (entry.get("estimatedCostUsd", 0.0) or 0.0) > 0
                    entry["scanEnabled"] = has_cost
                    entry["scanRule"] = "AUTO_INCLUDE_HAS_DATA" if has_cost else "MANUAL_EXCLUDE"
            else:
                for pid in project_ids:
                    if pid in reg_projects:
                        new_state = bool(scan_enabled) if scan_enabled is not None else (not reg_projects[pid].get("scanEnabled", False))
                        reg_projects[pid]["scanEnabled"] = new_state
                        reg_projects[pid]["scanRule"] = "MANUAL_INCLUDE" if new_state else "MANUAL_EXCLUDE"

            save_sync_registry(reg)
            RAM_PAYLOAD_CACHE.clear()
            sync_summary = build_sync_summary_for_account(active_acc, reg)
            self.send_json({"success": True, "sync": sync_summary})
            return

        if parsed.path in ("/api/projects-sync/force-scan", "/api/project-scan"):
            project_id = (req.get("projectId") or "").strip()
            days = int(req.get("days") or 30)
            if not project_id:
                self.send_json({"success": False, "error": "Missing projectId"}, 400)
                return
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            req_sid = getattr(self, "_current_req_sid", None)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=req_sid)
            if not st.get("activeAccount") or not st.get("tokenValid"):
                st.pop("accessToken", None)
                self.send_json({"success": False, "needsLogin": True, "error": "Daily authentication required.", "auth": st}, 401, clear_cookie=True)
                return
            RAM_PAYLOAD_CACHE.clear()
            res = force_scan_single_project(
                project_id=project_id,
                days=days,
                requested_account=st.get("activeAccount"),
                browser_accounts=browser_accs,
                session_id=req_sid
            )
            if isinstance(res, dict):
                res["billingCalibration"] = get_billing_calibration_summary()
            self.send_json(res)
            return

        if parsed.path in ("/api/killswitch/toggle", "/api/budgets"):
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            if not st.get("activeAccount") or not st.get("tokenValid"):
                st.pop("accessToken", None)
                self.send_json({"success": False, "needsLogin": True, "error": "Daily authentication required.", "auth": st}, 401, clear_cookie=True)
                return
            pid = req.get("projectId")
            block_action = bool(req.get("block", True))

            budgets = load_budgets()
            p_cfg = budgets.setdefault("projects", {}).setdefault(pid, {"budgetUsd": 100.0, "blocked": False})
            if "budgetUsd" in req:
                p_cfg["budgetUsd"] = float(req.get("budgetUsd") or 100.0)
            if "block" in req:
                p_cfg["blocked"] = block_action
            p_cfg["updatedAt"] = datetime.now(timezone.utc).isoformat()
            save_budgets(budgets)
            RAM_PAYLOAD_CACHE.clear()

            self.send_json({
                "success": True,
                "projectId": pid,
                "blocked": p_cfg["blocked"],
                "budgetUsd": p_cfg["budgetUsd"],
                "detail": "READ-ONLY mode active: state saved locally in the demo only (no changes sent to GCP)."
            })
            return

        if parsed.path == "/api/models-pricing/sync":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            token = st.get("accessToken")
            active_acc = st.get("activeAccount")
            st.pop("accessToken", None)
            if not active_acc or not st.get("tokenValid") or not token:
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            if not MODELS_PRICING_SYNC_LOCK.acquire(blocking=False):
                self.send_json({
                    "success": False,
                    "error": "Price list sync already in progress."
                }, 409)
                return
            try:
                quota_cands = get_quota_project_candidates(active_acc)
                cfg = sync_models_and_pricing_from_gcp_api(
                    token, user_project=(quota_cands[0] if quota_cands else None), quota_candidates=quota_cands
                )
                bq_auto_on = bool(normalize_billing_calibration_block(
                    load_models_pricing_config().get("billingCalibration")).get("bigqueryAutoSync"))
                if bq_auto_on and "discover_and_calibrate_bigquery_billing" in globals():
                    with contextlib.suppress(Exception):
                        bq_res = discover_and_calibrate_bigquery_billing(
                            token=token,
                            active_acc=active_acc,
                            quota_candidates=quota_cands,
                            auto_apply=True,
                            force_apply=False,
                        )
                        if isinstance(bq_res, dict) and isinstance(bq_res.get("config"), dict):
                            cfg = bq_res["config"]
                reprice_stats = {"repriced": 0, "skipped": 0}
                try:
                    res_stats = reprice_all_cached_payloads(active_acc)
                    if isinstance(res_stats, dict):
                        reprice_stats = res_stats
                except Exception:
                    reprice_stats = {"repriced": 0, "skipped": 0}
                RAM_PAYLOAD_CACHE.clear()
                observed = compute_observed_models_summary(active_acc, cfg=cfg)
                self.send_json({
                    "success": True,
                    "config": sanitize_models_pricing_config_for_http(cfg),
                    "modelsCount": len((cfg or {}).get("models") or {}),
                    "observed": observed,
                    "auth": st,
                    "repriced": int(reprice_stats.get("repriced", 0)),
                    "skipped": int(reprice_stats.get("skipped", 0)),
                })
            finally:
                MODELS_PRICING_SYNC_LOCK.release()
            return

        if parsed.path == "/api/models-pricing/config":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            active_acc = st.get("activeAccount")
            st.pop("accessToken", None)
            if not active_acc or not st.get("tokenValid"):
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st
                }, 401, clear_cookie=True)
                return
            ok, err_msg, cfg = validate_and_apply_models_pricing_update(req)
            if not ok:
                self.send_json({"success": False, "error": err_msg}, 400)
                return
            reprice_stats = {"repriced": 0, "skipped": 0}
            try:
                res_stats = reprice_all_cached_payloads(active_acc)
                if isinstance(res_stats, dict):
                    reprice_stats = res_stats
            except Exception:
                reprice_stats = {"repriced": 0, "skipped": 0}
            RAM_PAYLOAD_CACHE.clear()
            observed = compute_observed_models_summary(active_acc, cfg=cfg)
            self.send_json({
                "success": True,
                "config": sanitize_models_pricing_config_for_http(cfg),
                "modelsCount": len((cfg or {}).get("models") or {}),
                "observed": observed,
                "auth": st,
                "repriced": int(reprice_stats.get("repriced", 0)),
                "skipped": int(reprice_stats.get("skipped", 0)),
            })
            return

        if parsed.path == "/api/models-pricing/calibrate-bigquery":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            token = st.get("accessToken")
            active_acc = st.get("activeAccount")
            st.pop("accessToken", None)
            if not active_acc or not st.get("tokenValid") or not token:
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st,
                }, 401, clear_cookie=True)
                return
            if not MODELS_PRICING_SYNC_LOCK.acquire(blocking=False):
                self.send_json({
                    "success": False,
                    "error": "Another pricing sync or calibration is already in progress.",
                }, 409)
                return
            try:
                quota_cands = get_quota_project_candidates(active_acc)
                explicit_tbl = req.get("billingExportTable") if isinstance(req, dict) else None
                res_bq = discover_and_calibrate_bigquery_billing(
                    token=token,
                    active_acc=active_acc,
                    quota_candidates=quota_cands,
                    explicit_table=explicit_tbl,
                    auto_apply=True,
                    force_apply=True,
                )
                if not res_bq.get("success"):
                    self.send_json({"success": False, "error": res_bq.get("error") or "BigQuery calibration failed."}, 400)
                    return
                cfg = res_bq.get("config") or load_models_pricing_config()
                reprice_stats = {"repriced": 0, "skipped": 0}
                if res_bq.get("applied"):
                    with contextlib.suppress(Exception):
                        rs = reprice_all_cached_payloads(active_acc)
                        if isinstance(rs, dict):
                            reprice_stats = rs
                RAM_PAYLOAD_CACHE.clear()
                observed = compute_observed_models_summary(active_acc, cfg=cfg)
                self.send_json({
                    "success": True,
                    "bigqueryStatus": res_bq.get("bigqueryStatus"),
                    "applied": bool(res_bq.get("applied")),
                    "config": sanitize_models_pricing_config_for_http(cfg),
                    "modelsCount": len((cfg or {}).get("models") or {}),
                    "observed": observed,
                    "auth": st,
                    "repriced": int(reprice_stats.get("repriced", 0)),
                    "skipped": int(reprice_stats.get("skipped", 0)),
                })
            finally:
                MODELS_PRICING_SYNC_LOCK.release()
            return

        if parsed.path == "/api/models-pricing/calibrate-csv":
            req_acc, browser_accs = self.get_browser_account_context(body_dict=req)
            st = get_auth_status_for_browser(req_acc, browser_accs, session_id=getattr(self, "_current_req_sid", None))
            active_acc = st.get("activeAccount")
            st.pop("accessToken", None)
            if not active_acc or not st.get("tokenValid"):
                self.send_json({
                    "success": False,
                    "needsLogin": True,
                    "error": st.get("tokenError") or "Daily authentication required.",
                    "auth": st,
                }, 401, clear_cookie=True)
                return
            if not MODELS_PRICING_SYNC_LOCK.acquire(blocking=False):
                self.send_json({
                    "success": False,
                    "error": "Another pricing sync or calibration is already in progress.",
                }, 409)
                return
            try:
                ok, err_msg, cfg = calibrate_from_csv_uploads((req or {}).get("files"))
                if not ok:
                    self.send_json({"success": False, "error": err_msg}, 400)
                    return
                reprice_stats = {"repriced": 0, "skipped": 0}
                with contextlib.suppress(Exception):
                    rs = reprice_all_cached_payloads(active_acc)
                    if isinstance(rs, dict):
                        reprice_stats = rs
                RAM_PAYLOAD_CACHE.clear()
                observed = compute_observed_models_summary(active_acc, cfg=cfg)
                self.send_json({
                    "success": True,
                    "config": sanitize_models_pricing_config_for_http(cfg),
                    "modelsCount": len((cfg or {}).get("models") or {}),
                    "observed": observed,
                    "auth": st,
                    "repriced": int(reprice_stats.get("repriced", 0)),
                    "skipped": int(reprice_stats.get("skipped", 0)),
                })
            finally:
                MODELS_PRICING_SYNC_LOCK.release()
            return

        self.send_json({"success": False, "error": "Endpoint not found"}, 404)


def _open_app_browser(url: str):
    with contextlib.suppress(OSError):
        if hasattr(os, "startfile"):
            os.startfile(url)  # nosec B606 - opens the app's own local URL in the default browser (Windows)
            return
    with contextlib.suppress(Exception):
        import webbrowser
        webbrowser.open(url, new=1)


def _is_our_server_already_running(host: str, port: int) -> bool:
    with contextlib.suppress(OSError, ValueError, http.client.HTTPException):
        check_host = LOOPBACK_HOST if host in ("0.0.0.0", "::") else host  # noqa: S104  # nosec B104 - comparison, not a bind
        conn = http.client.HTTPConnection(check_host, int(port), timeout=1.5)
        try:
            conn.request("GET", "/api/auth/status")
            resp = conn.getresponse()
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return isinstance(data, dict) and "auth" in data
        finally:
            conn.close()
    return False


def _console_write(msg: str, flush: bool = False):
    sys.stdout.write(msg + "\n")
    if flush:
        sys.stdout.flush()


def run_server():
    global PORT, REDIRECT_URI, COOKIE_NAME, SESSION_COOKIE_NAME, OAUTH_STATE_COOKIE_NAME
    server = None
    for candidate_port in [PORT] + list(range(PORT + 1, PORT + 15)):
        try:
            PORT = candidate_port
            REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", f"http://{LOOPBACK_HOST}:{PORT}/oauth2callback")
            COOKIE_NAME = f"gcp_monitor_account_{PORT}"
            SESSION_COOKIE_NAME = f"gcp_monitor_sid_{PORT}"
            OAUTH_STATE_COOKIE_NAME = f"gcp_oauth_state_{PORT}"
            server = ThreadingHTTPServer((HOST, PORT), MonitorHandler)
            break
        except OSError:
            if candidate_port == PORT and _is_our_server_already_running(HOST, candidate_port):
                existing_url = os.environ.get("PUBLIC_BASE_URL", f"http://{LOOPBACK_HOST}:{candidate_port}")
                _console_write("============================================================")
                _console_write(f" ✅ GCP AI Cost Control Tower is already running at {existing_url}")
                _console_write(" 🌐 Opening the browser on the running instance...")
                _console_write("============================================================", flush=True)
                _open_app_browser(existing_url)
                sys.exit(0)
            continue

    if server is None:
        _console_write(f"❌ Unable to start the server: ports {PORT - 14}..{PORT} are in use.", flush=True)
        sys.exit(1)

    app_url = f"http://{LOOPBACK_HOST}:{PORT}" if is_demo_mode() else os.environ.get("PUBLIC_BASE_URL", f"http://{LOOPBACK_HOST}:{PORT}")
    _console_write("============================================================")
    if is_demo_mode():
        _console_write(" 🎭 DEMO MODE: invented data (Acme Corp), no Google Cloud access, no real data")
        _console_write(f" 🎭 Sample data lives in a temporary folder removed at exit: {DATA_DIR}")
        if str(os.environ.get(DEMO_ENV_VAR, "")).strip().lower() in ("1", "true", "yes", "on"):
            _console_write(f" 🎭 Why: {DEMO_ENV_VAR} is set. Use {DEMO_ENV_VAR}=0 for the real mode.")
        else:
            _console_write(f" 🎭 Why: no Google OAuth client found (GCP_OAUTH_CLIENT_ID / GCP_OAUTH_CLIENT_SECRET in the environment or .env). Set both for the real mode, or {DEMO_ENV_VAR}=0.")
        if HOST not in ("127.0.0.1", "localhost", "::1"):
            _console_write(f" ⚠️  Demo mode is listening on {HOST}: anyone who can reach this port sees the invented data. Publish the port on 127.0.0.1 only.")
    _console_write(" 🚀 JanusTower - AI FinOps & Security Posture Control Tower (100% Read-Only)")
    _console_write(f" 🔒 Daily Zero-Trust Mode | Host: {HOST}:{PORT}")
    _console_write(f" 🌐 URL: {app_url}")
    if not OAUTH_CONFIGURED and not is_demo_mode():
        _console_write(f" ⚠️  {OAUTH_NOT_CONFIGURED_MSG}")
    _console_write("============================================================", flush=True)
    if IS_FROZEN or os.environ.get("AUTO_OPEN_BROWSER") == "1":
        threading.Timer(0.8, lambda: _open_app_browser(app_url)).start()
    if is_demo_mode():
        # a plain SIGTERM would skip the atexit hook that removes the temporary demo folder
        with contextlib.suppress(ValueError, OSError):
            import signal
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _console_write("\nServer stopped.", flush=True)


bootstrap_demo_data()  # demo mode only (no-op otherwise): fills the temporary DATA_DIR with the invented dataset

if __name__ == "__main__" and globals().get("_DEFER_AUTORUN") is not True:
    run_server()
