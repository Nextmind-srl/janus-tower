# 🏛️ AI Agent Context — JanusTower

> **Purpose of this file**: give any AI coding agent (Claude Code, Cursor, Copilot, …) or new developer the architectural context needed to change **JanusTower** safely. Keep it in sync with the code.

---

## 1. System overview

JanusTower is a **local, single-user, read-only** web app (Python 3.11+ backend + single-page frontend) that inspects the Google Cloud projects visible to the signed-in user and shows:

1. **AI FinOps (estimated)**: calls and tokens from Cloud Monitoring (`aiplatform.googleapis.com`, `generativelanguage.googleapis.com`) multiplied by the price table `MODEL_PRICING_PER_1M` in `backend/config.py`. There is **no** BigQuery billing export or invoice CSV reconciliation (roadmap).
2. **Identity & Shadow AI attribution**: Cloud Audit Logs correlated with API keys, service accounts, OAuth workloads and human users.
3. **Agents & Gemini Enterprise** (`backend/gemini_enterprise.py`): Agentspace apps, data stores, connectors, licenses, session metadata, Reasoning Engines, Dialogflow CX, Agent Registry (agents and MCP servers); plus an on-demand read-only REST probe (`GET /api/gemini-enterprise/inspect`). There is **no** live MCP JSON-RPC inspector (roadmap).
4. **AI security posture** (`backend/security_posture.py`): 0–100 score, findings, `gcloud` remediation commands, Model Armor, data residency (EU vs non-EU).

---

## 2. Architecture

### Backend (`server.py` + `backend/`)
- **Shared namespace**: `server.load_backend_modules()` executes `backend/*.py` **in the order of `BACKEND_MODULES`** into ONE global namespace. Files use names defined by earlier files without importing them (that is why ruff ignores F821/F401/E402 for `backend/*.py`). A new top-level name must not collide with an existing one.
- `config.py`: `.env` loader (`load_dotenv_file`, real env vars win), host/port, `data/` paths, OAuth settings (`GCP_OAUTH_CLIENT_ID`, `GCP_OAUTH_CLIENT_SECRET`; **no built-in client** — `OAUTH_CONFIGURED` false ⇒ login fails closed), `MODEL_PRICING_PER_1M` (built-in Google seed models only), neutral `DEFAULT_BILLING_SETTINGS` (saved as `billingSettings`: `0%` discounts, `0%` implicit cache hit, `1.10×` regional multiplier), `VERTEX_OAUTH_CLIENT_OWNERS` (empty by default), `get_model_rates(model_id, location="")` (longest-key match + explicit regional SKU or multiplier), `load_models_pricing_config` / `save_models_pricing_config` (`data/models_pricing_config.json`, preserving `manualOverride` entries), `sync_models_and_pricing_from_gcp_api` (Vertex Publisher Models list read across pages, trying up to several quota projects; Cloud Billing Catalog SKUs read by the generic `parse_catalog_sku`/`build_catalog_rates` into per-model, per-modality rates; per model `status` `active`/`deleted` + `deletedAt`, `pricingStatus` `CATALOG`/`NO_CATALOG_PRICE`, `catalog`; the list changes only when `lastApiSync.listAuthoritative` is true, i.e. the Google publisher list was read completely; non-Google ids not returned by any Google service are removed; manual overrides, `geminiApiRates` and cache shares are never overwritten; batch/priority/flex, long-context and Live API SKUs are skipped; more than 10 publisher pages is not authoritative; `modelListFromApi` stops the loader from resurrecting removed built-ins; `lastApiSync.modelsDeleted`/`modelsRemoved`/`quotaProject`; `save_models_pricing_config` writes via temp file + `os.replace`, an unreadable file is renamed `.corrupt-<ts>`), `register_observed_models_in_pricing_config`, service catalog, budgets.
- `auth_gcp.py`: OAuth token store `data/oauth_tokens.json` (daily expiry), `get_auth_status_for_browser()`, scan progress state, read-only Google API helpers `gcp_api_get` / `gcp_api_post`, and paginated `fetch_monitoring_timeseries()` (`nextPageToken` loop up to 25 pages).
- `gemini_enterprise.py`, `gcp_discovery.py`, `project_inspector.py`, `security_posture.py`: scanning and calculations (distinguishing HTTP `429` rate limits from `403`, excluding support-only APIs from `hasAiApiEnabled`, attributing `oauth_client` tokens and reconciling user OAuth cost via `max(shared_oauth_pool, sum_direct_oauth_cost)`).
- `sync_registry.py`: scan orchestration (`start_or_join_live_scan`, single scan at a time), once-per-UTC-day automatic pricing sync (`_should_auto_sync_models_pricing`), exact credential-sum slicing in `slice_cached_payload_for_days`, per-account cache files `data/scan_cache_v9_<account>_<period>d.json`, synced-project list `data/projects_sync_registry.json` (never auto-excluding projects hit by `429`), `purge_account_local_data()`.
- `http_routes.py`: `MonitorHandler` (access log without query strings) and `run_server()`.

