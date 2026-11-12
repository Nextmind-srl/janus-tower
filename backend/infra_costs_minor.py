"""Fixed-cost estimates for the smaller supporting services: Artifact Registry, Secret Manager, BigQuery, Cloud Storage,
and Cloud Run. Cloud Monitoring, Logging and Trace are NOT estimated: their cost depends on ingestion volumes with
a free allowance shared by the whole billing account, so a guess would be worse than no line.

Same rules as infra_costs.py: volumes come from the project's own APIs / Cloud Monitoring, prices from the public Cloud
Billing Catalog (list price, USD), the local `infraSavingsPct` models the user's discounts. Free tiers are NOT applied
(they are shared at billing-account level and cannot be seen from one project), so these lines are an upper bound.
A service with no resources or no usage produces no line at all. When no reliable volume exists the line says so.
"""

import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

MINOR_CATALOG_SERVICE_IDS = {
    "artifactregistry": "149C-F9EC-3994",
    "secretmanager": "EE82-7A5E-871C",
    "bigquery": "24E6-581D-38E5",
    "storage": "95FF-2EF5-5EA1",
    "run": "152E-C115-5142",
}
_GIB = 2.0 ** 30
_TIB = 2.0 ** 40


def _minor_default_mon_fetch(pid: str, token: str, days: int, now: datetime | None):
    now = now or datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_iso = datetime.fromtimestamp(now.timestamp() - max(1, days) * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fetch(metric_type: str, group_by: list, aligner: str):
        return fetch_monitoring_timeseries(pid, token, f'metric.type="{metric_type}"', start_iso, end_iso, group_by, aligner)
    return fetch


def _series_values(ts: dict) -> list:
    out = []
    for pt in ts.get("points") or []:
        val = pt.get("value") or {}
        v = val.get("int64Value", val.get("doubleValue"))
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _series_mean(ts: dict) -> float:
    """Average of the available points: a storage volume is billed for the time it is held, so a short peak must not
    be charged for the whole month."""
    vals = _series_values(ts)
    return sum(vals) / len(vals) if vals else 0.0


def _series_label(ts: dict, kind: str, name: str) -> str:
    return str(((ts.get(kind) or {}).get("labels") or {}).get(name, ""))


def _minor_line(service: str, key: str, name: str, subtitle: str, icon: str, *, items: list, locations: list,
                gross: float, days: int, status: str, note: str = "") -> dict:
    return _infra_line(service, MINOR_CATALOG_SERVICE_IDS[key], name, subtitle, icon, instances=items,
                       locations=sorted(x for x in set(locations) if x), gross=gross, days=days, status=status, note=note)


def _status(total: float, skipped: list) -> str:
    return "ok" if not skipped else ("partial" if total > 0 else "not_estimable")


# ----------------------------------------------------------------------------- Artifact Registry

_AR_LOCATIONS_TTL = 24 * 3600.0
_ar_locations_lock = threading.Lock()
_ar_locations_cache: dict = {"at": 0.0, "ids": None}


def _artifactregistry_location_ids(base: str, fetch) -> tuple[int, list]:
    """Location ids are practically the same for every project: kept in a process cache (24h TTL, only successful
    reads are cached) so the /locations call happens once."""
    with _ar_locations_lock:
        ids = _ar_locations_cache["ids"]
        if ids is not None and time.time() - _ar_locations_cache["at"] < _AR_LOCATIONS_TTL:
            return 200, list(ids)
        status, body = fetch(f"{base}?pageSize=200")
        if status != 200 or not isinstance(body, dict):
            return status, []
        ids = [str(x.get("locationId", "")) for x in (body.get("locations") or []) if isinstance(x, dict)]
        ids = [x for x in ids if x][:80]
        if ids:
            _ar_locations_cache["ids"], _ar_locations_cache["at"] = list(ids), time.time()
        return 200, ids


def _artifactregistry_repositories(pid: str, fetch) -> tuple[int, list]:
    """All repositories of a project. The API has no all-locations wildcard (`locations/-` answers HTTP 400), so the
    locations are listed first (cached) and each one is read in parallel. (status, repositories); status != 200 only
    when nothing could be read at all."""
    base = f"https://artifactregistry.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations"
    status, loc_ids = _artifactregistry_location_ids(base, fetch)
    if status != 200:
        return status, []

    def one(loc_id: str):
        st, rb = fetch(f"{base}/{urllib.parse.quote(loc_id)}/repositories?pageSize=200")
        return st, (rb.get("repositories") if st == 200 and isinstance(rb, dict) else None) or []

    repos, statuses = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for st, items in pool.map(one, loc_ids):
            statuses.append(st)
            repos.extend(r for r in items if isinstance(r, dict))
    if statuses and all(st != 200 for st in statuses):
        return statuses[0], []
    return 200, repos


def build_artifactregistry_line(pid, token, days, skus, fetch=None, now=None, mon_fetch=None):
    meta = ("artifactregistry.googleapis.com", "artifactregistry", "Artifact Registry", "Repository storage", "📦")
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=20, user_project=pid))
    status, repositories = _artifactregistry_repositories(pid, fetch)
    if status != 200:
        return _infra_unavailable(meta[0], MINOR_CATALOG_SERVICE_IDS[meta[1]], meta[2], meta[3], meta[4], days, status)
    body = {"repositories": repositories}
    total, names, locs, skipped = 0.0, [], [], []
    for repo in (body.get("repositories") or []):
        size = float(repo.get("sizeBytes") or 0)
        if size <= 0:
            continue
        parts = str(repo.get("name", "")).split("/")
        loc = parts[3] if len(parts) > 3 else ""
        short = parts[-1] if parts else "repo"
        price, _ = _infra_pick_price(skus, loc, ["artifact registry storage"], ["egress", "network"], "GiBy.mo")
        names.append(short)
        locs.append(loc)
        if price is None:
            skipped.append(f"{short}: storage price not found in catalog ({loc})")
        else:
            total += size / _GIB * price * _infra_month_fraction(days * 24.0)
    if not names:
        return None
    return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=names, locations=locs, gross=total, days=days,
                       status=_status(total, skipped), note="; ".join(skipped))


