"""Fixed-cost estimates for the infrastructure that backs AI workloads (Cloud SQL, Memorystore Redis, Compute Engine).

Nothing here is taken from an invoice: the resources are read, read-only, from the project's own admin APIs and priced
with the public Cloud Billing Catalog (list price, USD). An optional local setting (`infraSavingsPct`) models the
discounts of the user's own contract. Every line is an ESTIMATE and says so; when a resource, a permission or a price
is missing the line says "not available" / "not estimable" instead of showing 0.

Hours of activity are an assumption (the resource ran for the whole window, or since its creation). Backups, network
egress, licences and sustained-use discounts are not included.
"""

import json
import math
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone

INFRA_CATALOG_SERVICE_IDS = {
    "sql": "9662-B51E-5089",
    "redis": "5AF5-2C11-D467",
    "compute": "6F81-5844-456A",
    # smaller supporting services (see infra_costs_minor.py)
    "artifactregistry": "149C-F9EC-3994",
    "secretmanager": "EE82-7A5E-871C",
    "bigquery": "24E6-581D-38E5",
    "storage": "95FF-2EF5-5EA1",
    "run": "152E-C115-5142",
}
INFRA_CATALOG_CACHE_FILE = os.path.join(DATA_DIR, "infra_catalog_cache.json")
INFRA_CATALOG_TTL_S = 7 * 86400

_infra_catalog_lock = threading.Lock()
_infra_catalog_mem: dict = {"loadedAt": 0.0, "skus": None}


# ----------------------------------------------------------------------------- catalog

def _infra_compact_sku(sku: dict) -> dict | None:
    price, unit = _catalog_sku_unit_price(sku)
    if price is None:
        return None
    return {
        "d": str(sku.get("description") or ""),
        "u": unit,
        "p": price,
        "r": list(sku.get("serviceRegions") or []),
    }


def _infra_catalog_fetch(token: str, fetch=None) -> dict | None:
    """All SKUs of the three services, compacted. None if any page fails (never a partial catalog)."""
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=25))
    out: dict = {}
    for key, svc_id in INFRA_CATALOG_SERVICE_IDS.items():
        skus: list = []
        page_token = ""
        for _ in range(15):
            url = f"https://cloudbilling.googleapis.com/v1/services/{svc_id}/skus?pageSize=5000"
            if page_token:
                url += f"&pageToken={urllib.parse.quote(page_token)}"
            status, body = fetch(url)
            if status != 200 or not isinstance(body, dict):
                return None
            for sku in body.get("skus") or []:
                c = _infra_compact_sku(sku)
                if c:
                    skus.append(c)
            page_token = body.get("nextPageToken") or ""
            if not page_token:
                break
        else:
            return None  # more than 15 pages: refuse a partial catalog
        out[key] = skus
    return out


def get_infra_catalog(token: str, fetch=None) -> dict | None:
    """Catalog of fixed-cost SKUs: memory, then 7-day file cache, then the API (a stale cache beats nothing)."""
    if is_demo_mode():
        return None  # demo mode: no catalog download (nothing is estimated live)
    now = time.time()
    with _infra_catalog_lock:
        mem = _infra_catalog_mem
        if mem["skus"] is not None and now - mem["loadedAt"] < INFRA_CATALOG_TTL_S:
            return mem["skus"]
        stale = None
        try:
            with open(INFRA_CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, dict) and isinstance(cached.get("skus"), dict):
                stale = cached["skus"]
                complete = all(k in stale for k in INFRA_CATALOG_SERVICE_IDS)  # a cache from an older version lacks services
                if complete and now - float(cached.get("fetchedAt", 0)) < INFRA_CATALOG_TTL_S:
                    mem["skus"], mem["loadedAt"] = stale, now
                    return stale
        except (OSError, ValueError, TypeError):
            pass
        fresh = _infra_catalog_fetch(token, fetch)
        if fresh is None:
            if stale is not None:
                mem["skus"], mem["loadedAt"] = stale, now
            return stale
        try:
            os.makedirs(os.path.dirname(INFRA_CATALOG_CACHE_FILE), exist_ok=True)
            tmp = INFRA_CATALOG_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetchedAt": now, "skus": fresh}, f)
            os.replace(tmp, INFRA_CATALOG_CACHE_FILE)
        except OSError:
            pass
        mem["skus"], mem["loadedAt"] = fresh, now
        return fresh


