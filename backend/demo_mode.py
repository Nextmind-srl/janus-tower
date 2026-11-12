"""Demo mode: try JanusTower without Google, with invented data ("Acme Corp"), never touching real data.

This file is the FIRST backend module (see BACKEND_MODULES in server.py): everything below runs before config.py,
because the demo decides where the data directory lives and whether `.env` is read at all.

The switch is decided ONCE, at startup, from the process environment (and the `.env` file), and nowhere else:
no request, query string, header or body can turn it on or off.

  * JANUSTOWER_DEMO=1  -> demo mode ON
  * JANUSTOWER_DEMO=0  -> demo mode OFF, always (real mode)
  * unset / empty      -> demo mode ON only when the Google OAuth client is NOT configured
                          (GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET both set = configured)

In demo mode:
  * DATA_DIR is a fresh temporary directory (never inside the repository), filled at startup with invented data
    (scan cache, sync registry, pricing config, budgets, a demo login). `<repo>/data` is never read or written.
  * `.env` is not read, no OAuth client is held in memory, the Host allow-list is fixed to the loopback names (HOST keeps its default of 127.0.0.1).
  * No request leaves the machine: every Google API helper raises DemoModeError (see gcp_api_get / gcp_api_post and
    the urllib3 pool in auth_gcp.py); the OAuth routes redirect to "/"; live scan / sync POSTs answer 403.
"""

import os
import sys
import atexit as _jt_atexit
import shutil as _jt_shutil
import tempfile as _jt_tempfile

DEMO_ENV_VAR = "JANUSTOWER_DEMO"
_DEMO_TRUE_VALUES = ("1", "true", "yes", "on")
_DEMO_FALSE_VALUES = ("0", "false", "no", "off")


class DemoModeError(RuntimeError):
    """Raised by every code path that would reach Google (or any remote host) while demo mode is on."""


def parse_demo_flag(value) -> bool | None:
    """True / False for an explicit JANUSTOWER_DEMO value, None for unset, empty or unrecognised (= automatic)."""
    text = str(value or "").strip().lower()
    if text in _DEMO_TRUE_VALUES:
        return True
    if text in _DEMO_FALSE_VALUES:
        return False
    return None


def read_dotenv_values(path: str) -> dict:
    """Read-only parse of a `.env` file (KEY=VALUE, # comments). Unlike config.load_dotenv_file it never touches os.environ."""
    values: dict = {}
    if not os.path.isfile(path):
        return values
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key:
                    values.setdefault(key, value)
    except (OSError, UnicodeDecodeError):
        return {}
    return values


def oauth_client_configured(environ, dotenv_values: dict) -> bool:
    """True when both GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET are set (a real environment variable wins over `.env`,
    exactly like config.py: an empty variable in the environment is not replaced by the `.env` value)."""
    def pick(name: str) -> str:
        return str(environ[name] if name in environ else dotenv_values.get(name, "")).strip()
    return bool(pick("GCP_OAUTH_CLIENT_ID") and pick("GCP_OAUTH_CLIENT_SECRET"))


def decide_demo_mode(environ, dotenv_values: dict | None = None) -> bool:
    """Pure activation rule (see the module docstring). `environ` and `dotenv_values` are plain mappings."""
    dotenv_values = dotenv_values or {}
    flag = parse_demo_flag(environ[DEMO_ENV_VAR] if DEMO_ENV_VAR in environ else dotenv_values.get(DEMO_ENV_VAR, ""))
    if flag is not None:
        return flag
    return not oauth_client_configured(environ, dotenv_values)


