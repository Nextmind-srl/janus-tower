"""
Read-only Cloud Billing calibration engine supporting 3 cost-parameter paths:
  1. BigQuery Cloud Billing Export (auto-discovered or user-configured table via BigQuery REST API v2)
  2. In-memory Cloud Billing CSV report upload (Italian and English number/header formats)
  3. Manual / Default list-price settings in Billing settings
"""
import csv
import io
import statistics

_BQ_CALIBRATION_LOCK = threading.Lock()
_BQ_CHECKED_DATE_BY_ACCOUNT: dict[str, str] = {}

_BQ_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{3,62}$")
_BQ_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,256}$")
_BQ_TABLE_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,256}$")

_CAL_MODEL_RE = re.compile(r"\bgemini\s+([0-9][^\n]*)", re.IGNORECASE)
_CAL_STOP_WORDS = {
    "text", "input", "output", "predictions", "cached", "caching", "cache", "storage",
    "image", "audio", "video", "speech", "grounding", "batch", "priority", "long",
    "short", "prompt", "response", "token", "tokens", "global", "regional", "multi",
}

_BQ_PRIORITY_PROJECT_HINTS = (
    "bill", "finops", "cost", "infra", "org", "admin", "central",
    "shared", "mgmt", "ops", "data", "bi", "analytics", "agentspace",
)
_BQ_DATASET_HINTS = ("bill", "export", "cost", "finops", "invoice", "spend")

# Official Google Cloud Billing CSV column names (English and Italian locales)
_CSV_COL_SERVICE = ("service description", "service", "descrizione servizio")
_CSV_COL_SERVICE_ID = ("service id", "id servizio")
_CSV_COL_SKU = ("sku description", "sku", "descrizione sku")
_CSV_COL_QTY = ("usage amount", "usage", "usage quantity", "amount", "quantità di utilizzo")
_CSV_COL_LIST = ("cost at list", "list cost", "gross cost", "costo di listino")
_CSV_COL_NEGOTIATED = ("negotiated savings", "risparmi negoziati")
_CSV_COL_OTHER = ("other savings", "total credits", "credits", "promotions and others", "altri risparmi")
_CSV_COL_SUBTOTAL = ("subtotal", "unrounded subtotal", "net cost", "cost", "subtotale", "costo")

_CAL_SERVICE_MAP = {
    "C7E2-9256-1C43": "Vertex AI",
    "AEFD-7695-64FA": "Gemini API",
    "vertex ai": "Vertex AI",
    "gemini api": "Gemini API",
    "generative language api": "Gemini API",
}


def build_default_billing_calibration() -> dict:
    return {
        "activeSource": "DEFAULT_LIST_PRICES",
        "manualOverride": False,
        "bigqueryAutoSync": False,
        "bigqueryStatus": "NOT_CHECKED",
        "bigqueryCheckedAt": None,
        "billingExportTable": "",
        "discoveredTable": "",
        "jobProject": "",
        "deniedTargets": [],
        "bigqueryMessage": "BigQuery Billing Export has not been checked yet. Run a scan, sync model rates, or click 'Detect & Calibrate from BigQuery'.",
        "calibratedAt": None,
        "csvFiles": [],
        "windowDays": 30,
        "rowCount": 0,
        "derivedSettings": {},
        "perModelGeminiCacheCount": 0,
        "notes": [],
    }


def normalize_billing_calibration_block(raw_cal: dict | None, billing_settings: dict | None = None) -> dict:
    base = build_default_billing_calibration()
    if isinstance(raw_cal, dict):
        for k in base:
            if k in raw_cal and raw_cal[k] is not None:
                base[k] = raw_cal[k]
    if base["activeSource"] not in ("BIGQUERY_EXPORT", "CSV_UPLOAD", "MANUAL", "DEFAULT_LIST_PRICES"):
        base["activeSource"] = "DEFAULT_LIST_PRICES"
    if base["bigqueryStatus"] not in ("OK", "PERMISSION_DENIED", "NOT_FOUND", "ERROR", "NOT_CHECKED"):
        base["bigqueryStatus"] = "NOT_CHECKED"
    base["manualOverride"] = bool(base.get("manualOverride"))
    # Off unless the user turned it on: BigQuery query jobs can be billed by Google
    base["bigqueryAutoSync"] = base.get("bigqueryAutoSync") is True
    base["billingExportTable"] = str(base.get("billingExportTable") or "").strip()[:320]
    base["discoveredTable"] = str(base.get("discoveredTable") or "").strip()[:320]
    base["jobProject"] = str(base.get("jobProject") or "").strip()[:80]
    base["deniedTargets"] = [str(x)[:200] for x in (base.get("deniedTargets") or []) if x][:8]
    base["csvFiles"] = [os.path.basename(str(x))[:120] for x in (base.get("csvFiles") or []) if x][:12]
    base["notes"] = [str(x)[:260] for x in (base.get("notes") or []) if x][:10]
    if not isinstance(base.get("derivedSettings"), dict):
        base["derivedSettings"] = {}

    # Upgrade existing installations that already had non-default discounts saved before billingCalibration existed
    if (
        base["activeSource"] == "DEFAULT_LIST_PRICES"
        and not base["calibratedAt"]
        and isinstance(billing_settings, dict)
    ):
        v_disc = float(billing_settings.get("vertexBillingCreditDiscountPct", 0.0) or 0.0)
        g_disc = float(billing_settings.get("geminiApiBillingCreditDiscountPct", 0.0) or 0.0)
        g_cache = float(billing_settings.get("geminiApiImplicitCacheHitRatioPct", 0.0) or 0.0)
        v_cache = float(billing_settings.get("vertexImplicitCacheHitRatioPct", 93.0) or 93.0)
        if v_disc > 0.0 or g_disc > 0.0 or g_cache > 0.0 or abs(v_cache - 93.0) > 0.05:
            base["activeSource"] = "MANUAL"
    return base