# ----------------------------------------------------------------------------- Secret Manager

def build_secretmanager_line(pid, token, days, skus, fetch=None, now=None, mon_fetch=None):
    meta = ("secretmanager.googleapis.com", "secretmanager", "Secret Manager", "Active secret versions", "🔑")
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=20, user_project=pid))
    base = f"https://secretmanager.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/secrets"
    status, body = fetch(f"{base}?pageSize=100")
    if status != 200:
        return _infra_unavailable(meta[0], MINOR_CATALOG_SERVICE_IDS[meta[1]], meta[2], meta[3], meta[4], days, status)
    secrets = [s for s in (body.get("secrets") or []) if isinstance(s, dict)]
    if not secrets:
        return None
    price, _ = _infra_pick_price(skus, "", ["secret version replica storage"], None, None)
    replicas_total, skipped = 0, []

    def read_versions(sec: dict):
        name = str(sec.get("name", "")).split("/")[-1]
        st, vb = fetch(f"{base}/{urllib.parse.quote(name)}/versions?pageSize=100&filter=state%3AENABLED")
        if st != 200 or not isinstance(vb, dict):
            return name, st, 0
        user_managed = ((sec.get("replication") or {}).get("userManaged") or {}).get("replicas") or []
        return name, st, len(vb.get("versions") or []) * max(1, len(user_managed))

    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, st, replicas in pool.map(read_versions, secrets[:50]):
            if st != 200:
                skipped.append(f"{name}: versions unreadable (HTTP {st})")
            else:
                replicas_total += replicas
    if len(secrets) > 50:
        skipped.append(f"only the first 50 of {len(secrets)} secrets were counted")
    if price is None:
        return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=[f"{len(secrets)} secret"], locations=[],
                           gross=0.0, days=days, status="not_estimable", note="version replica price not found in catalog")
    total = replicas_total * price * _infra_month_fraction(days * 24.0)
    return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=[f"{len(secrets)} secrets, {replicas_total} active replicas"],
                       locations=[], gross=total, days=days, status="partial" if skipped else "ok", note="; ".join(skipped))