### REST API (all `/api/*` except `/api/auth/status` and `/api/auth/logout` require today's session for the requesting browser)
| Method | Path | Purpose |
| :--- | :--- | :--- |
| GET | `/auth/google/start`, `/oauth2callback` (alias `/auth/google/callback`) | OAuth login (redirects to `/?autostart=1`, no session id in the URL; the frontend then relies on the HttpOnly cookie) |
| GET | `/api/auth/status` | Session state for this browser |
| POST | `/api/auth/switch`, `/api/auth/logout` | Switch account / sign out this browser |
| GET | `/api/scan` | Cached (`cached=1`) or live scan (`async=1` for background) |
| GET | `/api/scan/progress` | Live scan progress |
| GET/POST | `/api/projects-sync`, `/api/projects-sync/toggle`, `/api/projects-sync/force-scan` (alias `/api/project-scan`) | Synced-project list and single-project scan |
| GET/POST | `/api/budgets`, `/api/killswitch/toggle` | Local budgets only (nothing sent to Google Cloud) |
| GET | `/api/models-pricing` | Current model pricing catalog (`data/models_pricing_config.json`), observed models from the latest scan, and sync state |
| POST | `/api/models-pricing/sync` | Trigger an on-demand read-only sync with Google Cloud Billing Catalog & Vertex Publisher APIs (`409` if already syncing) |
| POST | `/api/models-pricing/config` | Update `billingCreditRules` (`0..1` ratios, `1..2` regional multiplier), add/edit manual model overrides (`manualOverride: true`, `source: "MANUAL"`), or `resetToDefaults` |
| GET | `/api/gemini-enterprise/inspect` | Read-only live probe of one Agentspace resource |
| POST | `/api/data/purge` | Delete local scan data of the signed-in account (409 while its scan is running) |

Only `/` (`index.html`) and read-only SVG brand assets under `/Design/logos/<name>.svg` are served as static files.

### Frontend & Design System (`Design/` + `frontend/` → generated `index.html`)
- `Design/tokens.css`, `Design/components.css`, `Design/jt-theme.css`, `frontend/css/main.css`, `frontend/html/*.html`, and `frontend/js/*.js` (`core_and_auth.js`, `gemini_enterprise.js`, `views_dashboard_and_finops.js`, `views_pricing.js`, `views_security_and_modals.js`) are concatenated by `server.assemble_frontend_html()` into `index.html` (one inline `<style>` and one inline `<script>`; JS files share globals and communicate through global functions such as `refreshDashboardView`, `switchTab`, `openProjectModal`, `openUserModal`, `openGeminiInspectorModal`, `openPricingModelDrawer`).
- `Design/tokens.css` & `Design/components.css`: design tokens (`--jt-navy`, `--jt-amber`, `--jt-amber-700`, `--jt-blue`, `--jt-bg`, `--jt-font-sans`, `--jt-font-mono`, …) and top header bar `.jt-header` / `.jt-scope` / `.jt-menu` styles.
- `Design/jt-theme.css`: workspace theme (`body.jt-root`), collapsible sidebar (`.jt-sidebar` / `.jt-sidebar--collapsed`, `248px ↔ 68px`), `.jt-page-header`, `.jt-kpi`, `.jt-table-panel` / `.jt-table`, **`.jt-sticky-first`** (add to a `<table>` to keep its first column fixed on horizontal scroll), **`[data-jt-tip]` tooltips** (`jtTipChip(toneClasses, iconId, shortLabel, fullText)` in `core_and_auth.js`: compact chip with the detail in a floating tooltip; use it for any long badge in any table), **`jtExpandList(itemsHtml[], {visible, noun, stack, key})`** (shows the first N items and a "+N more" button that expands in place; `key` keeps the open state across re-renders; use it for long user/key/project lists), `.jt-tabs`, `.jt-badge--*` / `.jt-chip--*`, right-docked detail drawers (`.jt-drawer-backdrop` / `.jt-drawer` for `#project-modal`, `#user-modal`, `#gemini-inspector-modal`, `#pricing-model-modal`), and responsive rules.
- `core_and_auth.js`: global state (`globalScanData`), `escapeHtml`, `jsArg`, `setSafeHtml`/`sanitizeFragment`, `toneBadge(tone, text, opts)`, auth, scan polling, collapsible sidebar (`toggleSidebarCollapse`), navigation (`switchTab`, `switchSubTab`), `purgeLocalData`.
- `tools/calibra_da_csv.py`: offline, read-only helper that turns a Cloud Billing CSV (grouped by SKU, Italian number format) into a calibration proposal for the Billing settings; never applies anything. Tested with a synthetic CSV in `tests/test_calibra_da_csv.py`.
- `views_pricing.js`: **Pricing & Rates** view (`#view-pricing`, 3 top-level blocks: KPI grid, sync banner, and 3-tab panel `Model rates · Billing settings · Coverage`) and `#pricing-model-modal` SKU inspector / manual override drawer.
- `Design/contratto_ui.json` & `tests/test_ui_contract.py`: machine-verifiable UI contract covering all 11 views, DOM IDs, inline handlers, `data-*` attributes, `.fe-tbl-*` classes, and all 35 tables and column headers.

---

## 3. Golden rules for changes

1. **Edit `frontend/` or `Design/jt-theme.css`, never `index.html`**, then regenerate it:
   ```bash
   python -c "import server; server.assemble_frontend_html('.', write_to_disk=True)"
   ```
   `tests/test_app.py` fails if `index.html` is stale, and `tests/test_ui_contract.py` fails if any contracted DOM ID, handler, attribute, class, or table column is removed or broken.
2. **Escape every dynamic value in HTML templates**: `${escapeHtml(v)}` in text/attributes, `data-jt-click="fn(${jsArg(v)})"` for actions (delegated by `frontend/js/ui_actions.js`; never inline `on*` handlers, which the sanitizer strips and the CSP blocks; never `'${v}'`). Do not escape values that already are HTML built by the code (arrays of `<span>` badges, `toneBadge()`, `render*()` helpers). Insert HTML only via `setSafeHtml()`.
3. **Preserve DOM IDs and global function names**: check all 5 JS files, 3 HTML files, and `Design/contratto_ui.json` before renaming.
4. **Read-only towards Google Cloud**: no mutating API calls.
5. **Never commit runtime data or secrets**: `data/*.json`, `.env`, `*.csv` are ignored; scan caches can contain personal data.
6. **Before finishing**: `python -m unittest discover -s tests -v` and `ruff check .` must pass.