def parse_bigquery_table_ref(raw_ref: str) -> tuple[str, str, str] | None:
    """
    Parses 'project.dataset.table', 'project:dataset.table' or '`project.dataset.table`'.
    Returns (project_id, dataset_id, table_id) only if every identifier matches strict GCP syntax.
    """
    cleaned = str(raw_ref or "").strip().strip("`").strip("'").strip('"').strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace(":", ".", 1) if ":" in cleaned else cleaned
    parts = [p.strip() for p in cleaned.split(".") if p.strip()]
    if len(parts) != 3:
        return None
    proj, ds, tbl = parts
    if not (_BQ_PROJECT_ID_RE.match(proj) and _BQ_DATASET_ID_RE.match(ds) and _BQ_TABLE_ID_RE.match(tbl)):
        return None
    return proj, ds, tbl


def _cal_model_label_from_sku(sku: str) -> str | None:
    m = _CAL_MODEL_RE.search(sku or "")
    if not m:
        return None
    words = []
    for w in re.split(r"\s+", m.group(1).strip()):
        wl = w.lower().strip("-")
        if wl in _CAL_STOP_WORDS or wl == "":
            break
        words.append(wl)
    if not words:
        return None
    return "gemini-" + "-".join(w for w in words if w != "/")


def _cal_classify_sku(sku: str) -> dict | None:
    low = (sku or "").lower()
    if "gemini" not in low:
        return None
    if any(w in low for w in ("storage", "token hour", "token-hour", "per hour")):
        return None
    if "cach" in low:
        kind = "cache"
    elif "output" in low:
        kind = "output"
    elif "input" in low:
        kind = "input"
    else:
        return None
    if "image" in low:
        modality = "image"
    elif any(w in low for w in ("audio", "video", "speech")):
        modality = "other"
    else:
        modality = "text"
    if "regional" in low:
        scope = "regional"
    elif "global" in low:
        scope = "global"
    else:
        scope = "api"
    return {"kind": kind, "modality": modality, "scope": scope}


def _cal_pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den > 0 else None


def compute_calibration_from_rows(
    service_rows: list[dict],
    token_rows: list[dict],
    min_service_list_cost: float = 0.05,
    min_regional_list_cost: float = 1.0,
) -> dict:
    """
    Pure deterministic math shared by BigQuery export rows and CSV invoice rows.
    - `service_rows`: [{'service': 'Vertex AI'|'Gemini API', 'list': float, 'savings': float}]
      where `savings >= 0` is total effective discount amount `(list_cost - net_cost)`.
    - `token_rows`: classified Gemini token SKU rows with `service`, `model`, `kind`, `modality`,
      `scope`, `qty` (tokens), `list`, `savings`.
    """
    per_service: dict[str, list[float]] = {}
    for r in service_rows:
        lst = float(r.get("list") or 0.0)
        sav = float(r.get("savings") or 0.0)
        svc = str(r.get("service") or "")
        if lst <= 0 or svc not in ("Vertex AI", "Gemini API"):
            continue
        acc = per_service.setdefault(svc, [0.0, 0.0])
        acc[0] += lst
        acc[1] += sav

    disc_service = {
        svc: _cal_pct(vals[1], vals[0])
        for svc, vals in per_service.items()
        if vals[0] >= min_service_list_cost
    }

    cache_agg: dict[str, dict[str, float]] = {}
    for r in token_rows:
        if r.get("kind") not in ("input", "cache"):
            continue
        key = f"{r['service']}|{r['model']}"
        a = cache_agg.setdefault(key, {"cached": 0.0, "uncached": 0.0, "list": 0.0})
        qty = max(0.0, float(r.get("qty") or 0.0))
        if r["kind"] == "cache":
            a["cached"] += qty
        else:
            a["uncached"] += qty
        a["list"] += max(0.0, float(r.get("list") or 0.0))

    cache_by_model: dict[str, dict] = {}
    for key, a in cache_agg.items():
        tot = a["cached"] + a["uncached"]
        if tot > 0 and a["list"] >= min_service_list_cost:
            cache_by_model[key] = {
                "cachePct": _cal_pct(a["cached"], tot),
                "cachedTokens": int(round(a["cached"])),
                "inputTokens": int(round(tot)),
            }

    def _weighted_cache(svc_name: str) -> float | None:
        c_sum = sum(v["cachedTokens"] for k, v in cache_by_model.items() if k.startswith(svc_name + "|"))
        t_sum = sum(v["inputTokens"] for k, v in cache_by_model.items() if k.startswith(svc_name + "|"))
        return _cal_pct(c_sum, t_sum)

    reg_sums: dict[tuple[str, str], dict[str, list[float]]] = {}
    for r in token_rows:
        if r.get("service") != "Vertex AI" or r.get("modality") != "text" or r.get("kind") == "cache":
            continue
        qty = float(r.get("qty") or 0.0)
        lst = float(r.get("list") or 0.0)
        sc = r.get("scope")
        if qty <= 0 or sc not in ("regional", "global"):
            continue
        bucket = reg_sums.setdefault((r["model"], r["kind"]), {}).setdefault(sc, [0.0, 0.0])
        bucket[0] += lst
        bucket[1] += qty

    reg_units = {
        k: {sc: v[0] / v[1] for sc, v in d.items() if v[1] > 0 and v[0] >= min_regional_list_cost}
        for k, d in reg_sums.items()
    }
    reg_ratios = [v["regional"] / v["global"] for v in reg_units.values() if v.get("regional") and v.get("global")]
    reg_mult = round(statistics.median(reg_ratios), 2) if reg_ratios else None

    derived_bs: dict[str, float] = {}
    notes: list[str] = []

    if disc_service.get("Vertex AI") is not None:
        raw_vd = disc_service["Vertex AI"]
        if raw_vd < -0.5:
            notes.append("Vertex AI net spend exceeded list cost; credit discount clamped to 0%.")
        derived_bs["vertexBillingCreditDiscountPct"] = max(0.0, min(95.0, round(raw_vd, 1)))

    if disc_service.get("Gemini API") is not None:
        raw_gd = disc_service["Gemini API"]
        if raw_gd < -0.5:
            notes.append("Gemini API net spend exceeded list cost; credit discount clamped to 0%.")
        derived_bs["geminiApiBillingCreditDiscountPct"] = max(0.0, min(95.0, round(raw_gd, 1)))

    v_cache = _weighted_cache("Vertex AI")
    if v_cache is not None:
        derived_bs["vertexImplicitCacheHitRatioPct"] = max(0.0, min(98.0, round(v_cache, 1)))

    g_cache = _weighted_cache("Gemini API")
    if g_cache is not None:
        derived_bs["geminiApiImplicitCacheHitRatioPct"] = max(0.0, min(98.0, round(g_cache, 1)))

    if reg_mult is not None:
        derived_bs["regionalMultiplierDefault"] = max(1.0, min(3.0, reg_mult))

    per_model_gemini_cache = {
        key.split("|", 1)[1]: max(0.0, min(98.0, round(v["cachePct"], 1)))
        for key, v in cache_by_model.items()
        if key.startswith("Gemini API|") and v.get("cachePct") is not None
    }

    return {
        "billingSettings": derived_bs,
        "geminiApiCacheHitRatioByModelPct": per_model_gemini_cache,
        "notes": notes,
        "serviceListTotals": {k: round(v[0], 2) for k, v in per_service.items()},
    }