# ----------------------------------------------------------------------------- BigQuery

def build_bigquery_line(pid, token, days, skus, fetch=None, now=None, mon_fetch=None):
    meta = ("bigquery.googleapis.com", "bigquery", "BigQuery", "Analysis and storage (gross of free tiers)", "📊")
    mon = mon_fetch or _minor_default_mon_fetch(pid, token, days, now)
    scanned = mon("bigquery.googleapis.com/query/scanned_bytes_billed", ["resource.label.location"], "ALIGN_SUM")
    stored = mon("bigquery.googleapis.com/storage/stored_bytes", ["resource.label.location"], "ALIGN_MAX")
    total, items, locs, skipped = 0.0, [], [], []
    for ts in scanned:
        tib = sum(_series_values(ts)) / _TIB
        loc = _series_label(ts, "resource", "location").lower()
        if tib <= 0:
            continue
        price, _ = _infra_pick_price(skus, loc, ["analysis"], ["flat", "edition", "slot", "bi engine", "omni", "storage", "free"], "TiBy")
        locs.append(loc)
        items.append(f"analisi {tib:.3f} TiB")
        if price is None:
            skipped.append(f"analysis {loc}: price not found in catalog")
        else:
            total += tib * price
    for ts in stored:
        gib = _series_mean(ts) / _GIB
        loc = _series_label(ts, "resource", "location").lower()
        if gib <= 0:
            continue
        price, _ = _infra_pick_price(skus, loc, ["active logical storage"], ["long term", "physical"], "GiBy.mo")
        locs.append(loc)
        items.append(f"storage {gib:.1f} GiB")
        if price is None:
            skipped.append(f"storage {loc}: price not found in catalog")
        else:
            total += gib * price * _infra_month_fraction(days * 24.0)
    if not items:
        return None
    return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=items, locations=locs, gross=total, days=days,
                       status=_status(total, skipped), note="; ".join(skipped))


# ----------------------------------------------------------------------------- Cloud Storage

_STORAGE_CLASSES = {"STANDARD": "standard", "NEARLINE": "nearline", "COLDLINE": "coldline", "ARCHIVE": "archive",
                    "REGIONAL": "standard", "MULTI_REGIONAL": "standard"}
_MULTI_REGIONS = {"eu": "europe", "us": "us", "asia": "asia"}


def build_storage_line(pid, token, days, skus, fetch=None, now=None, mon_fetch=None):
    meta = ("storage.googleapis.com", "storage", "Cloud Storage", "Buckets (storage only, excluding operations and traffic)", "🪣")
    mon = mon_fetch or _minor_default_mon_fetch(pid, token, days, now)
    series = mon("storage.googleapis.com/storage/total_bytes", ["resource.label.location", "metric.label.storage_class"], "ALIGN_MAX")
    total, items, locs, skipped = 0.0, [], [], []
    for ts in series:
        gib = _series_mean(ts) / _GIB
        loc = _series_label(ts, "resource", "location").lower()
        cls = _STORAGE_CLASSES.get(_series_label(ts, "metric", "storage_class").upper())
        if gib <= 0 or not loc:
            continue
        locs.append(loc)
        items.append(f"{cls or '?'} {gib:.2f} GiB")
        if cls is None:
            skipped.append(f"{loc}: unsupported storage class")
            continue
        if loc in _MULTI_REGIONS:
            price, _ = _infra_pick_price(skus, loc, [f"{cls} storage", _MULTI_REGIONS[loc], "multi-region"],
                                         ["operations", "network", "early", "retrieval", "dual"], "GiBy.mo")
            if price is None:
                price, _ = _infra_pick_price(skus, "", [f"{cls} storage", _MULTI_REGIONS[loc], "multi-region"],
                                             ["operations", "network", "early", "retrieval", "dual"], "GiBy.mo")
        else:
            price, _ = _infra_pick_price(skus, loc, [f"{cls} storage"],
                                         ["operations", "network", "early", "retrieval", "multi-region", "dual"], "GiBy.mo")
        if price is None:
            skipped.append(f"{cls} {loc}: price not found in catalog")
        else:
            total += gib * price * _infra_month_fraction(days * 24.0)
    if not items:
        return None
    return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=items, locations=locs, gross=total, days=days,
                       status=_status(total, skipped), note="; ".join(skipped))