def _infra_pick_price(skus: list, region: str, must: list, none: list | None = None, unit: str | None = None,
                      prefix: str | None = None):
    """(price, unit) of the SKU whose description has every `must` token and none of `none`, valid in `region`.
    Several candidates: the one with the shortest description (the most generic), deterministic."""
    none = [n.lower() for n in (none or [])]
    must = [m.lower() for m in must]
    best = None
    for s in skus:
        d = s["d"].lower()
        if not all(m in d for m in must) or any(n in d for n in none):
            continue
        if prefix and not d.startswith(prefix.lower()):
            continue
        if unit and s["u"] != unit:
            continue
        regs = s["r"]
        if region and regs and region not in regs and "global" not in regs:
            continue
        if best is None or len(s["d"]) < len(best["d"]):
            best = s
    return (best["p"], best["u"]) if best else (None, "")


# ----------------------------------------------------------------------------- helpers

def _infra_parse_ts(value) -> datetime | None:
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _infra_hours(created, days: int, now: datetime | None = None) -> float:
    """Hours the resource existed inside the scan window (24 h/day, assumed always on)."""
    now = now or datetime.now(timezone.utc)
    created_dt = _infra_parse_ts(created)
    window_days = float(max(1, days))
    if created_dt is None:
        return window_days * 24.0
    existed = max(0.0, (now - created_dt).total_seconds() / 86400.0)
    return min(window_days, existed) * 24.0


def _infra_month_fraction(hours: float) -> float:
    """Share of a billing month covered by `hours`. A window of about one month (28-31 days) counts as exactly 1,
    as the invoice does for a full calendar month; shorter or longer windows are pro-rated on 30.4375 days."""
    days = hours / 24.0
    return 1.0 if 28.0 <= days <= 31.0 else days / 30.4375


def _infra_line(service: str, service_id: str, name: str, subtitle: str, icon: str, *, instances: list,
                locations: list, gross: float, days: int, status: str, note: str = "") -> dict:
    """One line of `infraServices`, in the shape the UI and the period slicing already use."""
    pct = _infra_savings_pct()
    gross = round(max(0.0, gross), 4)
    sav = round(gross * pct / 100.0, 4)
    net = round(gross - sav, 4)
    details = [", ".join(instances[:4]) + (f" +{len(instances) - 4}" if len(instances) > 4 else "") if instances else "",
               ", ".join(locations), f"{days} days", {"ok": "list-price estimate", "partial": "partial estimate"}.get(status, ""), note[:400]]
    return {
        "service": service,
        "serviceId": service_id,
        "name": f"{name} ({subtitle})",
        "shortName": name,
        "icon": icon,
        "instances": instances,
        "locations": locations,
        "activeDays": days,
        "grossCostUsd": gross,
        "negotiatedSavingsUsd": sav,
        "cudSavingsUsd": 0.0,
        "savingsUsd": sav,
        "costUsd": net,
        "unroundedEur": round(net * get_usd_to_eur_rate(), 6),
        "estimated": True,
        "estimateStatus": status,
        "note": note,
        "estimateNote": note,
        "details": " · ".join(x for x in details if x),
    }