def _demo_base_dir() -> str:
    """Same base directory as config.BASE_DIR (the repository root, or the folder of the frozen executable)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here) if os.path.basename(here).lower() == "backend" else here


def _make_demo_data_dir(repo_dir: str) -> str:
    """A new empty temporary directory, refused if it would sit inside the repository (so `<repo>/data` can never be it)."""
    path = os.path.realpath(_jt_tempfile.mkdtemp(prefix="janustower-demo-"))
    repo_real = os.path.realpath(repo_dir)
    if path == repo_real or path.startswith(repo_real + os.sep):
        _jt_shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError("Demo mode refused to start: the temporary directory is inside the repository. Set TMPDIR elsewhere.")
    _jt_atexit.register(_jt_shutil.rmtree, path, True)
    return path


# `_JT_DEMO_ENRICH_ONLY` is set by backend/demo_data.py when it loads a private copy of the backend just to enrich a payload:
# that copy is inert (temporary DATA_DIR, nothing populated), so it can never reach <repo>/data.
DEMO_ENRICH_ONLY = bool(globals().get("_JT_DEMO_ENRICH_ONLY"))
_DEMO_REPO_DIR = _demo_base_dir()
_DEMO_DOTENV = read_dotenv_values(os.path.join(_DEMO_REPO_DIR, ".env"))
# Decided once, here. Nothing below (or anywhere else) reassigns these names.
DEMO_MODE = True if DEMO_ENRICH_ONLY else decide_demo_mode(os.environ, _DEMO_DOTENV)
# Whether a Google OAuth client was configured at startup (environment or `.env`); reported by /api/auth/status.
OAUTH_CONFIGURED_AT_STARTUP = oauth_client_configured(os.environ, _DEMO_DOTENV)
DEMO_DATA_DIR = _make_demo_data_dir(_DEMO_REPO_DIR) if DEMO_MODE else None
del _DEMO_DOTENV  # the `.env` content is not kept in memory

DEMO_SESSION_ID = None  # random per process, set by bootstrap_demo_data()
_DEMO_MODULE = None


def is_demo_mode() -> bool:
    """True when the app runs on invented data. Computed once at startup; cannot change while the process runs."""
    return DEMO_MODE


def demo_disabled_message(what: str) -> str:
    return f"{what} is disabled in demo mode: this instance has no Google Cloud access and no real data."


def demo_block_network(what: str) -> None:
    """Call before any code that would reach a remote host: raises DemoModeError in demo mode, does nothing otherwise."""
    if DEMO_MODE:
        raise DemoModeError(demo_disabled_message(what))


def demo_session_credentials() -> tuple[str, str]:
    """(account, session id) of the demo login, handed to the browser by /api/auth/status in demo mode."""
    return _DEMO_MODULE.DEMO_ACCOUNT, DEMO_SESSION_ID


def _load_demo_data_module():
    """Loads backend/demo_data.py as its own module (its helper names must not leak into the shared backend namespace)."""
    import importlib.util
    path = os.path.join(RESOURCE_DIR, "backend", "demo_data.py")
    if not os.path.isfile(path):
        raise RuntimeError(f"Demo mode needs {path}, which is missing from this installation.")
    spec = importlib.util.spec_from_file_location("janustower_demo_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def demo_ensure_token_store() -> None:
    """Keeps the demo login valid: the daily Zero-Trust policy purges yesterday's login, so a demo left running past
    midnight gets a fresh entry (same account and session id). Only ever writes inside the temporary DATA_DIR."""
    if not DEMO_MODE or DEMO_ENRICH_ONLY or _DEMO_MODULE is None or DATA_DIR != DEMO_DATA_DIR:
        return
    today = get_today_date_str()
    current = None
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                current = (json.load(f).get("accounts") or {}).get(_DEMO_MODULE.DEMO_ACCOUNT)
        except (OSError, ValueError, AttributeError, TypeError):
            current = None
    now_ts = time.time()
    if isinstance(current, dict) and current.get("login_date") == today and float(current.get("daily_expires_at", 0) or 0) > now_ts \
            and current.get("session_id") == DEMO_SESSION_ID:
        return
    store = _DEMO_MODULE.build_demo_token_store(today, DEMO_SESSION_ID, now_ts, now_ts + get_seconds_until_midnight())
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


def bootstrap_demo_data() -> None:
    """Fills the temporary DATA_DIR with the invented dataset. Called once at startup, after every backend module is loaded.

    Written files (all inside DATA_DIR, which is a temporary directory): the scan caches (30 and 90 days, enriched by the
    app's own enrich_scan_payload_security), the sync registry, the models pricing config, the budgets and the demo login
    (no refresh token, a placeholder access token)."""
    global DEMO_SESSION_ID, _DEMO_MODULE
    if not DEMO_MODE or DEMO_ENRICH_ONLY:
        return
    if DATA_DIR != DEMO_DATA_DIR or os.path.realpath(DATA_DIR) == os.path.realpath(os.path.join(BASE_DIR, "data")):
        raise RuntimeError("Demo mode refused to start: DATA_DIR is not the temporary demo directory.")
    mod = _load_demo_data_module()
    _DEMO_MODULE = mod
    DEMO_SESSION_ID = secrets.token_urlsafe(24)
    ref = datetime.now(timezone.utc).date()
    ref_str = ref.isoformat()

    payload_30 = None
    for days in (30, 90):
        payload = mod.build_demo_scan_payload(days=days, reference_date=ref_str, enrich=True, enricher=enrich_scan_payload_security)
        payload["fromCache"] = True
        with open(get_account_cache_path(mod.DEMO_ACCOUNT, days), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        if days == 30:
            payload_30 = payload

    save_sync_registry(mod.build_demo_sync_registry(payload_30["projects"], ref))
    save_models_pricing_config(mod.build_demo_models_pricing_config(ref_str, base=_build_default_models_pricing_config()))
    save_budgets({
        "projects": {p["projectId"]: {"budgetUsd": p.get("budgetUsd", 100.0), "blocked": False, "updatedAt": payload_30["scannedAt"]}
                     for p in payload_30["projects"] if p.get("budgetUsd")},
        "credentials": {},
    })
    demo_ensure_token_store()
    RAM_PAYLOAD_CACHE.clear()
