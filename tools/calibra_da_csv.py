#!/usr/bin/env python3
"""Propose cost-calibration values from a Google Cloud Billing CSV export (read-only).

Reads one or more "Cost table / report" CSV files exported from the Cloud Billing console
(grouped by SKU, Italian locale: decimal comma, dot as thousands separator) and PROPOSES the values
to enter in JanusTower > Pricing & Rates > Billing settings. It never changes any setting by itself.

What it derives (all arithmetic, no AI):
  - credit discount per service  = -other savings / list cost            (Vertex AI, Gemini API)
  - cache hit ratio per model    = cached tokens / (cached + uncached input tokens)
  - regional multiplier          = regional unit price / global unit price (same model, same token kind)
  - USD -> EUR rate              = EUR unit price in the invoice / USD catalog price (from the local pricing file)

Privacy: the CSV contains only service/SKU/costs. Keep it in data/ (ignored by Git). The proposal is
written to data/ too (ignored by Git) and only aggregated numbers are printed.

Usage:
  python tools/calibra_da_csv.py REPORT_OCT.csv [REPORT_NOV.csv ...] [--pricing data/models_pricing_config.json]
                                  [--out data/calibration_proposal.json] [--min-list-eur 1.0]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

TOKEN_SERVICES = ("Vertex AI", "Gemini API")
_STOP_WORDS = {
    "global", "regional", "text", "image", "audio", "video", "input", "output", "caching", "cached",
    "cache", "token", "count", "online", "predictions", "prediction", "for", "when", "generate", "content",
}


_SUSPECT_ENGLISH_NUMBER = re.compile(r"^-?\d+\.\d{1,2}$")


def looks_like_english_number(raw: str) -> bool:
    """'1.5' or '12.34' (dot decimal, no comma): in the Italian export it would be read as 15 / 1234."""
    return bool(_SUSPECT_ENGLISH_NUMBER.match((raw or "").strip()))


def parse_number(raw: str) -> float:
    """Parse an Italian-locale number ("1.850,70", "115.946.171", "0,01"). Non-numeric -> 0.0."""
    txt = (raw or "").strip().replace("−", "-")
    if not txt or txt.lower() in {"nuova", "new"} or txt.endswith("%"):
        return 0.0
    txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _col(row: dict, prefix: str) -> str:
    for key in row:
        if key and key.strip().lower().startswith(prefix.lower()):
            return row[key]
    return ""


def model_label_from_sku(sku: str) -> str | None:
    """'Gemini 4 Argon Regional Text Input - Online Predictions' -> 'gemini-4-argon'."""
    m = re.search(r"gemini\s+(.+)", sku, re.IGNORECASE)
    if not m:
        return None
    words = []
    for w in re.split(r"\s+", m.group(1).strip()):
        wl = w.lower().strip("-")
        if wl in _STOP_WORDS or wl == "":
            break
        words.append(wl)
    if not words:
        return None
    return "gemini-" + "-".join(w for w in words if w != "/")


def classify_sku(sku: str) -> dict | None:
    """Return {'kind': input|output|cache, 'modality': text|image, 'scope': global|regional|api}, or None."""
    low = sku.lower()
    if "gemini" not in low:
        return None
    if any(w in low for w in ("storage", "token hour", "token-hour", "per hour")):
        return None  # billed per hour/GiB, not per token
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


def load_rows(paths: list[Path], warnings: list[str] | None = None) -> list[dict]:
    rows: list[dict] = []
    flagged = False
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                service = (_col(raw, "Descrizione servizio") or "").strip()
                sku = (_col(raw, "Descrizione SKU") or "").strip()
                info = classify_sku(sku)
                if service not in TOKEN_SERVICES or info is None:
                    continue
                label = model_label_from_sku(sku)
                if not label:
                    continue
                if warnings is not None and not flagged and any(
                    looks_like_english_number(_col(raw, c)) for c in ("Quantità di utilizzo", "Costo di listino")
                ):
                    warnings.append(f"{path.name}: numbers with a dot decimal were found: the CSV may be in English format "
                                    "(this tool expects the Italian format with decimal comma).")
                    flagged = True
                rows.append({
                    "service": service, "model": label, "sku": sku, "source": path.name, **info,
                    "qty": parse_number(_col(raw, "Quantità di utilizzo")),
                    "list": parse_number(_col(raw, "Costo di listino")),
                    "negotiated": parse_number(_col(raw, "Risparmi negoziati")),
                    "other": parse_number(_col(raw, "Altri risparmi")),
                })
    return rows


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den > 0 else None


def compute_discounts(rows: list[dict], min_list_eur: float) -> tuple[dict, dict]:
    """Credit discount (other savings / list cost) per service and per (service, model)."""
    per_service: dict[str, list[float]] = {}
    per_model: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["list"] <= 0:
            continue
        s = per_service.setdefault(r["service"], [0.0, 0.0])
        s[0] += r["list"]
        s[1] += -r["other"]
        m = per_model.setdefault(f"{r['service']}|{r['model']}", {"list": 0.0, "disc": 0.0})
        m["list"] += r["list"]
        m["disc"] += -r["other"]
    services = {k: _pct(v[1], v[0]) for k, v in per_service.items() if v[0] >= min_list_eur}
    models = {k: _pct(v["disc"], v["list"]) for k, v in per_model.items() if v["list"] >= min_list_eur}
    return services, models


def compute_cache_ratios(rows: list[dict], min_list_eur: float) -> dict:
    """cached tokens / (cached + uncached input tokens), per (service, model)."""
    agg: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["kind"] not in ("input", "cache"):
            continue
        a = agg.setdefault(f"{r['service']}|{r['model']}", {"cached": 0.0, "uncached": 0.0, "list": 0.0})
        a["cached" if r["kind"] == "cache" else "uncached"] += r["qty"]
        a["list"] += r["list"]
    out = {}
    for key, a in agg.items():
        total = a["cached"] + a["uncached"]
        if total > 0 and a["list"] >= min_list_eur:
            out[key] = {"cachePct": _pct(a["cached"], total), "cachedTokens": int(a["cached"]), "inputTokens": int(total)}
    return out


def weighted_service_cache(cache_by_model: dict, service: str) -> float | None:
    cached = sum(v["cachedTokens"] for k, v in cache_by_model.items() if k.startswith(service + "|"))
    total = sum(v["inputTokens"] for k, v in cache_by_model.items() if k.startswith(service + "|"))
    return _pct(cached, total)


def compute_regional_multiplier(rows: list[dict], min_list_eur: float = 1.0) -> dict:
    """Regional / global unit price (EUR per token) for the same Vertex model and text token kind."""
    sums: dict[tuple, dict[str, list[float]]] = {}
    for r in rows:
        if r["service"] != "Vertex AI" or r["modality"] != "text" or r["kind"] == "cache" or r["qty"] <= 0:
            continue
        if r["scope"] not in ("regional", "global"):
            continue
        acc = sums.setdefault((r["model"], r["kind"]), {}).setdefault(r["scope"], [0.0, 0.0])
        acc[0] += r["list"]
        acc[1] += r["qty"]
    # ignore groups where either side is tiny (cent-level rounding makes the unit price meaningless)
    unit = {k: {sc: v[0] / v[1] for sc, v in d.items() if v[1] > 0 and v[0] >= min_list_eur} for k, d in sums.items()}
    ratios = [v["regional"] / v["global"] for v in unit.values() if v.get("regional") and v.get("global")]
    if not ratios:
        return {"multiplier": None, "samples": 0}
    return {
        "multiplier": round(statistics.median(ratios), 4),
        "samples": len(ratios),
        "min": round(min(ratios), 4),
        "max": round(max(ratios), 4),
    }


def _eur_samples(rows: list[dict], models: dict, min_list_eur: float) -> list[float]:
    ratios = []
    for r in rows:
        if r["modality"] != "text" or r["kind"] not in ("input", "output") or r["scope"] == "regional":
            continue
        if r["qty"] <= 0 or r["list"] < min_list_eur:
            continue
        entry = models.get(r["model"])
        if not isinstance(entry, dict):
            continue
        usd = None
        if r["service"] == "Gemini API" and isinstance(entry.get("geminiApiRates"), dict):
            usd = entry["geminiApiRates"].get(r["kind"])
        if usd is None:
            usd = entry.get(r["kind"])
        if not isinstance(usd, (int, float)) or usd <= 0:
            continue
        ratios.append(r["list"] / r["qty"] * 1_000_000.0 / float(usd))
    return ratios


def compute_eur_rate(rows: list[dict], pricing_cfg: dict | None, min_list_eur: float = 1.0) -> dict:
    """EUR per 1 USD: invoice unit price (EUR per 1M tokens) / catalog USD price, global/API text input & output.

    The billing account can use a different exchange rate each month, so the rate is computed per source file;
    the proposal uses the LAST file passed on the command line (give files in chronological order).
    """
    if not pricing_cfg:
        return {"rate": None, "samples": 0, "note": "pricing file not found"}
    models = pricing_cfg.get("models") or {}
    by_source: dict[str, dict] = {}
    for src in dict.fromkeys(r["source"] for r in rows):
        ratios = _eur_samples([r for r in rows if r["source"] == src], models, min_list_eur)
        if ratios:
            by_source[src] = {"rate": round(statistics.median(ratios), 4), "samples": len(ratios),
                              "min": round(min(ratios), 4), "max": round(max(ratios), 4)}
    if not by_source:
        return {"rate": None, "samples": 0, "note": "no model with a catalog price matched"}
    last = list(by_source.values())[-1]
    return {**last, "bySource": by_source}


def build_proposal(rows: list[dict], pricing_cfg: dict | None, min_list_eur: float, sources: list[str],
                   warnings: list[str] | None = None) -> dict:
    disc_service, disc_model = compute_discounts(rows, min_list_eur)
    cache = compute_cache_ratios(rows, min_list_eur)
    regional = compute_regional_multiplier(rows, min_list_eur)
    eur = compute_eur_rate(rows, pricing_cfg, min_list_eur)

    billing: dict[str, float] = {}
    if disc_service.get("Vertex AI") is not None:
        billing["vertexBillingCreditDiscountPct"] = round(disc_service["Vertex AI"], 1)
    if disc_service.get("Gemini API") is not None:
        billing["geminiApiBillingCreditDiscountPct"] = round(disc_service["Gemini API"], 1)
    vertex_cache = weighted_service_cache(cache, "Vertex AI")
    if vertex_cache is not None:
        billing["vertexImplicitCacheHitRatioPct"] = round(vertex_cache, 1)
    gemini_cache = weighted_service_cache(cache, "Gemini API")
    if gemini_cache is not None:
        billing["geminiApiImplicitCacheHitRatioPct"] = round(gemini_cache, 1)
    if regional["multiplier"] is not None:
        billing["regionalMultiplierDefault"] = round(regional["multiplier"], 2)
    if eur["rate"] is not None:
        billing["usdToEurRate"] = round(eur["rate"], 3)

    per_model_gemini_cache = {
        key.split("|", 1)[1]: round(v["cachePct"], 1)
        for key, v in cache.items() if key.startswith("Gemini API|") and v["cachePct"] is not None
    }
    notes = list(warnings or [])
    if len({round(v, 0) for k, v in disc_model.items() if v is not None and k.startswith("Gemini API|")}) > 1:
        notes.append("Gemini API discount differs per model: the proposed value is the weighted average.")
    if regional["samples"] and regional["max"] - regional["min"] > 0.03:
        notes.append("Regional multiplier varies across models (>3%): check the details before using the median.")
    if eur.get("samples") and eur["max"] - eur["min"] > 0.03 * eur["rate"]:
        notes.append("EUR rate spread across SKUs is above 3%: the invoice may mix several exchange rates.")
    by_src = (eur.get("bySource") or {}).values()
    if len(by_src) > 1 and max(v["rate"] for v in by_src) - min(v["rate"] for v in by_src) > 0.01 * eur["rate"]:
        notes.append("The EUR rate differs between files (monthly exchange rate): the proposal uses the last file given.")
    if any(v is not None and v < 0 for v in disc_service.values()):
        notes.append("A negative credit discount was computed (other savings are positive): check the CSV columns.")
    if not rows:
        notes.append("No Vertex AI / Gemini API token rows found: check that the CSV is grouped by SKU.")
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "billingSettings": billing,
        "geminiApiCacheHitRatioByModelPct": per_model_gemini_cache,
        "details": {
            "creditDiscountPctByService": disc_service,
            "creditDiscountPctByModel": disc_model,
            "cacheByServiceModel": cache,
            "regionalMultiplier": regional,
            "usdToEurRate": eur,
        },
        "notes": notes,
        "howToApply": [
            "Pricing & Rates > Billing settings: enter the values under billingSettings, then Save settings.",
            "Pricing & Rates > click a model > 'Gemini API (AI Studio) cache hit': enter the per-model values.",
            "Run a new scan so costs are recalculated, then compare with the invoice.",
        ],
        "applied": False,
    }


def render_report(p: dict) -> str:
    lines = ["PROPOSTA DI CALIBRAZIONE (nessuna impostazione è stata modificata)", ""]
    labels = {
        "vertexBillingCreditDiscountPct": "Sconto crediti Vertex AI (%)",
        "geminiApiBillingCreditDiscountPct": "Sconto crediti Gemini API (%)",
        "vertexImplicitCacheHitRatioPct": "Cache implicita Vertex (%)",
        "geminiApiImplicitCacheHitRatioPct": "Cache Gemini API, media (%)",
        "regionalMultiplierDefault": "Moltiplicatore regionale (x)",
        "usdToEurRate": "Cambio USD -> EUR (EUR per 1 USD)",
    }
    for key, label in labels.items():
        if key in p["billingSettings"]:
            lines.append(f"  {label:<42} {p['billingSettings'][key]}")
    if p["geminiApiCacheHitRatioByModelPct"]:
        lines.append("")
        lines.append("  Cache Gemini API per modello (%):")
        for model, pct in sorted(p["geminiApiCacheHitRatioByModelPct"].items()):
            lines.append(f"    {model:<40} {pct}")
    if p["notes"]:
        lines.append("")
        lines.extend(f"  ! {n}" for n in p["notes"])
    lines.append("")
    lines.extend(f"  {i + 1}. {step}" for i, step in enumerate(p["howToApply"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv", nargs="+", help="Cloud Billing CSV export(s), grouped by SKU")
    ap.add_argument("--pricing", default="data/models_pricing_config.json", help="local pricing file (for the EUR rate)")
    ap.add_argument("--out", default="data/calibration_proposal.json", help="where to write the proposal (keep under data/)")
    ap.add_argument("--min-list-eur", type=float, default=1.0, help="ignore groups with list cost below this (EUR)")
    args = ap.parse_args(argv)

    paths = [Path(c) for c in args.csv]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print("File non trovato: " + ", ".join(missing), file=sys.stderr)
        return 2
    pricing_cfg = None
    pricing_path = Path(args.pricing)
    if pricing_path.is_file():
        try:
            pricing_cfg = json.loads(pricing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pricing_cfg = None

    out_path = Path(args.out)
    if out_path.resolve() == pricing_path.resolve() or out_path.resolve() in [p.resolve() for p in paths]:
        print("--out non può coincidere con il file dei prezzi o con un CSV di input.", file=sys.stderr)
        return 2
    if out_path.exists():
        print(f"Attenzione: {out_path} esiste già e verrà sovrascritto.", file=sys.stderr)
    warnings: list[str] = []
    rows = load_rows(paths, warnings)
    proposal = build_proposal(rows, pricing_cfg, args.min_list_eur, [p.name for p in paths], warnings)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
    print(render_report(proposal))
    print(f"\nDettagli salvati in {out_path} (cartella ignorata da Git).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