def _infra_savings_pct() -> float:
    try:
        v = float(get_billing_settings().get("infraSavingsPct", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        v = 0.0
    return max(0.0, min(100.0, v))


def _infra_unavailable(service, service_id, name, subtitle, icon, days, status_code) -> dict:
    why = "missing permission or API not enabled" if status_code in (401, 403) else f"read failed (HTTP {status_code})"
    return _infra_line(service, service_id, name, subtitle, icon, instances=[], locations=[], gross=0.0, days=days,
                       status="unavailable", note=f"Data unavailable: {why}")


# ----------------------------------------------------------------------------- Cloud SQL

_SQL_ENGINES = (("POSTGRES", "PostgreSQL"), ("MYSQL", "MySQL"))


def _sql_shape(tier: str):
    """(vCPU, RAM GiB) of a Cloud SQL tier, or None for shared-core / unknown tiers."""
    t = str(tier or "").lower()
    m = re.fullmatch(r"db-custom-(\d+)-(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(2)) / 1024.0
    m = re.fullmatch(r"db-perf-optimized-n-(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(1)) * 8.0
    m = re.fullmatch(r"db-n1-(standard|highmem)-(\d+)", t)
    if m:
        n = int(m.group(2))
        return n, n * (3.75 if m.group(1) == "standard" else 6.5)
    return None


def fetch_sql_data_cache_quota_gib(pid: str, token: str, days: int, fetch=None, now: datetime | None = None) -> dict:
    """Real data cache size per instance (GiB) from the Cloud Monitoring gauge database/data_cache/quota."""
    now = now or datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_iso = datetime.fromtimestamp(now.timestamp() - max(1, days) * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    flt = 'metric.type="cloudsql.googleapis.com/database/data_cache/quota"'
    fetch = fetch or (lambda: fetch_monitoring_timeseries(pid, token, flt, start_iso, end_iso,
                                                          ["resource.label.database_id"], "ALIGN_MAX"))
    out: dict = {}
    try:
        series = fetch() or []
    except Exception:  # noqa: BLE001 - a missing metric must never break the scan: the fallback estimate is used
        return out
    for ts in series:
        db_id = str(((ts.get("resource") or {}).get("labels") or {}).get("database_id", ""))
        name = db_id.split(":")[-1]
        vals = []
        for pt in ts.get("points") or []:
            v = (pt.get("value") or {}).get("int64Value", (pt.get("value") or {}).get("doubleValue"))
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if name and vals and max(vals) > 0:
            out[name] = max(vals) / 2 ** 30
    return out


def estimate_sql_instance(inst: dict, skus: list, days: int, now: datetime | None = None,
                          cache_gib: float | None = None) -> tuple[float | None, str]:
    """(list-price cost for the window, reason). None cost = not estimable. `cache_gib` = real data cache size."""
    st = inst.get("settings") or {}
    tier = st.get("tier") or ""
    shape = _sql_shape(tier)
    engine = next((label for key, label in _SQL_ENGINES if str(inst.get("databaseVersion", "")).startswith(key)), None)
    if engine is None:
        return None, f"unsupported engine {inst.get('databaseVersion', '?')}"
    if shape is None:
        return None, f"unsupported tier {tier or '?'}"
    vcpu, ram = shape
    region = inst.get("region") or ""
    plus = str(st.get("edition", "")).upper() == "ENTERPRISE_PLUS"
    ha = "regional" if str(st.get("availabilityType", "")).upper() == "REGIONAL" else "zonal"
    reason = ""
    hours = _infra_hours(inst.get("createTime"), days, now)
    base = [f"cloud sql for {engine.lower()}", ha]
    ed_must, ed_none = (["enterprise plus"], []) if plus else ([], ["enterprise plus"])
    parts = {"vCPU": (vcpu * hours, ["vcpu"], "h"), "RAM": (ram * hours, [" ram"], "GiBy.h")}
    cost = 0.0
    running = str(st.get("activationPolicy", "ALWAYS")).upper() != "NEVER"
    for label, (qty, tokens, unit) in parts.items():
        if not running:
            continue
        price, _ = _infra_pick_price(skus, region, base + ed_must + tokens, ed_none + ["data cache", "backup"], unit)
        if price is None:
            return None, f"{label} price not found in catalog ({region})"
        cost += qty * price
    disk_gib = float(st.get("dataDiskSizeGb") or 0)
    if disk_gib > 0:
        hdd = str(st.get("dataDiskType", "")).upper() == "PD_HDD"
        for tokens in ([["hdd storage"]] if hdd else [["standard storage"], ["ssd storage"]]):
            price, _ = _infra_pick_price(skus, region, base + ed_must + tokens, ed_none + ["data cache", "backup"], "GiBy.mo")
            if price is not None:
                break
        if price is None:
            return None, f"disk price not found in catalog ({region})"
        cost += disk_gib * price * _infra_month_fraction(hours)
    if (st.get("dataCacheConfig") or {}).get("dataCacheEnabled"):
        if cache_gib is None:
            cache_gib = 375.0 * max(1, math.ceil(vcpu / 16))
            reason = "Data Cache size estimated (metric unavailable)"
        price, _ = _infra_pick_price(skus, region, base + ed_must + ["data cache"], ed_none, "GiBy.mo")
        if price is None:
            return None, f"data cache price not found in catalog ({region})"
        cost += cache_gib * price * _infra_month_fraction(hours)
    return cost, reason


def build_sql_line(pid: str, token: str, days: int, skus: list, fetch=None, now: datetime | None = None,
                   cache_fetch=None) -> dict:
    sid = INFRA_CATALOG_SERVICE_IDS["sql"]
    meta = ("sqladmin.googleapis.com", sid, "Cloud SQL", "Managed database", "🗄️")
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=20, user_project=pid))
    status, body = fetch(f"https://sqladmin.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/instances")
    if status != 200:
        return _infra_unavailable(*meta, days, status)
    items = [i for i in (body.get("items") or []) if isinstance(i, dict)]
    if not items:
        return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=[], locations=[], gross=0.0, days=days,
                           status="ok", note="No instances")
    total, names, regions, skipped, notes = 0.0, [], set(), [], []
    needs_cache = any(((i.get("settings") or {}).get("dataCacheConfig") or {}).get("dataCacheEnabled") for i in items)
    quotas = fetch_sql_data_cache_quota_gib(pid, token, days, now=now, fetch=cache_fetch) if needs_cache else {}
    for inst in items:
        cost, why = estimate_sql_instance(inst, skus, days, now, cache_gib=quotas.get(inst.get("name", "")))
        names.append(inst.get("name", "?"))
        regions.add(inst.get("region", ""))
        if cost is None:
            skipped.append(f"{inst.get('name', '?')}: {why}")
        else:
            total += cost
            if why:
                notes.append(f"{inst.get('name', '?')}: {why}")
    status_txt = "ok" if not skipped else ("partial" if total > 0 else "not_estimable")
    return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=names, locations=sorted(r for r in regions if r),
                       gross=total, days=days, status=status_txt, note="; ".join(skipped + notes))


# ----------------------------------------------------------------------------- Memorystore Redis

def _redis_capacity_class(gb: float) -> str:
    return "M1" if gb <= 4 else "M2" if gb <= 10 else "M3" if gb <= 35 else "M4" if gb <= 100 else "M5"


def estimate_redis_instance(inst: dict, skus: list, days: int, now: datetime | None = None) -> tuple[float | None, str]:
    region = str(inst.get("name", "")).split("/locations/")[-1].split("/")[0]
    gb = float(inst.get("memorySizeGb") or 0)
    if gb <= 0:
        return None, "memory size missing"
    tier = "standard" if str(inst.get("tier", "")).upper() == "STANDARD_HA" else "basic"
    hours = _infra_hours(inst.get("createTime"), days, now)
    price, _ = _infra_pick_price(skus, region, ["redis capacity", tier, _redis_capacity_class(gb).lower()], ["read replica"])
    if price is None:
        return None, f"Redis {tier} {_redis_capacity_class(gb)} price not found in catalog ({region})"
    return gb * hours * price, ""


def build_redis_line(pid: str, token: str, days: int, skus: list, fetch=None, now: datetime | None = None) -> dict:
    sid = INFRA_CATALOG_SERVICE_IDS["redis"]
    meta = ("redis.googleapis.com", sid, "Cloud Memorystore for Redis", "Session cache", "⚡")
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=20, user_project=pid))
    status, body = fetch(f"https://redis.googleapis.com/v1/projects/{urllib.parse.quote(pid)}/locations/-/instances")
    if status != 200:
        return _infra_unavailable(*meta, days, status)
    items = [i for i in (body.get("instances") or []) if isinstance(i, dict)]
    if not items:
        return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=[], locations=[], gross=0.0, days=days,
                           status="ok", note="No instances")
    total, names, regions, skipped = 0.0, [], set(), []
    for inst in items:
        cost, why = estimate_redis_instance(inst, skus, days, now)
        short = str(inst.get("name", "?")).split("/")[-1]
        names.append(short)
        regions.add(str(inst.get("name", "")).split("/locations/")[-1].split("/")[0])
        if cost is None:
            skipped.append(f"{short}: {why}")
        else:
            total += cost
    status_txt = "ok" if not skipped else ("partial" if total > 0 else "not_estimable")
    return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=names, locations=sorted(r for r in regions if r),
                       gross=total, days=days, status=status_txt, note="; ".join(skipped))