# ----------------------------------------------------------------------------- Cloud Run

# Conversion of the unit reported by the metric descriptor into the unit of the catalog price.
_RUN_MEMORY_UNITS = {"GiBy.s": 1.0, "By.s": 1.0 / 2 ** 30, "GBy.s": 1e9 / 2 ** 30, "MiBy.s": 1.0 / 1024, "KiBy.s": 1.0 / 2 ** 20}
_RUN_CPU_UNITS = {"s": 1.0}


def _minor_default_desc_fetch(pid: str, token: str):
    def fetch(metric_type: str):
        url = f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(pid)}/metricDescriptors/{metric_type}"
        status, body = gcp_api_get(url, token, timeout=20, user_project=pid)
        return str(body.get("unit", "")) if status == 200 and isinstance(body, dict) else None
    return fetch


def _run_unit_factor(metric: str, table: dict, desc_fetch) -> tuple[float, str]:
    """(factor, note): factor converts the metric unit into the catalog unit; unknown unit or failed read -> 1.0 plus
    a note, because the estimate would otherwise silently assume the unit."""
    try:
        unit = desc_fetch(metric)
    except Exception:
        unit = None
    unit = re.sub(r"\{[^}]*\}", "", unit).strip() if isinstance(unit, str) else ""
    if unit in table:
        return table[unit], ""
    return 1.0, "metric unit not verified"


def build_run_line(pid, token, days, skus, fetch=None, now=None, mon_fetch=None, desc_fetch=None):
    meta = ("run.googleapis.com", "run", "Cloud Run", "Request-billed services (gross of free tiers)", "🚀")
    mon = mon_fetch or _minor_default_mon_fetch(pid, token, days, now)
    desc_fetch = desc_fetch or _minor_default_desc_fetch(pid, token)
    metrics = (("run.googleapis.com/container/cpu/allocation_time", "vCPU-s", ["services cpu", "request-based"], _RUN_CPU_UNITS),
               ("run.googleapis.com/container/memory/allocation_time", "GiB-s", ["services memory", "request-based"], _RUN_MEMORY_UNITS),
               ("run.googleapis.com/request_count", "requests", ["requests"], None))
    total, items, locs, skipped = 0.0, [], [], []
    unit_notes = []
    for metric, label, tokens, unit_table in metrics:
        factor = 1.0
        series_list = mon(metric, ["resource.label.location"], "ALIGN_SUM")
        if unit_table is not None and any(sum(_series_values(ts)) > 0 for ts in series_list):
            factor, unit_note = _run_unit_factor(metric, unit_table, desc_fetch)
            if unit_note:
                unit_notes.append(f"{label}: {unit_note}")
        for ts in series_list:
            qty = sum(_series_values(ts)) * factor
            loc = _series_label(ts, "resource", "location").lower()
            if qty <= 0:
                continue
            price, _ = _infra_pick_price(skus, loc, tokens, ["instance-based", "gen1", "functions", "jobs", "worker"], None)
            locs.append(loc)
            items.append(f"{label} {qty:,.0f}")
            if price is None:
                skipped.append(f"{label} {loc}: price not found in catalog")
            else:
                total += qty * price
    if not items:
        return None
    return _minor_line(meta[0], meta[1], meta[2], meta[3], meta[4], items=items, locations=locs, gross=total, days=days,
                       status=_status(total, skipped), note="; ".join(skipped + unit_notes))


MINOR_INFRA_BUILDERS = [
    ("artifactregistry.googleapis.com", "artifactregistry", build_artifactregistry_line),
    ("secretmanager.googleapis.com", "secretmanager", build_secretmanager_line),
    ("bigquery.googleapis.com", "bigquery", build_bigquery_line),
    ("storage.googleapis.com", "storage", build_storage_line),
    ("run.googleapis.com", "run", build_run_line),
]