def apply_calibration_to_pricing_config(
    cfg: dict,
    computed: dict,
    source: str,
    now_iso: str,
) -> int:
    """
    Applies computed `billingSettings` and per-model `geminiApiCacheHitRatioPct` into `cfg` in-place
    and refreshes regional fallback rates on models without a dedicated regional SKU or manual override.
    Returns count of models updated with per-model Gemini API cache hit ratios.
    """
    bs_target = cfg.setdefault("billingSettings", dict(DEFAULT_BILLING_SETTINGS))
    for k, v in (computed.get("billingSettings") or {}).items():
        if k in _BILLING_SETTINGS_LIMITS:
            min_v, max_v = _BILLING_SETTINGS_LIMITS[k]
            bs_target[k] = round(max(min_v, min(max_v, float(v))), 4)

    reg_mult = float(bs_target.get("regionalMultiplierDefault", 1.10) or 1.10)
    models_map = cfg.setdefault("models", {})
    per_model_gem = computed.get("geminiApiCacheHitRatioByModelPct") or {}
    applied_models_cnt = 0

    for m_id, pct_val in per_model_gem.items():
        if m_id in models_map and isinstance(models_map[m_id], dict):
            models_map[m_id]["geminiApiCacheHitRatioPct"] = round(max(0.0, min(98.0, float(pct_val))), 2)
            models_map[m_id]["updatedAt"] = now_iso
            applied_models_cnt += 1

    for _m_id, m_entry in models_map.items():
        if not isinstance(m_entry, dict):
            continue
        mo_dict = m_entry.get("manualOverride") if isinstance(m_entry.get("manualOverride"), dict) else {}
        for base_f, reg_f in (
            ("input", "regional_input"),
            ("output", "regional_output"),
            ("thinking", "regional_thinking"),
            ("cache_read_input", "regional_cache_read_input"),
        ):
            if reg_f not in mo_dict and not m_entry.get("lastSkuIdRegional"):
                m_entry[reg_f] = round(float(m_entry.get(base_f, 0.0) or 0.0) * reg_mult, 4)

    cal = normalize_billing_calibration_block(cfg.get("billingCalibration"), bs_target)
    cal["activeSource"] = source
    cal["manualOverride"] = False
    cal["calibratedAt"] = now_iso
    cal["derivedSettings"] = dict(computed.get("billingSettings") or {})
    cal["perModelGeminiCacheCount"] = applied_models_cnt
    cfg["billingCalibration"] = cal
    return applied_models_cnt


# =========================================================================
# PATH 2: IN-MEMORY CLOUD BILLING CSV PARSER (ITALIAN & ENGLISH LOCALES)
# =========================================================================

def _csv_pick_col(row: dict, candidates: tuple[str, ...]) -> str:
    for k, v in row.items():
        if k is None:
            continue
        clean_k = k.strip().lstrip("\ufeff").lower()
        if clean_k in candidates:
            return "" if v is None else str(v).strip()
    return ""


def _detect_csv_number_locale(raw_rows: list[dict]) -> str:
    """Returns 'comma' for European/Italian numbers (1.850,70) or 'dot' for US/English numbers (1,850.70)."""
    comma_dec_hits = 0
    dot_dec_hits = 0
    num_cols = _CSV_COL_QTY + _CSV_COL_LIST + _CSV_COL_NEGOTIATED + _CSV_COL_OTHER + _CSV_COL_SUBTOTAL
    for r in raw_rows[:250]:
        for col_tuple in (num_cols,):
            for k, val in r.items():
                if not k or not val:
                    continue
                if k.strip().lstrip("\ufeff").lower() not in col_tuple:
                    continue
                s = re.sub(r"[€$£\s\u00a0]", "", str(val).strip())
                if not s or s in ("-", "—"):
                    continue
                if "," in s and "." in s:
                    if s.rfind(",") > s.rfind("."):
                        comma_dec_hits += 2
                    else:
                        dot_dec_hits += 2
                elif re.search(r",\d{1,2}$", s) or re.search(r",\d{4,}$", s):
                    comma_dec_hits += 1
                elif re.search(r"\.\d{1,2}$", s) or re.search(r"\.\d{4,}$", s):
                    dot_dec_hits += 1
    return "comma" if comma_dec_hits > dot_dec_hits else "dot"


def _parse_csv_num(val: str, locale_mode: str) -> float:
    s = re.sub(r"[€$£\s\u00a0]", "", str(val or "").strip())
    if not s or s in ("-", "—"):
        return 0.0
    if locale_mode == "comma":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        num = float(s)
        return num if math.isfinite(num) else 0.0
    except ValueError:
        return 0.0