# ----------------------------------------------------------------------------- Compute Engine

_GCE_SIZES = {"standard": 4.0, "highmem": 8.0, "highcpu": 1.0}
_GCE_N1_SIZES = {"standard": 3.75, "highmem": 6.5, "highcpu": 0.9}
_GCE_SHARED = {"micro", "small", "medium"}
_GCE_DISK_TOKENS = {
    "pd-standard": (["storage pd capacity"], ["regional", "snapshot", "extreme"]),
    "pd-balanced": (["balanced pd capacity"], ["regional", "snapshot"]),
    "pd-ssd": (["ssd backed pd capacity"], ["regional", "snapshot", "extreme"]),
}


def _gce_shape(machine_type: str):
    """(family, vCPU, RAM GiB, custom?) for predefined, custom and shared-core machine types."""
    t = str(machine_type or "").split("/")[-1].lower()
    m = re.fullmatch(r"([a-z0-9]+)-custom-(\d+)-(\d+)", t) or re.fullmatch(r"(custom)-(\d+)-(\d+)", t)
    if m:
        fam = m.group(1) if m.group(1) != "custom" else "n1"
        return fam, int(m.group(2)), int(m.group(3)) / 1024.0, True
    m = re.fullmatch(r"([a-z0-9]+)-(standard|highmem|highcpu)-(\d+)", t)
    if m:
        n = int(m.group(3))
        table = _GCE_N1_SIZES if m.group(1) == "n1" else _GCE_SIZES
        return m.group(1), n, n * table[m.group(2)], False
    m = re.fullmatch(r"e2-(micro|small|medium)", t)
    if m:  # shared-core E2 are billed as fractional vCPU + RAM at the E2 rates
        vcpu, ram = {"micro": (0.25, 1.0), "small": (0.5, 2.0), "medium": (1.0, 4.0)}[m.group(1)]
        return "e2", vcpu, ram, False
    if t in ("f1-micro", "g1-small"):  # legacy shared-core: one price per instance-hour
        return "legacy", t.split("-")[1], 0.0, False
    return None


def _gce_instance_cost(inst: dict, skus: list, days: int, now) -> tuple[float | None, str]:
    zone = str(inst.get("zone", "")).split("/")[-1]
    region = zone.rsplit("-", 1)[0]
    shape = _gce_shape(inst.get("machineType"))
    if shape is None:
        return None, f"unsupported machine type {str(inst.get('machineType', '?')).split('/')[-1]}"
    fam, vcpu, ram, custom = shape
    sched = inst.get("scheduling") or {}
    spot = str(sched.get("provisioningModel", "")).upper() == "SPOT" or bool(sched.get("preemptible"))
    hours = _infra_hours(inst.get("creationTimestamp"), days, now)
    pre = ["spot preemptible"] if spot else []
    pre_none = [] if spot else ["spot preemptible", "commitment", "sole tenancy", "windows", "sles", "rhel"]
    cust = ["custom"] if custom else []
    cust_none = [] if custom else ["custom"]
    if isinstance(vcpu, str):  # legacy f1-micro / g1-small
        token = "micro instance with burstable cpu" if vcpu == "micro" else "small instance with 1 vcpu"
        price, _ = _infra_pick_price(skus, region, [token] + pre, pre_none, "h")
        if price is None:
            return None, f"f1/g1 {vcpu} price not found in catalog ({region})"
        return price * hours, ""
    if fam == "n1" and custom:  # N1 custom SKUs carry no family name: "Custom Instance Core running in ..."
        core, _ = _infra_pick_price(skus, region, ["instance core"] + pre, pre_none + ["extended"], "h", prefix="custom instance core")
        mem, _ = _infra_pick_price(skus, region, ["instance ram"] + pre, pre_none + ["extended"], "GiBy.h", prefix="custom instance ram")
    else:
        core, _ = _infra_pick_price(skus, region, [f"{fam} "] + cust + pre + ["instance core"], pre_none + cust_none + ["ram"], "h")
        mem, _ = _infra_pick_price(skus, region, [f"{fam} "] + cust + pre + ["instance ram"], pre_none + cust_none, "GiBy.h")
    if core is None or mem is None:
        return None, f"{fam} core/RAM price not found in catalog ({region})"
    return (vcpu * core + ram * mem) * hours, ""