def calibrate_from_csv_uploads(files_payload: list[dict]) -> tuple[bool, str | None, dict | None]:
    """
    Parses 1..12 Cloud Billing CSV report files in memory, computes billing calibration indices,
    updates `models_pricing_config.json`, and returns `(ok, error_msg, cfg)`.
    """
    if not isinstance(files_payload, list) or len(files_payload) == 0:
        return False, "No CSV file provided.", None
    if len(files_payload) > 12:
        return False, "Too many CSV files (maximum 12 files per upload).", None

    total_chars = 0
    service_rows: list[dict] = []
    token_rows: list[dict] = []
    file_names: list[str] = []
    notes: list[str] = []

    for idx, item in enumerate(files_payload):
        if not isinstance(item, dict):
            return False, f"Invalid file entry at position {idx + 1}.", None
        fname = os.path.basename(str(item.get("name") or f"report_{idx + 1}.csv").strip())[:120] or f"report_{idx + 1}.csv"
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            return False, f"File '{fname}' is empty.", None
        total_chars += len(content)
        if total_chars > 15_000_000:
            return False, "Total CSV upload size exceeds the 15 MB safety limit.", None

        text = content.lstrip("\ufeff")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if (first_line.count(";") > first_line.count(",")) else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        raw_rows = [r for r in reader if isinstance(r, dict)]
        if not raw_rows:
            continue

        # Validate that required SKU & list cost columns exist
        sample = raw_rows[0]
        header_lows = {str(k or "").strip().lstrip("\ufeff").lower() for k in sample.keys()}
        has_svc = bool(header_lows & set(_CSV_COL_SERVICE)) or bool(header_lows & set(_CSV_COL_SERVICE_ID))
        has_sku = bool(header_lows & set(_CSV_COL_SKU))
        has_list = bool(header_lows & set(_CSV_COL_LIST))
        if not (has_svc and has_sku and has_list):
            return (
                False,
                f"File '{fname}' is missing required Cloud Billing SKU columns (Service description, SKU description, Cost at list).",
                None,
            )

        locale_mode = _detect_csv_number_locale(raw_rows)
        has_sav_cols = bool(header_lows & (set(_CSV_COL_NEGOTIATED) | set(_CSV_COL_OTHER)))
        has_sub_col = bool(header_lows & set(_CSV_COL_SUBTOTAL))
        file_names.append(fname)

        for raw in raw_rows:
            svc_raw = _csv_pick_col(raw, _CSV_COL_SERVICE)
            svc_id_raw = _csv_pick_col(raw, _CSV_COL_SERVICE_ID)
            svc = _CAL_SERVICE_MAP.get(svc_id_raw) or _CAL_SERVICE_MAP.get(svc_raw.lower())
            if not svc:
                continue
            sku_desc = _csv_pick_col(raw, _CSV_COL_SKU)
            if not sku_desc:
                continue

            list_cost = _parse_csv_num(_csv_pick_col(raw, _CSV_COL_LIST), locale_mode)
            qty = _parse_csv_num(_csv_pick_col(raw, _CSV_COL_QTY), locale_mode)
            if has_sav_cols:
                neg = _parse_csv_num(_csv_pick_col(raw, _CSV_COL_NEGOTIATED), locale_mode)
                oth = _parse_csv_num(_csv_pick_col(raw, _CSV_COL_OTHER), locale_mode)
                savings = -(neg + oth)
            elif has_sub_col:
                sub = _parse_csv_num(_csv_pick_col(raw, _CSV_COL_SUBTOTAL), locale_mode)
                savings = list_cost - sub
            else:
                savings = 0.0

            if list_cost > 0:
                service_rows.append({"service": svc, "list": list_cost, "savings": savings})

            sku_info = _cal_classify_sku(sku_desc)
            model_lbl = _cal_model_label_from_sku(sku_desc) if sku_info else None
            if sku_info and model_lbl:
                token_rows.append({
                    "service": svc,
                    "model": model_lbl,
                    "sku": sku_desc,
                    "source": fname,
                    "qty": qty,
                    "list": list_cost,
                    "savings": savings,
                    **sku_info,
                })

    if not service_rows and not token_rows:
        return (
            False,
            "No Vertex AI or Gemini API billing rows found in the uploaded CSV file(s). Export the report from Google Cloud Billing > Reports grouped by SKU.",
            None,
        )

    computed = compute_calibration_from_rows(service_rows, token_rows)
    if not computed.get("billingSettings") and not computed.get("geminiApiCacheHitRatioByModelPct"):
        return (
            False,
            "Vertex AI / Gemini API spend in the uploaded CSV is too small to derive calibration ratios.",
            None,
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    cfg = load_models_pricing_config()
    apply_calibration_to_pricing_config(cfg, computed, source="CSV_UPLOAD", now_iso=now_iso)
    cal = cfg["billingCalibration"]
    cal["csvFiles"] = file_names
    cal["rowCount"] = len(service_rows)
    cal["notes"] = (notes + computed.get("notes", []))[:10]
    save_models_pricing_config(cfg)
    return True, None, cfg


# =========================================================================
# PATH 1: BIGQUERY CLOUD BILLING EXPORT AUTO-DISCOVERY & CALIBRATION
# =========================================================================

def _extract_gcp_error_info(body: dict) -> tuple[str, str]:
    """Returns (reason, message) from a Google API JSON error payload."""
    if not isinstance(body, dict):
        return "", ""
    err = body.get("error")
    if isinstance(err, dict):
        msg = " ".join(str(err.get("message") or "").split())[:220]
        reasons = []
        for item in (err.get("errors") or []):
            if isinstance(item, dict) and item.get("reason"):
                reasons.append(str(item["reason"]))
        for det in (err.get("details") or []):
            if isinstance(det, dict) and det.get("reason"):
                reasons.append(str(det["reason"]))
        reason = reasons[0] if reasons else str(err.get("status") or "")
        return reason, msg
    if err:
        return "", " ".join(str(err).split())[:220]
    return "", ""


def _is_bq_api_disabled_403(body: dict) -> bool:
    reason, msg = _extract_gcp_error_info(body)
    low_m = msg.lower()
    low_r = reason.lower()
    return (
        "accessnotconfigured" in low_r
        or "service_disabled" in low_r
        or "has not been used in project" in low_m
        or "api has not been enabled" in low_m
        or "it is disabled" in low_m
    )


def _is_bq_iam_permission_denied(status: int, body: dict) -> bool:
    if status != 403:
        return False
    if _is_bq_api_disabled_403(body):
        return False
    return True


def _build_bq_calibration_sql(proj: str, ds: str, tbl: str, window_days: int = 30, use_partition_filter: bool = True) -> str:
    days_i = max(1, min(90, int(window_days or 30)))
    part_clause = (
        f"_PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_i + 1} DAY) AND "
        if use_partition_filter else ""
    )
    return (
        "SELECT "
        "service.id AS service_id, "
        "service.description AS service_desc, "
        "sku.id AS sku_id, "
        "sku.description AS sku_desc, "
        "ANY_VALUE(currency) AS currency, "
        "SUM(IFNULL(usage.amount, 0.0)) AS usage_amount, "
        "SUM(IFNULL(cost_at_list, cost)) AS list_cost, "
        "SUM(IFNULL(cost, 0.0)) AS gross_cost, "
        "SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c), 0.0)) AS credits_sum "
        f"FROM `{proj}.{ds}.{tbl}` "
        f"WHERE {part_clause}"
        f"usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_i} DAY) "
        "AND service.id IN ('C7E2-9256-1C43', 'AEFD-7695-64FA') "
        "GROUP BY service_id, service_desc, sku_id, sku_desc"
    )


def _parse_bq_query_rows(resp_body: dict) -> list[dict]:
    schema_fields = ((resp_body.get("schema") or {}).get("fields")) or []
    col_names = [str(f.get("name") or f"col_{i}") for i, f in enumerate(schema_fields)]
    out: list[dict] = []
    for raw_r in (resp_body.get("rows") or []):
        cells = raw_r.get("f") if isinstance(raw_r, dict) else None
        if not isinstance(cells, list):
            continue
        rec = {}
        for idx, col in enumerate(col_names):
            val = cells[idx].get("v") if idx < len(cells) and isinstance(cells[idx], dict) else None
            rec[col] = val
        out.append(rec)
    return out


def _query_bigquery_billing_table(
    proj: str,
    ds: str,
    tbl: str,
    token: str,
    quota_candidates: list[str] | None = None,
    window_days: int = 30,
) -> dict:
    """
    Executes a single read-only SELECT aggregation on `proj.ds.tbl`.
    Tries `proj` first as the BigQuery job project; if job creation is denied (`bigquery.jobs.create`),
    falls back to `quota_candidates` so users with `roles/bigquery.dataViewer` on a central billing
    dataset and `roles/bigquery.jobUser` on an operational project succeed seamlessly.
    """
    job_projects = list(dict.fromkeys([proj] + [str(p).strip() for p in (quota_candidates or []) if p and str(p).strip()]))[:5]
    last_status = 0
    last_msg = ""
    denied_targets: list[str] = []

    for job_proj in job_projects:
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(job_proj)}/queries"
        for use_part in (True, False):
            sql = _build_bq_calibration_sql(proj, ds, tbl, window_days=window_days, use_partition_filter=use_part)
            payload = {
                "query": sql,
                "useLegacySql": False,
                "timeoutMs": 20000,
                "maxResults": 2000,
            }
            st_code, body = gcp_api_post(url, token, payload, timeout=22)
            reason, msg = _extract_gcp_error_info(body)
            last_status, last_msg = st_code, msg

            if st_code == 400 and use_part and "_partitiontime" in msg.lower():
                continue  # custom view/table without _PARTITIONTIME: retry immediately with usage_start_time alone

            if st_code == 200 and isinstance(body, dict):
                if not body.get("jobComplete", True):
                    job_ref = body.get("jobReference") or {}
                    job_id = job_ref.get("jobId")
                    loc = job_ref.get("location")
                    if job_id:
                        poll_url = (
                            f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(job_proj)}"
                            f"/queries/{urllib.parse.quote(str(job_id))}?timeoutMs=10000&maxResults=2000"
                        )
                        if loc:
                            poll_url += f"&location={urllib.parse.quote(str(loc))}"
                        st_poll, body_poll = gcp_api_get(poll_url, token, timeout=14)
                        if st_poll == 200 and isinstance(body_poll, dict) and body_poll.get("jobComplete"):
                            body = body_poll
                        else:
                            return {
                                "status": "ERROR",
                                "table": f"{proj}.{ds}.{tbl}",
                                "jobProject": job_proj,
                                "message": "BigQuery calibration query did not complete within the timeout window.",
                                "deniedTargets": [],
                            }
                return {
                    "status": "OK",
                    "table": f"{proj}.{ds}.{tbl}",
                    "jobProject": job_proj,
                    "rows": _parse_bq_query_rows(body),
                    "deniedTargets": [],
                }

            if st_code == 404 or "notfound" in reason.lower() or "not found" in msg.lower():
                return {
                    "status": "NOT_FOUND",
                    "table": f"{proj}.{ds}.{tbl}",
                    "jobProject": job_proj,
                    "message": f"BigQuery table {proj}.{ds}.{tbl} was not found.",
                    "deniedTargets": [],
                }

            if _is_bq_iam_permission_denied(st_code, body):
                low_m = msg.lower()
                # If table/dataset itself is denied, changing job_project will not grant table data access,
                # except when the error is specifically about jobs.create on job_proj.
                if "jobs.create" in low_m or f"project {job_proj}" in low_m:
                    denied_targets.append(f"{job_proj} (bigquery.jobs.create)")
                    break  # try next job_project in quota_candidates
                denied_targets.append(f"{proj}.{ds}.{tbl}")
                return {
                    "status": "PERMISSION_DENIED",
                    "table": f"{proj}.{ds}.{tbl}",
                    "jobProject": job_proj,
                    "message": (
                        f"Access denied (HTTP 403) reading BigQuery Billing Export {proj}.{ds}.{tbl}. "
                        "Grant roles/bigquery.dataViewer on the billing export dataset and roles/bigquery.jobUser on an accessible GCP project."
                    ),
                    "detail": msg,
                    "deniedTargets": list(dict.fromkeys(denied_targets)),
                }

            if _is_bq_api_disabled_403(body):
                break  # BigQuery API disabled on this job_proj; try next candidate project

            break

    if denied_targets:
        return {
            "status": "PERMISSION_DENIED",
            "table": f"{proj}.{ds}.{tbl}",
            "jobProject": job_projects[0] if job_projects else proj,
            "message": (
                f"Access denied (HTTP 403) running BigQuery query for {proj}.{ds}.{tbl}. "
                "Grant roles/bigquery.dataViewer on the billing export dataset and roles/bigquery.jobUser on at least one GCP project."
            ),
            "detail": last_msg,
            "deniedTargets": list(dict.fromkeys(denied_targets)),
        }

    return {
        "status": "ERROR" if last_status not in (404,) else "NOT_FOUND",
        "table": f"{proj}.{ds}.{tbl}",
        "jobProject": job_projects[0] if job_projects else proj,
        "message": last_msg or f"BigQuery check returned HTTP {last_status}.",
        "deniedTargets": [],
    }