def _gce_disk_cost(disk: dict, skus: list, days: int, now) -> tuple[float | None, str]:
    region = str(disk.get("zone", "") or disk.get("region", "")).split("/")[-1]
    if disk.get("zone"):
        region = region.rsplit("-", 1)[0]
    dtype = str(disk.get("type", "")).split("/")[-1].lower()
    spec = _GCE_DISK_TOKENS.get(dtype)
    if spec is None:
        return None, f"unsupported disk type {dtype or '?'}"
    price, _ = _infra_pick_price(skus, region, spec[0], spec[1], "GiBy.mo")
    if price is None:
        return None, f"{dtype} disk price not found in catalog ({region})"
    hours = _infra_hours(disk.get("creationTimestamp"), days, now)
    return float(disk.get("sizeGb") or 0) * price * _infra_month_fraction(hours), ""


def _gce_address_cost(addr: dict, skus: list, days: int, now) -> tuple[float | None, str]:
    region = str(addr.get("region", "")).split("/")[-1]
    hours = _infra_hours(addr.get("creationTimestamp"), days, now)
    if str(addr.get("status", "")).upper() == "RESERVED":
        price, _ = _infra_pick_price(skus, region, ["static ip charge"], None, "h")
    else:
        price, _ = _infra_pick_price(skus, region, ["ip", "standard vm"], ["spot", "preemptible"], "h")
    if price is None:
        return None, f"IP price not found in catalog ({region or 'global'})"
    return price * hours, ""


def _gce_flatten(body: dict, key: str) -> list:
    out = []
    for scoped in (body.get("items") or {}).values():
        if isinstance(scoped, dict):
            out.extend(x for x in (scoped.get(key) or []) if isinstance(x, dict))
    return out