def _rank_project_for_billing_discovery(p_meta: dict) -> tuple[int, str]:
    pid = str(p_meta.get("projectId") or "").strip().lower()
    pname = str(p_meta.get("name") or "").strip().lower()
    combined = f"{pid} {pname}"
    for idx, kw in enumerate(_BQ_PRIORITY_PROJECT_HINTS):
        if kw in combined:
            return (idx, pid)
    return (99, pid)


def _discover_bigquery_billing_tables(
    token: str,
    candidate_projects: list[dict],
) -> tuple[list[tuple[str, str, str]], list[str], list[str]]:
    """
    Scans accessible projects for BigQuery datasets/tables matching `gcp_billing_export_v1_*`
    or `gcp_billing_export_resource_v1_*`.
    Returns `(found_tables, denied_targets, empty_billing_datasets)`.
    """
    ranked = sorted(
        [p for p in (candidate_projects or []) if isinstance(p, dict) and _BQ_PROJECT_ID_RE.match(str(p.get("projectId") or ""))],
        key=_rank_project_for_billing_discovery,
    )[:40]

    found_tables: list[tuple[int, str, str, str]] = []
    denied_targets: list[str] = []
    empty_billing_datasets: list[str] = []

    def _inspect_project(p_meta: dict):
        pid = str(p_meta["projectId"]).strip()
        pname_low = f"{pid} {p_meta.get('name') or ''}".lower()
        is_billing_named_proj = any(k in pname_low for k in ("bill", "finops", "cost", "infra", "org", "admin"))
        ds_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(pid)}/datasets?maxResults=200"
        st_ds, body_ds = gcp_api_get(ds_url, token, timeout=10)
        p_found = []
        p_denied = []
        p_empty = []
        if st_ds != 200:
            if _is_bq_iam_permission_denied(st_ds, body_ds) and is_billing_named_proj:
                p_denied.append(f"{pid} (bigquery.datasets.list)")
            return p_found, p_denied, p_empty

        datasets = body_ds.get("datasets") or []
        matching_ds: list[str] = []
        other_ds: list[str] = []
        for d_obj in datasets:
            d_ref = (d_obj.get("datasetReference") or {}) if isinstance(d_obj, dict) else {}
            did = str(d_ref.get("datasetId") or "").strip()
            if not _BQ_DATASET_ID_RE.match(did):
                continue
            if any(h in did.lower() for h in _BQ_DATASET_HINTS):
                matching_ds.append(did)
            elif is_billing_named_proj and len(datasets) <= 8:
                other_ds.append(did)

        for did in (matching_ds + other_ds)[:10]:
            tbl_url = (
                f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(pid)}"
                f"/datasets/{urllib.parse.quote(did)}/tables?maxResults=200"
            )
            st_t, body_t = gcp_api_get(tbl_url, token, timeout=10)
            if st_t != 200:
                if _is_bq_iam_permission_denied(st_t, body_t):
                    p_denied.append(f"{pid}.{did}")
                continue
            tables = body_t.get("tables") or []
            matched_in_ds = False
            for t_obj in tables:
                t_ref = (t_obj.get("datasetReference") or t_obj.get("tableReference") or {}) if isinstance(t_obj, dict) else {}
                tid = str((t_obj.get("tableReference") or {}).get("tableId") or t_ref.get("tableId") or "").strip()
                if not _BQ_TABLE_ID_RE.match(tid):
                    continue
                tid_low = tid.lower()
                if tid_low.startswith("gcp_billing_export_v1_"):
                    p_found.append((0, pid, did, tid))
                    matched_in_ds = True
                elif tid_low.startswith("gcp_billing_export_resource_v1_"):
                    p_found.append((1, pid, did, tid))
                    matched_in_ds = True
            if not matched_in_ds and did in matching_ds and len(tables) == 0:
                p_empty.append(f"{pid}.{did}")
        return p_found, p_denied, p_empty

    if ranked:
        workers = min(6, max(1, len(ranked)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for pf, pd, pe in pool.map(_inspect_project, ranked):
                found_tables.extend(pf)
                denied_targets.extend(pd)
                empty_billing_datasets.extend(pe)

    found_tables.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    dedup_tables = list(dict.fromkeys((p, d, t) for _prio, p, d, t in found_tables))
    return dedup_tables, list(dict.fromkeys(denied_targets)), list(dict.fromkeys(empty_billing_datasets))


def discover_and_calibrate_bigquery_billing(
    token: str,
    active_acc: str | None = None,
    raw_projects: list[dict] | None = None,
    reg: dict | None = None,
    quota_candidates: list[str] | None = None,
    explicit_table: str | None = None,
    auto_apply: bool = True,
    force_apply: bool = False,
    window_days: int = 30,
) -> dict:
    """
    Discovers (or queries `explicit_table` / configured `billingExportTable`) the BigQuery Cloud Billing Export,
    computes real 30d credit discounts, implicit cache hit ratios, per-model Gemini API cache hit ratios and
    regional multiplier, updates `models_pricing_config.json`, and returns the updated config.
    100% read-only on GCP (GET datasets/tables + read-only SELECT query).
    """
    demo_block_network("BigQuery billing calibration")
    with _BQ_CALIBRATION_LOCK:
        cfg = load_models_pricing_config()
        bs_curr = cfg.setdefault("billingSettings", dict(DEFAULT_BILLING_SETTINGS))
        cal = normalize_billing_calibration_block(cfg.get("billingCalibration"), bs_curr)
        now_iso = datetime.now(timezone.utc).isoformat()

        if explicit_table is not None:
            clean_exp = str(explicit_table).strip()
            if clean_exp:
                parsed_exp = parse_bigquery_table_ref(clean_exp)
                if not parsed_exp:
                    return {
                        "success": False,
                        "error": "Invalid BigQuery table reference. Expected format: project_id.dataset_id.table_id",
                        "config": cfg,
                    }
                cal["billingExportTable"] = f"{parsed_exp[0]}.{parsed_exp[1]}.{parsed_exp[2]}"
            else:
                cal["billingExportTable"] = ""

        if not quota_candidates and active_acc and "get_quota_project_candidates" in globals():
            with contextlib.suppress(Exception):
                quota_candidates = get_quota_project_candidates(active_acc, reg=reg, raw_projects=raw_projects, limit=5)

        # Build candidate tables to try first (configured override -> previously discovered table)
        direct_candidates: list[tuple[str, str, str, bool]] = []
        if cal.get("billingExportTable"):
            p_ref = parse_bigquery_table_ref(cal["billingExportTable"])
            if p_ref:
                direct_candidates.append((*p_ref, True))
        if cal.get("discoveredTable"):
            p_disc = parse_bigquery_table_ref(cal["discoveredTable"])
            if p_disc and (*p_disc, True) not in direct_candidates and (*p_disc, False) not in direct_candidates:
                direct_candidates.append((*p_disc, False))

        query_outcome = None
        all_denied: list[str] = []

        for proj, ds, tbl, is_explicit_cfg in direct_candidates:
            q_res = _query_bigquery_billing_table(
                proj, ds, tbl, token, quota_candidates=quota_candidates, window_days=window_days
            )
            if q_res["status"] == "OK":
                query_outcome = q_res
                break
            if q_res["status"] == "PERMISSION_DENIED":
                all_denied.extend(q_res.get("deniedTargets") or [f"{proj}.{ds}.{tbl}"])
                if is_explicit_cfg:
                    query_outcome = q_res
                    break
            elif is_explicit_cfg and q_res["status"] in ("NOT_FOUND", "ERROR"):
                query_outcome = q_res
                break

        empty_billing_ds: list[str] = []
        if query_outcome is None:
            # Auto-discover across accessible GCP projects
            proj_list: list[dict] = []
            if raw_projects:
                proj_list = list(raw_projects)
            else:
                if active_acc and "ensure_account_sync_registry" in globals():
                    with contextlib.suppress(Exception):
                        reg_obj = reg or ensure_account_sync_registry(active_acc)
                        acc_p = ((reg_obj or {}).get("accounts") or {}).get(active_acc, {}).get("projects") or {}
                        proj_list = [{"projectId": pid, "name": (m or {}).get("name") or pid} for pid, m in acc_p.items() if pid]
                if not proj_list and "list_all_accessible_projects" in globals():
                    with contextlib.suppress(Exception):
                        proj_list = list_all_accessible_projects(token) or []

            if not quota_candidates and proj_list and "get_quota_project_candidates" in globals():
                with contextlib.suppress(Exception):
                    quota_candidates = get_quota_project_candidates(active_acc, reg=reg, raw_projects=proj_list, limit=5)

            found_tables, disc_denied, empty_billing_ds = _discover_bigquery_billing_tables(token, proj_list)
            all_denied.extend(disc_denied)

            for proj, ds, tbl in found_tables[:4]:
                if any((proj, ds, tbl) == (c[0], c[1], c[2]) for c in direct_candidates):
                    continue
                q_res = _query_bigquery_billing_table(
                    proj, ds, tbl, token, quota_candidates=quota_candidates, window_days=window_days
                )
                if q_res["status"] == "OK":
                    query_outcome = q_res
                    break
                if q_res["status"] == "PERMISSION_DENIED":
                    all_denied.extend(q_res.get("deniedTargets") or [f"{proj}.{ds}.{tbl}"])
                    if query_outcome is None:
                        query_outcome = q_res

        all_denied = list(dict.fromkeys(all_denied))[:8]
        # Reload latest config after network I/O so concurrent model edits are never overwritten
        explicit_override_saved = cal.get("billingExportTable", "")
        cfg = load_models_pricing_config()
        bs_curr = cfg.setdefault("billingSettings", dict(DEFAULT_BILLING_SETTINGS))
        cal = normalize_billing_calibration_block(cfg.get("billingCalibration"), bs_curr)
        if explicit_table is not None:
            cal["billingExportTable"] = explicit_override_saved
        cal["bigqueryCheckedAt"] = now_iso
        cal["windowDays"] = int(window_days or 30)

        if active_acc:
            _BQ_CHECKED_DATE_BY_ACCOUNT[active_acc] = get_today_date_str()

        if query_outcome and query_outcome["status"] == "OK":
            bq_rows = query_outcome.get("rows") or []
            service_rows: list[dict] = []
            token_rows: list[dict] = []
            for r in bq_rows:
                svc_id = str(r.get("service_id") or "").strip()
                svc_desc = str(r.get("service_desc") or "").strip()
                svc = _CAL_SERVICE_MAP.get(svc_id) or _CAL_SERVICE_MAP.get(svc_desc.lower())
                if not svc:
                    continue
                sku_desc = str(r.get("sku_desc") or "").strip()
                try:
                    qty = float(r.get("usage_amount") or 0.0)
                    list_cost = float(r.get("list_cost") or 0.0)
                    gross_cost = float(r.get("gross_cost") or 0.0)
                    credits_sum = float(r.get("credits_sum") or 0.0)
                except (TypeError, ValueError):
                    continue
                net_cost = gross_cost + credits_sum
                savings = list_cost - net_cost
                if list_cost > 0:
                    service_rows.append({"service": svc, "list": list_cost, "savings": savings})
                sku_info = _cal_classify_sku(sku_desc)
                model_lbl = _cal_model_label_from_sku(sku_desc) if sku_info else None
                if sku_info and model_lbl:
                    token_rows.append({
                        "service": svc,
                        "model": model_lbl,
                        "sku": sku_desc,
                        "source": query_outcome["table"],
                        "qty": qty,
                        "list": list_cost,
                        "savings": savings,
                        **sku_info,
                    })

            computed = compute_calibration_from_rows(service_rows, token_rows)
            cal["bigqueryStatus"] = "OK"
            cal["discoveredTable"] = query_outcome["table"]
            cal["jobProject"] = query_outcome.get("jobProject") or ""
            cal["deniedTargets"] = []
            cal["rowCount"] = len(bq_rows)
            cal["derivedSettings"] = dict(computed.get("billingSettings") or {})
            cal["notes"] = list(computed.get("notes") or [])

            should_apply = bool(force_apply or (auto_apply and not cal.get("manualOverride")))
            has_derived = bool(computed.get("billingSettings") or computed.get("geminiApiCacheHitRatioByModelPct"))
            actually_applied = False
            if should_apply and has_derived:
                cfg["billingCalibration"] = cal
                apply_calibration_to_pricing_config(cfg, computed, source="BIGQUERY_EXPORT", now_iso=now_iso)
                cal = cfg["billingCalibration"]
                cal["bigqueryMessage"] = (
                    f"Connected to BigQuery Billing Export ({query_outcome['table']}). "
                    f"Billing discounts and cache ratios are automatically calibrated over the last {cal['windowDays']} days."
                )
                actually_applied = True
            elif should_apply:
                if cal.get("activeSource") == "DEFAULT_LIST_PRICES":
                    cal["activeSource"] = "BIGQUERY_EXPORT"
                    cal["manualOverride"] = False
                    cal["calibratedAt"] = now_iso
                    cal["bigqueryMessage"] = (
                        f"Connected to BigQuery Billing Export ({query_outcome['table']}), "
                        f"with zero Vertex AI / Gemini API billed rows in the last {cal['windowDays']} days (neutral 0% discounts active)."
                    )
                else:
                    cal["bigqueryMessage"] = (
                        f"Connected to BigQuery Billing Export ({query_outcome['table']}), "
                        f"with zero Vertex AI / Gemini API billed rows in the last {cal['windowDays']} days; keeping current cost parameters until billing rows arrive."
                    )
                cfg["billingCalibration"] = cal
            else:
                cal["bigqueryMessage"] = (
                    f"BigQuery Billing Export ({query_outcome['table']}) is readable, "
                    "while manual billing settings are kept active (click 'Detect & Calibrate from BigQuery' to apply BigQuery values)."
                )
                cfg["billingCalibration"] = cal

            save_models_pricing_config(cfg)
            return {"success": True, "bigqueryStatus": "OK", "applied": actually_applied, "config": cfg}

        if (query_outcome and query_outcome["status"] == "PERMISSION_DENIED") or all_denied:
            cal["bigqueryStatus"] = "PERMISSION_DENIED"
            cal["deniedTargets"] = all_denied
            target_lbl = (query_outcome or {}).get("table") or (all_denied[0] if all_denied else "billing export dataset")
            cal["bigqueryMessage"] = (query_outcome or {}).get("message") or (
                f"Missing IAM permission (HTTP 403) to read BigQuery Billing Export on {target_lbl}. "
                "Grant roles/bigquery.dataViewer on the billing export dataset and roles/bigquery.jobUser on an accessible GCP project."
            )
            cfg["billingCalibration"] = cal
            save_models_pricing_config(cfg)
            return {"success": True, "bigqueryStatus": "PERMISSION_DENIED", "applied": False, "config": cfg}

        if query_outcome and query_outcome["status"] == "ERROR":
            cal["bigqueryStatus"] = "ERROR"
            cal["bigqueryMessage"] = query_outcome.get("message") or "Temporary error while querying BigQuery Billing Export."
            cfg["billingCalibration"] = cal
            save_models_pricing_config(cfg)
            return {"success": True, "bigqueryStatus": "ERROR", "applied": False, "config": cfg}

        # NOT_FOUND
        cal["bigqueryStatus"] = "NOT_FOUND"
        cal["deniedTargets"] = []
        if empty_billing_ds:
            cal["bigqueryMessage"] = (
                f"No gcp_billing_export_v1_* table found (dataset {empty_billing_ds[0]} is empty). "
                "Enable Cloud Billing Export to BigQuery in Google Cloud Console, specify an existing project.dataset.table below, or upload a Billing CSV report."
            )
        else:
            cal["bigqueryMessage"] = (
                "No BigQuery Cloud Billing Export table (gcp_billing_export_v1_*) was found in your accessible projects. "
                "Enable Standard Usage Cost Export in Google Cloud Billing > Billing export, enter project.dataset.table if hosted in another project, or upload a Billing CSV report."
            )
        cfg["billingCalibration"] = cal
        save_models_pricing_config(cfg)
        return {"success": True, "bigqueryStatus": "NOT_FOUND", "applied": False, "config": cfg}


def maybe_auto_calibrate_bigquery_for_account(
    token: str,
    active_acc: str | None,
    raw_projects: list[dict] | None = None,
    reg: dict | None = None,
    quota_candidates: list[str] | None = None,
    force_check: bool = False,
) -> dict | None:
    """
    Runs BigQuery discovery/calibration at most once per calendar day per active Google account
    (unless `force_check=True`), never blocking scans on unexpected exceptions.
    """
    if is_demo_mode() or not token:
        return None
    # Opt-in: BigQuery query jobs can be billed, so scans never run them unless the user enabled it
    if not normalize_billing_calibration_block(load_models_pricing_config().get("billingCalibration")).get("bigqueryAutoSync"):
        return None
    today = get_today_date_str()
    if not force_check and active_acc and _BQ_CHECKED_DATE_BY_ACCOUNT.get(active_acc) == today:
        cfg_existing = load_models_pricing_config()
        cal_existing = (cfg_existing.get("billingCalibration") or {}).get("bigqueryStatus")
        if cal_existing and cal_existing != "NOT_CHECKED":
            return cfg_existing
    with contextlib.suppress(Exception):
        res = discover_and_calibrate_bigquery_billing(
            token=token,
            active_acc=active_acc,
            raw_projects=raw_projects,
            reg=reg,
            quota_candidates=quota_candidates,
            auto_apply=True,
            force_apply=False,
        )
        if isinstance(res, dict):
            return res.get("config")
    return None