def build_compute_line(pid: str, token: str, days: int, skus: list, fetch=None, now: datetime | None = None) -> dict:
    sid = INFRA_CATALOG_SERVICE_IDS["compute"]
    meta = ("compute.googleapis.com", sid, "Compute Engine", "VMs, disks and static IPs", "🖥️")
    fetch = fetch or (lambda url: gcp_api_get(url, token, timeout=25, user_project=pid))
    base = f"https://compute.googleapis.com/compute/v1/projects/{urllib.parse.quote(pid)}/aggregated"
    resources = {}
    for key, path, field in (("vm", "instances", "instances"), ("disk", "disks", "disks"), ("addr", "addresses", "addresses")):
        status, body = fetch(f"{base}/{path}?maxResults=500")
        if status != 200:
            return _infra_unavailable(*meta, days, status)
        resources[key] = _gce_flatten(body, field)
    total, names, regions, skipped = 0.0, [], set(), []
    for vm in resources["vm"]:
        if str(vm.get("status", "")).upper() != "RUNNING":
            continue
        cost, why = _gce_instance_cost(vm, skus, days, now)
        names.append(vm.get("name", "vm"))
        regions.add(str(vm.get("zone", "")).split("/")[-1].rsplit("-", 1)[0])
        if cost is None:
            skipped.append(f"{vm.get('name', 'vm')}: {why}")
        else:
            total += cost
    for disk in resources["disk"]:
        cost, why = _gce_disk_cost(disk, skus, days, now)
        names.append(disk.get("name", "disk"))
        if cost is None:
            skipped.append(f"{disk.get('name', 'disk')}: {why}")
        else:
            total += cost
    for addr in resources["addr"]:
        if str(addr.get("addressType", "")).upper() != "EXTERNAL":
            continue
        cost, why = _gce_address_cost(addr, skus, days, now)
        names.append(addr.get("name", "ip"))
        regions.add(str(addr.get("region", "")).split("/")[-1])
        if cost is None:
            skipped.append(f"{addr.get('name', 'ip')}: {why}")
        else:
            total += cost
    if not names:
        return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=[], locations=[], gross=0.0, days=days,
                           status="ok", note="No resources")
    status_txt = "ok" if not skipped else ("partial" if total > 0 else "not_estimable")
    return _infra_line(*meta[:2], meta[2], meta[3], meta[4], instances=names, locations=sorted(r for r in regions if r),
                       gross=total, days=days, status=status_txt, note="; ".join(skipped))


# ----------------------------------------------------------------------------- entry point

def _minor_infra_builders() -> list:
    """Builders of the smaller services, defined in infra_costs_minor.py (same shared backend namespace); empty if that
    module is not loaded."""
    try:
        return MINOR_INFRA_BUILDERS  # noqa: F821 - provided by infra_costs_minor.py
    except NameError:
        return []


def build_infra_services_breakdown(pid: str, token: str, days: int, enabled_services: set, fetch=None,
                                   skus: dict | None = None, now: datetime | None = None) -> list:
    """Lines for the enabled fixed-cost services of one project. Empty list when none is enabled."""
    builders = [("sqladmin.googleapis.com", "sql", build_sql_line),
                ("redis.googleapis.com", "redis", build_redis_line),
                ("compute.googleapis.com", "compute", build_compute_line)]
    builders += list(_minor_infra_builders())
    wanted = [(svc, key, fn) for svc, key, fn in builders if svc in enabled_services]
    if not wanted:
        return []
    catalog = skus if skus is not None else get_infra_catalog(token)
    out = []
    for svc, key, fn in wanted:
        if not catalog or not catalog.get(key):
            sid = INFRA_CATALOG_SERVICE_IDS[key]
            out.append(_infra_line(svc, sid, svc.split(".")[0], "price catalog unavailable", "❔", instances=[],
                                   locations=[], gross=0.0, days=days, status="unavailable",
                                   note="Data unavailable: price catalog unreachable"))
            continue
        try:
            line = fn(pid, token, days, catalog[key], fetch=fetch, now=now)
        except Exception as exc:  # noqa: BLE001 - an unexpected API shape must never abort the scan of the whole project
            line = _infra_line(svc, INFRA_CATALOG_SERVICE_IDS[key], svc.split(".")[0], "estimation error", "❔", instances=[],
                               locations=[], gross=0.0, days=days, status="unavailable",
                               note=f"Estimate failed ({type(exc).__name__})")
        if line is not None:  # the smaller services return None when the project has nothing of them
            out.append(line)
    return out
