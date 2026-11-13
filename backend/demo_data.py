#!/usr/bin/env python3
"""Deterministic generator of INVENTED demo data for JanusTower (fictitious company "Acme Corp").

It reproduces the full shape of the ``/api/scan`` payload (``summary``, ``timeline``, ``projects``, ``sync``,
``periodRange``, ``scanMode``...) so that every view of the app can be shown without touching Google Cloud:
README screenshots and the app's demo mode (``JANUSTOWER_DEMO``, see backend/demo_mode.py), which loads this file at startup.

Everything here is made up. There are no real Google Cloud identifiers, no real e-mail addresses, no real
project numbers and no secrets: users live on the reserved domains ``example.com`` / ``example.org``
(contractors on ``contractor.example.net``), service accounts use invented ``acme-*`` project ids, API keys
and client ids are obvious placeholders. Costs are internally consistent (daily series -> models ->
credentials -> users -> projects -> summary) and computed with deterministic arithmetic.

Determinism: the output depends ONLY on ``(days, seed, reference_date)``. The wall clock is never read, and
the pseudo random numbers come from SHA-256 (stable across Python versions and platforms).

Usage:
  python backend/demo_data.py --output /path/outside/the/repo/demo_scan.json [--days 30] [--seed N]
                            [--reference-date YYYY-MM-DD] [--auth-output /path/outside/the/repo/demo_auth.json]
                            [--no-enrich]

Standard library only. The optional enrichment step reuses the project's own backend (the same code that
the app runs on every cached payload) to derive the security posture, data residency, FinOps and Gemini
Enterprise sections; without it the payload is still valid input for ``slice_cached_payload_for_days``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULT_SEED = 20261104
DEFAULT_REFERENCE_DATE = "2026-11-04"
COMPANY = "Acme Corp"
DEMO_ACCOUNT = "demo.admin@example.com"
FAKE_USD_TO_EUR = 0.92

# ---------------------------------------------------------------------------------------------------------
# Deterministic pseudo random numbers (SHA-256 based, no `random` module state, no wall clock)
# ---------------------------------------------------------------------------------------------------------


class _Rnd:
    def __init__(self, *parts) -> None:
        self._seed = ":".join(str(p) for p in parts)
        self._n = 0

    def random(self) -> float:
        digest = hashlib.sha256(f"{self._seed}:{self._n}".encode()).digest()
        self._n += 1
        return int.from_bytes(digest[:8], "big") / 2.0**64

    def jitter(self, spread: float) -> float:
        """Multiplier in [1-spread, 1+spread]."""
        return 1.0 - spread + 2.0 * spread * self.random()


# ---------------------------------------------------------------------------------------------------------
# Catalogs (invented people, real public Google model names with plausible list prices in USD / 1M tokens)
# ---------------------------------------------------------------------------------------------------------

PEOPLE = [
    "anna.rossi", "marco.bianchi", "giulia.verdi", "luca.ferrari", "sara.conti", "paolo.romano",
    "elena.gallo", "davide.costa", "chiara.fontana", "matteo.greco", "francesca.bruno", "andrea.marino",
    "laura.rizzo", "simone.lombardi", "valentina.moretti", "roberto.barbieri", "martina.ricci",
    "fabio.deluca", "silvia.mancini", "claudio.colombo", "irene.giordano", "nicola.esposito",
    "alessia.caruso", "stefano.serra", "monica.vitale", "tommaso.parisi", "federica.sanna",
    "gabriele.longo", "beatrice.pellegrini", "riccardo.fabbri",
]
CONTRACTORS = ["tom.becker", "iris.larsen", "noah.dubois", "maya.novak", "leo.martin"]


def _person(i: int) -> str:
    domain = "example.org" if i % 7 == 6 else "example.com"
    return f"{PEOPLE[i % len(PEOPLE)]}@{domain}"


def _contractor(i: int) -> str:
    return f"{CONTRACTORS[i % len(CONTRACTORS)]}@contractor.example.net"


# model id -> (input, output) USD per 1M tokens; cached input is billed at 25% of the input price
MODEL_PRICES = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash-001": (0.10, 0.40),
    "text-embedding-005": (0.025, 0.0),
    "claude-sonnet-4": (3.0, 15.0),
}
SVC_VERTEX = "aiplatform.googleapis.com"
SVC_GEMINI = "generativelanguage.googleapis.com"
SVC_DISCOVERY = "discoveryengine.googleapis.com"
SVC_COMPANION = "cloudaicompanion.googleapis.com"
# cost of one interaction on the managed (pool) products, invented but in the right order of magnitude
POOL_RATES = {"assist": 0.0041, "search": 0.0015, "code": 0.0014, "nb": 0.0030}
POOL_MODEL = {"assist": "gemini-enterprise-assistant", "search": "gemini-enterprise-assistant",
              "code": "gemini-code-assist", "nb": "notebooklm-enterprise"}
POOL_SERVICE = {"assist": SVC_DISCOVERY, "search": SVC_DISCOVERY, "code": SVC_COMPANION, "nb": SVC_DISCOVERY}
POOL_TOKENS = {"assist": (1800, 350), "search": (300, 60), "code": (600, 150), "nb": (2500, 500)}

API_CATALOG = {
    SVC_VERTEX: ("Vertex AI API", "Vertex AI", "🧠", "Vertex AI platform (Gemini models, Model Garden, Agent Engine, endpoints)"),
    SVC_GEMINI: ("Gemini API (AI Studio)", "Google AI Studio", "✨", "Direct Gemini API / Google AI Studio (often invoked via API Key without IAM/VPC-SC)"),
    SVC_DISCOVERY: ("Discovery Engine / Gemini Enterprise", "Gemini Enterprise", "🔍", "Enterprise engine for Agentspace, Vertex AI Search, NotebookLM Enterprise and RAG DataStores"),
    SVC_COMPANION: ("Gemini Code Assist", "Developer Tools", "💻", "License management and telemetry for Gemini Code Assist developers"),
    "modelarmor.googleapis.com": ("Model Armor", "AI Security", "🛡️", "Inline Prompt Injection, Jailbreak, RAI Filter, DLP/SDP and Malicious URI protection for LLMs and Agents"),
    "dlp.googleapis.com": ("Sensitive Data Protection", "AI Security", "🔒", "Inspection, classification and de-identification of sensitive data"),
    "dialogflow.googleapis.com": ("Dialogflow CX", "Conversational AI", "💬", "Enterprise conversational agents, LLM Generative Playbooks, voicebots and chatbots on Vertex AI"),
    "notebooks.googleapis.com": ("Notebooks / Colab Enterprise", "Vertex AI Notebooks", "📓", "Managed JupyterLab instances on Vertex AI Workbench for Data Science and ML"),
    "agentregistry.googleapis.com": ("Agent Registry", "Agent Governance", "🗂️", "Centralized Gemini Enterprise Agent Platform registry for discovery and governance of AI Agents, MCP Servers and Skills"),
    "iap.googleapis.com": ("Identity-Aware Proxy", "AI Security", "🚪", "Zero-trust access to applications and resources"),
}

BUCKET_INT_KEYS = (
    "requests", "inferenceRequests", "vertexInferenceRequests", "systemRequests", "vertexRequests",
    "geminiApiRequests", "ok200", "ok200Inference", "errors429", "tokens", "inputTokens", "outputTokens",
    "cachedTokens", "thinkingTokens",
)
BUCKET_COST_KEYS = ("costUsd", "vertexCostUsd", "geminiCostUsd", "otherAiCostUsd")

IAM_PERMISSIONS = [
    "resourcemanager.projects.get", "serviceusage.services.list", "serviceusage.apiKeys.list",
    "monitoring.timeSeries.list", "logging.logEntries.list", "iam.serviceAccounts.list",
    "aiplatform.endpoints.list", "aiplatform.reasoningEngines.list", "dialogflow.agents.list",
    "discoveryengine.engines.list", "modelarmor.floorSettings.get", "modelarmor.templates.list",
]
METHODS = {
    SVC_VERTEX: ["google.cloud.aiplatform.v1.PredictionService.GenerateContent",
                 "google.cloud.aiplatform.v1.PredictionService.StreamGenerateContent"],
    SVC_GEMINI: ["google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent",
                 "google.ai.generativelanguage.v1beta.GenerativeService.StreamGenerateContent"],
    "embed": ["google.cloud.aiplatform.v1.PredictionService.Predict"],
}
SYSTEM_METHODS = ["google.cloud.aiplatform.v1.EndpointService.ListEndpoints",
                  "google.cloud.aiplatform.v1.ModelService.ListModels"]

# ---------------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------------


def _empty_bucket() -> dict:
    b: dict = {k: 0 for k in BUCKET_INT_KEYS}
    b.update({k: 0.0 for k in BUCKET_COST_KEYS})
    return b


def _add_bucket(dst: dict, src: dict) -> None:
    for k in BUCKET_INT_KEYS:
        dst[k] += src.get(k, 0)
    for k in BUCKET_COST_KEYS:
        dst[k] = round(dst[k] + src.get(k, 0.0), 4)


def _iso(ref: date, days_ago: int, hour: int = 9, minute: int = 0) -> str:
    return f"{(ref - timedelta(days=days_ago)).isoformat()}T{hour:02d}:{minute:02d}:00Z"


# ---------------------------------------------------------------------------------------------------------
# Traffic simulation: one "stream" = one model used through one credential (or one pool user)
# ---------------------------------------------------------------------------------------------------------

WEEKDAY_FACTOR = [1.0, 1.06, 1.10, 1.05, 0.92]


def _day_factor(st: dict, d: date, i: int, n: int, rnd: _Rnd) -> float:
    f = WEEKDAY_FACTOR[d.weekday()] if d.weekday() < 5 else float(st.get("wk", 0.18)) * rnd.jitter(0.3)
    f *= 1.0 + float(st.get("ramp", 0.0)) * (i / max(1, n - 1))
    start = float(st.get("start", 0.0))
    if start > 0:
        pos = i / max(1, n - 1)
        if pos < start:
            return 0.0
        f *= min(1.0, 0.25 + (pos - start) / 0.12)
    f *= st.get("spikes", {}).get(n - 1 - i, 1.0)
    f *= rnd.jitter(0.15)
    if i == n - 1:  # the reference day is still in progress
        f *= 0.55
    return max(0.0, f)


def _simulate_llm_day(st: dict, f: float, rnd: _Rnd, is_burst: bool) -> tuple[dict, dict]:
    calls = int(round(st["calls"] * f))
    svc = st["svc"]
    is_vertex = svc == SVC_VERTEX
    is_gemini = svc == SVC_GEMINI
    sys_rate = float(st.get("sys", 0.04))
    sysr = int(round(calls * sys_rate)) if calls else 0
    e429_rate = float(st.get("e429", 0.0)) * (8.0 if is_burst else 1.0)
    e429 = min(calls, int(round(calls * e429_rate * (0.5 + 1.5 * rnd.random())))) if calls else 0
    other_err = int(round(calls * float(st.get("err", 0.002)))) if calls else 0
    ok_inf = max(0, calls - e429 - other_err)
    avg_in, avg_out = st["tin"], st["tout"]
    tin = int(ok_inf * avg_in * rnd.jitter(0.12))
    tout = int(ok_inf * avg_out * rnd.jitter(0.12))
    think = int(tout * float(st.get("think", 0.0)))
    cached = int(tin * float(st.get("cache", 0.0)))
    p_in, p_out = MODEL_PRICES[st["model"]]
    free = bool(st.get("free"))
    gross = 0.0 if free else (tin * p_in + (tout + think) * p_out) / 1e6
    cost = 0.0 if free else ((tin - cached) * p_in + cached * p_in * 0.25 + (tout + think) * p_out) / 1e6
    cost = round(cost, 4)
    saved = round(max(0.0, gross - cost), 4)
    reqs = calls + sysr
    b = _empty_bucket()
    b.update({
        "requests": reqs, "inferenceRequests": calls, "vertexInferenceRequests": calls if is_vertex else 0,
        "systemRequests": sysr, "vertexRequests": reqs if is_vertex else 0,
        "geminiApiRequests": reqs if is_gemini else 0,
        "ok200": max(0, reqs - e429 - other_err), "ok200Inference": ok_inf, "errors429": e429,
        "tokens": tin + tout + think, "inputTokens": tin, "outputTokens": tout, "cachedTokens": cached,
        "thinkingTokens": think, "costUsd": cost,
        "vertexCostUsd": cost if is_vertex else 0.0, "geminiCostUsd": cost if is_gemini else 0.0,
        "otherAiCostUsd": 0.0 if (is_vertex or is_gemini) else cost,
    })
    extra = {"saved": saved, "other_err": other_err, "reqBytes": tin * 4 if is_gemini else 0,
             "respBytes": (tout + think) * 4 if is_gemini else 0}
    return b, extra


def _simulate_pool_day(st: dict, f: float, rnd: _Rnd) -> tuple[dict, dict]:
    counts = {k: int(round(st.get(k, 0) * f * rnd.jitter(0.2))) for k in POOL_RATES}
    total = sum(counts.values())
    tin = sum(counts[k] * POOL_TOKENS[k][0] for k in counts)
    tout = sum(counts[k] * POOL_TOKENS[k][1] for k in counts)
    cost = round(sum(counts[k] * POOL_RATES[k] for k in counts), 4)
    b = _empty_bucket()
    b.update({"requests": total, "inferenceRequests": total, "ok200": total, "ok200Inference": total,
              "tokens": tin + tout, "inputTokens": tin, "outputTokens": tout, "costUsd": cost,
              "otherAiCostUsd": cost})
    return b, {"counts": counts}


# ---------------------------------------------------------------------------------------------------------
# Resource builders (shape of `deployedAiResources`)
# ---------------------------------------------------------------------------------------------------------


def _console(path: str, pid: str) -> str:
    return f"https://console.cloud.google.com/{path}?project={pid}"


def _res(rtype: str, label: str, name: str, rid: str, loc: str, ref: date, age: int, pid: str, path: str, details: str, **extra) -> dict:
    r = {
        "resourceType": rtype, "typeLabel": label, "displayName": name, "resourceId": rid, "location": loc,
        "createTime": _iso(ref, age), "updateTime": _iso(ref, max(0, age - 9)),
        "consoleUrl": _console(path, pid), "details": details,
    }
    r.update(extra)
    return r


def _reasoning_engine(name, loc, ref, age, pid, desc=""):
    return _res("REASONING_ENGINE", "🤖 Agente ADK / Reasoning Engine", name, name.lower().replace(" ", "-"), loc, ref, age, pid,
                "vertex-ai/reasoning-engines", "Framework: Google ADK (Python 3.12)" + (f" — {desc}" if desc else ""),
                framework="Google ADK", pythonVersion="3.12", description=desc)


def _endpoint(name, loc, ref, age, pid, models=1, private=False):
    return _res("VERTEX_ENDPOINT", "🚀 Vertex Online Endpoint", name, name, loc, ref, age, pid, "vertex-ai/online-prediction/endpoints",
                f"{models} deployed models" + (" • Private Service Connect (PSC) enabled" if private else ""), deployedModelsCount=models, deployedModels=[f"{name}-model-v{k + 1}" for k in range(models)])


def _colab_runtime(name, user, loc, ref, age, pid, state="RUNNING", machine="n1-standard-8"):
    return _res("COLAB_ENTERPRISE_RUNTIME", "⚡ Colab Enterprise Active Runtime", name, name, loc, ref, age, pid,
                "vertex-ai/colab/runtimes", f"User: {user} • State: {state} • {machine}",
                runtimeUser=user, runtimeState=state, machineType=machine, healthState="HEALTHY")


def _colab_template(name, loc, ref, age, pid, machine="n1-standard-4"):
    return _res("COLAB_ENTERPRISE_TEMPLATE", "📓 Colab Enterprise Runtime Template", name, name, loc, ref, age, pid,
                "vertex-ai/colab/runtime-templates", f"Macchina: {machine} • Idle Shutdown: 3600s", machineType=machine)


def _colab_job(name, user, loc, ref, age, pid, state):
    return _res("COLAB_EXECUTION_JOB", "🗓️ Colab Scheduled Execution Job", name, f"{name}-{age:03d}", loc, ref, age, pid,
                "vertex-ai/colab/execution-jobs", f"Stato: {state} • Identity: {user} • Eseguito: {_iso(ref, age)[:16]}",
                runtimeUser=user, ownerEmail=user, state=state, jobState=state, executionIdentity=user)


def _workbench(name, loc, ref, age, pid, user):
    return _res("WORKBENCH_NOTEBOOK", "💻 Vertex AI Workbench Instance", name, name, loc, ref, age, pid,
                "vertex-ai/workbench/instances", "n1-standard-8 • ACTIVE", state="ACTIVE", machineType="n1-standard-8", ownerEmail=user)


def _simple_res(rtype, label, name, loc, ref, age, pid, path, details, **extra):
    return _res(rtype, label, name, name, loc, ref, age, pid, path, details, **extra)


# ---------------------------------------------------------------------------------------------------------
# Project specifications (all invented)
# ---------------------------------------------------------------------------------------------------------


def _llm(key, model, svc, cred, loc, calls, tin, tout, **kw) -> dict:
    d = {"kind": "llm", "key": key, "model": model, "svc": svc, "cred": cred, "loc": loc, "calls": calls, "tin": tin, "tout": tout}
    d.update(kw)
    return d


def _pool(user, **kw) -> dict:
    d = {"kind": "pool", "key": f"pool:{user}", "user": user}
    d.update(kw)
    return d


def _sa(slug, pid, unique_id, name, keys=0, old_keys=0, disabled=False, default=False, number="555000000001") -> dict:
    email = f"{number}-compute@developer.gserviceaccount.com" if default else f"{slug}@{pid}.iam.gserviceaccount.com"
    return {"slug": slug, "email": email, "uniqueId": unique_id, "name": name, "keys": keys, "oldKeys": old_keys,
            "disabled": disabled, "default": default}


def _key(uid_n, name, owner, targets, age, status="ACTIVE", ai_studio=False) -> dict:
    return {"uid": f"00000000-0000-4000-8000-{uid_n:012d}", "name": name, "owner": owner, "targets": targets,
            "age": age, "status": status, "aiStudio": ai_studio}


def _project_specs(ref: date) -> list[dict]:
    antigravity_client = "000000000001-demoantigravity.apps.googleusercontent.com"
    wl_user = "oauth-workload:000000000001"
    agentspace_users = [_person(i) for i in range(24)] + [_contractor(i) for i in range(3)]
    devtools_users = [_person(i) for i in range(4, 16)]
    ml_users = [_person(i) for i in (1, 2, 3, 5, 8, 9)]
    ds_apps = ["acme-intranet-assistant", "acme-hr-search"]
    ds_ids = ["acme-drive-connector", "acme-wiki-connector", "acme-jira-connector", "acme-hr-policies-docs", "acme-notebooklm-store", "legacy-sharepoint-archive"]

    specs: list[dict] = []

    # 1. finance prod: Vertex AI in Milan, Model Armor on, one old exported SA key
    pid = "acme-finance-prod"
    specs.append({
        "pid": pid, "name": "Acme Finance (Prod)", "number": "555000000101", "age": 520, "budget": 1500.0, "latency": 1620.0,
        "streams": [
            _llm("fin-pro", "gemini-2.5-pro", SVC_VERTEX, f"serviceaccount:{9990000000001}", "europe-west8", 1800, 3200, 520, think=0.35, cache=0.35, err=0.0, ramp=0.25),
            _llm("fin-flash", "gemini-2.5-flash", SVC_VERTEX, f"serviceaccount:{9990000000001}", "europe-west8", 6000, 1400, 220, cache=0.4, err=0.0),
            _llm("fin-embed", "text-embedding-005", SVC_VERTEX, f"serviceaccount:{9990000000002}", "europe-west1", 9000, 420, 0, cache=0.0, sys=0.01, err=0.0),
            _llm("fin-lite", "gemini-2.5-flash-lite", SVC_VERTEX, f"apikey:{_key(1, '', '', [], 0)['uid']}", "europe-west8", 1200, 900, 160, cache=0.2, err=0.0),
        ],
        "sas": [_sa("finance-agent", pid, "9990000000001", "Finance Agent Runtime"), _sa("finance-etl", pid, "9990000000002", "Finance ETL", keys=1, old_keys=1),
                _sa("", pid, "9990000000003", "Compute Engine default service account", default=True)],
        "keys": [_key(1, "AI Reporting", _person(0), ["aiplatform.googleapis.com"], 70)],
        "apis": [SVC_VERTEX, "modelarmor.googleapis.com", "dlp.googleapis.com", "agentregistry.googleapis.com", "iap.googleapis.com"],
        "ma": "active", "ma_threats": (2, 2, 120),
        "resources": [
            _reasoning_engine("finance-agent-engine-20261001", "europe-west8", ref, 34, pid, "Expense reconciliation and control"),
            _reasoning_engine("finance-agent-engine-20260901", "europe-west8", ref, 64, pid, "Expense reconciliation and control"),
            _endpoint("fraud-scorer", "europe-west8", ref, 200, pid, private=True),
            _simple_res("DLP_INSPECT_TEMPLATE", "🛡️ Sensitive Data Protection (DLP Template)", "pii-redaction-template", "europe-west1", ref, 120, pid, "security/dlp", "PII redaction template"),
            _simple_res("AGENT_REGISTRY_AGENT", "🗂️ Agent Registry (Governed Agent)", "finance-agent-registry-entry", "europe-west8", ref, 30, pid, "agent-registry", "Registered agent"),
        ],
        "features": [("vertex_gemini_inference", "Vertex AI Online Inference (Gemini / Model Garden)", "Vertex AI LLM Inference", "✨", "fin-"),
                     ("vertex_agent_engine", "Vertex AI Agent Engine (Reasoning Engines / ADK)", "Gemini Agent Platform", "🤖", None)],
    })

    # 2. ML lab: Antigravity through a shared OAuth client (expensive), notebooks, non-EU endpoint, no Model Armor
    pid = "acme-ml-lab"
    ml_streams = [
        _llm("ml-antigrav", "gemini-2.5-pro", SVC_VERTEX, f"oauth2:{antigravity_client}", "global", 1150, 9000, 700, think=0.5, cache=0.5, e429=0.0003, ramp=0.4, wk=0.35),
        _llm("ml-flash", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000011", "europe-west4", 2200, 1800, 300, think=0.2, cache=0.3, e429=0.0004),
        _llm("ml-claude", "claude-sonnet-4", SVC_VERTEX, "serviceaccount:9990000000011", "us-east5", 160, 4200, 600, cache=0.0, e429=0.0005),
        _llm("ml-key", "gemini-2.0-flash-001", SVC_VERTEX, f"apikey:{_key(2, '', '', [], 0)['uid']}", "europe-west4", 500, 1100, 200, cache=0.1, err=0.0),
    ]
    specs.append({
        "pid": pid, "name": "Acme ML Lab", "number": "555000000102", "age": 410, "budget": 1200.0, "latency": 2480.0,
        "streams": ml_streams,
        "oauth": [{"client": antigravity_client, "owner": wl_user, "display": "OAuth Workload Vertex AI (000000000001)", "tool": "Antigravity IDE (Vertex AI OAuth)"}],
        "sas": [_sa("ml-trainer", pid, "9990000000011", "ML Trainer", keys=2, old_keys=1), _sa("ml-notebooks", pid, "9990000000012", "Notebook Runner", disabled=True)],
        "keys": [_key(2, "Notebook Quick Key", ml_users[0], ["aiplatform.googleapis.com"], 60)],
        "apis": [SVC_VERTEX, "notebooks.googleapis.com", "dlp.googleapis.com"],
        "ma": "off",
        "users": [{"email": u, "type": "INTERNAL_USER"} for u in ml_users] + [{"email": wl_user, "type": "OAUTH_WORKLOAD"}],
        "resources": [
            _endpoint("custom-ranker-us", "us-central1", ref, 150, pid, 2),
            _endpoint("idle-test-endpoint", "europe-west4", ref, 90, pid, 0),
            _simple_res("VECTOR_SEARCH_ENDPOINT", "📡 Vector Search Index Endpoint", "ml-lab-vs-endpoint", "europe-west4", ref, 100, pid, "vertex-ai/vector-search", "Endpoint pubblico"),
            _simple_res("VERTEX_TUNING_JOB", "🎯 Fine-Tuning LLM Job (SFT)", "summarizer-sft-v3", "europe-west4", ref, 12, pid, "vertex-ai/training", "Stato: JOB_STATE_SUCCEEDED"),
            _colab_template("gpu-template-a100", "europe-west4", ref, 140, pid, "a2-highgpu-1g"),
            _colab_runtime("runtime-" + ml_users[0].split("@")[0], ml_users[0], "europe-west4", ref, 6, pid),
            _colab_runtime("runtime-" + ml_users[2].split("@")[0], ml_users[2], "europe-west4", ref, 21, pid, state="RUNNING", machine="n1-standard-16"),
            _workbench("workbench-research-01", "europe-west4", ref, 75, pid, ml_users[3]),
        ] + [_colab_job("nightly-feature-refresh", ml_users[1], "europe-west4", ref, k, pid, "JOB_STATE_FAILED" if k in (9, 17) else "JOB_STATE_SUCCEEDED") for k in range(1, 22)]
        + [_colab_job("weekly-model-eval", ml_users[4], "europe-west4", ref, k * 7, pid, "JOB_STATE_SUCCEEDED") for k in range(1, 5)],
        "features": [("vertex_colab_enterprise", "Colab Enterprise & Vertex AI Notebooks Runtime", "Vertex AI Notebooks", "📓", None, 310)],
    })

    # 3. Agentspace / Gemini Enterprise with many users, NotebookLM with 18 users
    pid = "acme-agentspace"
    pool_streams = []
    for idx, u in enumerate(agentspace_users):
        pool_streams.append(_pool(u, assist=22 + (idx * 7) % 40, search=14 + (idx * 5) % 25, nb=(6 + idx % 9) if idx < 18 else 0,
                                  engines=[ds_apps[0]] + ([ds_apps[1]] if idx % 3 == 0 else []),
                                  datastores=ds_ids[:3] + (["acme-notebooklm-store"] if idx < 18 else []), wk=0.12))
    pool_streams.append(_llm("as-conn", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000021", "europe-west1", 320, 1500, 240, cache=0.3, err=0.0))
    specs.append({
        "pid": pid, "name": "Acme Gemini Enterprise", "number": "555000000103", "age": 300, "budget": 600.0, "latency": 1980.0,
        "streams": pool_streams,
        "sas": [_sa("agentspace-connector", pid, "9990000000021", "Connector Sync")],
        "keys": [],
        "apis": [SVC_DISCOVERY, SVC_VERTEX, "modelarmor.googleapis.com"],
        "ma": "partial",
        "users": [{"email": u, "type": "EXTERNAL_USER" if "contractor" in u else "INTERNAL_USER"} for u in agentspace_users],
        "resources": [
            _simple_res("AGENTSPACE_APP", "✨ Google Agentspace / Enterprise App", ds_apps[0], "eu", ref, 280, pid, "gen-app-builder/engines",
                        "App: INTRANET • Tier: ENTERPRISE • 4 DataStores collegati • Org: Acme Corp", solutionType="SOLUTION_TYPE_SEARCH",
                        appType="INTRANET", industryVertical="GENERIC", searchTier="ENTERPRISE", searchAddOns=["LLM"],
                        dataStoreIds=ds_ids[:3] + ["acme-notebooklm-store"], companyName=COMPANY, enabledModels=["gemini-2.5-pro", "gemini-2.5-flash"], defaultModel="gemini-2.5-pro"),
            _simple_res("AGENTSPACE_APP", "✨ Google Agentspace / Enterprise App", ds_apps[1], "eu", ref, 190, pid, "gen-app-builder/engines",
                        "App: INTRANET • Tier: ENTERPRISE • 1 DataStore collegato • Org: Acme Corp", solutionType="SOLUTION_TYPE_SEARCH",
                        appType="INTRANET", industryVertical="GENERIC", searchTier="ENTERPRISE", searchAddOns=["LLM"],
                        dataStoreIds=["acme-hr-policies-docs"], companyName=COMPANY, enabledModels=["gemini-2.5-flash"], defaultModel="gemini-2.5-flash"),
        ] + [
            _simple_res("AGENTSPACE_DATASTORE", "🗄️ Agentspace / Discovery DataStore", d, "eu", ref, 250 - 17 * k, pid, "gen-app-builder/data-stores",
                        "Content: CONTENT_REQUIRED", contentConfig="CONTENT_REQUIRED")
            for k, d in enumerate(ds_ids)
        ],
        "features": [("svc_agentspace_assistant", "Gemini Enterprise Assistant", "Gemini Enterprise", "✨", "assist"),
                     ("svc_notebooklm_enterprise", "NotebookLM Enterprise", "Gemini Enterprise", "📓", "nb")],
    })

    # 4. Support bot: bursts of 429, Model Armor with real violations, zombie builds, audit-log blindness
    pid = "acme-support-bot"
    specs.append({
        "pid": pid, "name": "Acme Support Bot", "number": "555000000104", "age": 150, "budget": 500.0, "latency": 980.0,
        "streams": [
            _llm("sb-flash", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000031", "europe-west1", 9500, 1500, 260, cache=0.45, e429=0.012, start=0.28, ramp=0.5,
                 spikes={6: 2.4, 5: 1.8}),
            _llm("sb-lite", "gemini-2.5-flash-lite", SVC_VERTEX, "serviceaccount:9990000000031", "europe-west1", 5200, 700, 110, cache=0.3, e429=0.004, start=0.28),
            _llm("sb-unattr", "gemini-2.5-flash", SVC_VERTEX, "system:unattributed-audit-logs-disabled", "europe-west1", 420, 1300, 200, cache=0.0),
        ],
        "sas": [_sa("support-bot-runtime", pid, "9990000000031", "Support Bot Runtime")],
        "keys": [_key(4, "Support Widget (web)", _person(11), ["aiplatform.googleapis.com"], 40)],
        "apis": [SVC_VERTEX, "modelarmor.googleapis.com", "dialogflow.googleapis.com"],
        "ma": "active", "ma_threats": (46, 37, 2300),
        "resources": [
            _reasoning_engine("support-bot-agent-20261020", "europe-west1", ref, 15, pid, "Risposte di primo livello"),
            _reasoning_engine("support-bot-agent-20261006", "europe-west1", ref, 29, pid, "Risposte di primo livello"),
            _reasoning_engine("support-bot-agent-20260922", "europe-west1", ref, 43, pid, "Risposte di primo livello"),
            _simple_res("DIALOGFLOW_CX_AGENT", "💬 Dialogflow CX Generative Agent", "support-triage-agent", "europe-west1", ref, 100, pid, "dialogflow/cx", "Playbook generativo"),
        ],
        "features": [("vertex_gemini_inference", "Vertex AI Online Inference (Gemini / Model Garden)", "Vertex AI LLM Inference", "✨", "sb-"),
                     ("vertex_agent_engine", "Vertex AI Agent Engine (Reasoning Engines / ADK)", "Gemini Agent Platform", "🤖", None)],
    })

    # 5. AI Studio sandbox (Gemini Developer API with API keys, 429 heavy, unrestricted keys, ghost key)
    pid = "acme-aistudio-sandbox"
    specs.append({
        "pid": pid, "name": "Acme AI Studio Sandbox", "number": "555000000105", "age": 260, "budget": 150.0, "latency": 1340.0, "aistudio": True,
        "streams": [
            _llm("as-flash", "gemini-2.5-flash", SVC_GEMINI, f"apikey:{_key(5, '', '', [], 0)['uid']}", "global", 1800, 2100, 330, think=0.25, cache=0.2, e429=0.03, wk=0.6, err=0.004),
            _llm("as-pro", "gemini-2.5-pro", SVC_GEMINI, f"apikey:{_key(6, '', '', [], 0)['uid']}", "global", 260, 5200, 700, think=0.4, cache=0.1, e429=0.05, wk=0.5),
            _llm("as-lite", "gemini-2.5-flash-lite", SVC_GEMINI, f"apikey:{_key(7, '', '', [], 0)['uid']}", "global", 900, 800, 120, e429=0.02, wk=0.9),
            _llm("as-ghost", "gemini-2.5-flash", SVC_GEMINI, f"apikey:{_key(8, '', '', [], 0)['uid']}", "global", 140, 1500, 250, e429=0.01),
        ],
        "sas": [],
        "keys": [_key(5, "Prototype Key", _person(3), [SVC_GEMINI], 45, ai_studio=True), _key(6, "Hackathon Key", _contractor(1), [], 130, ai_studio=True),
                 _key(7, "Notebook Demo Key", _person(14), [], 400, ai_studio=True),
                 _key(8, "Old Experiment (deleted)", _person(9), [], 300, status="DELETED_OR_EXTERNAL", ai_studio=True)],
        "apis": [SVC_GEMINI],
        "ma": "off",
        "users": [{"email": _person(3), "type": "INTERNAL_USER"}, {"email": _contractor(1), "type": "EXTERNAL_USER"},
                  {"email": _person(14), "type": "INTERNAL_USER"}, {"email": _person(9), "type": "INTERNAL_USER"}],
        "resources": [],
    })

    # 6. Data platform: embeddings, vector search, idle endpoint
    pid = "acme-data-platform"
    specs.append({
        "pid": pid, "name": "Acme Data Platform", "number": "555000000106", "age": 600, "budget": 400.0, "latency": 640.0,
        "streams": [
            _llm("dp-embed", "text-embedding-005", SVC_VERTEX, "serviceaccount:9990000000041", "europe-west8", 42000, 500, 0, sys=0.005, err=0.0),
            _llm("dp-batch", "gemini-2.5-flash-lite", SVC_VERTEX, "serviceaccount:9990000000041", "europe-west8", 3500, 1900, 180, cache=0.15, wk=0.8, err=0.0),
        ],
        "sas": [_sa("dp-pipeline", pid, "9990000000041", "Data Pipeline"), _sa("", pid, "9990000000042", "Compute Engine default service account", default=True, number="555000000106")],
        "keys": [],
        "apis": [SVC_VERTEX, "dlp.googleapis.com"],
        "ma": "off",
        "resources": [
            _simple_res("VECTOR_SEARCH_INDEX", "🧭 Vertex Vector Search Index", "product-catalog-index", "europe-west8", ref, 220, pid, "vertex-ai/vector-search", "Indice 768 dimensioni"),
            _simple_res("VECTOR_SEARCH_ENDPOINT", "📡 Vector Search Index Endpoint", "product-catalog-endpoint", "europe-west8", ref, 220, pid, "vertex-ai/vector-search", "Endpoint pubblico"),
            _simple_res("RAG_CORPUS", "📚 Vertex AI RAG Corpus", "contracts-corpus", "europe-west8", ref, 160, pid, "vertex-ai/rag", "RAG Corpus"),
            _endpoint("legacy-classifier", "europe-west8", ref, 380, pid, 0),
        ],
    })

    # 7. Marketing GenAI: global/US traffic (GDPR finding) and a cost spike
    pid = "acme-marketing-genai"
    specs.append({
        "pid": pid, "name": "Acme Marketing GenAI", "number": "555000000107", "age": 200, "budget": 300.0, "latency": 2210.0,
        "streams": [
            _llm("mk-flash", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000051", "us-central1", 2600, 2400, 700, think=0.3, cache=0.2, err=0.0, spikes={9: 4.5, 8: 2.2}),
            _llm("mk-global", "gemini-2.5-pro", SVC_VERTEX, "serviceaccount:9990000000051", "global", 240, 3800, 900, think=0.4, cache=0.1, err=0.0),
        ],
        "sas": [_sa("marketing-genai", pid, "9990000000051", "Marketing GenAI Service")],
        "keys": [_key(9, "Campaign Tool", _person(17), ["aiplatform.googleapis.com"], 20)],
        "apis": [SVC_VERTEX],
        "ma": "off",
        "resources": [_endpoint("brand-voice-endpoint", "us-central1", ref, 110, pid, 1, private=True)],
    })

    # 8. Developer tools: Gemini Code Assist
    pid = "acme-devtools"
    dev_streams = [_pool(u, code=120 + (i * 37) % 160, assist=0, wk=0.1) for i, u in enumerate(devtools_users)]
    dev_streams.append(_llm("dt-ci", "gemini-2.5-flash-lite", SVC_VERTEX, "serviceaccount:9990000000081", "europe-west1", 260, 1200, 160, err=0.0))
    specs.append({
        "pid": pid, "name": "Acme Developer Tools", "number": "555000000108", "age": 350, "budget": 250.0, "latency": 410.0,
        "streams": dev_streams,
        "sas": [_sa("devtools-ci", pid, "9990000000081", "Developer Tools CI")],
        "keys": [],
        "apis": [SVC_COMPANION],
        "ma": "off",
        "users": [{"email": u, "type": "INTERNAL_USER"} for u in devtools_users],
        "resources": [],
    })

    # 9. HR assistant: small, EU only, well protected
    pid = "acme-hr-assistant"
    specs.append({
        "pid": pid, "name": "Acme HR Assistant", "number": "555000000109", "age": 120, "budget": 120.0, "latency": 880.0,
        "streams": [_llm("hr-flash", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000061", "europe-west8", 380, 1900, 280, cache=0.5, err=0.0)],
        "sas": [_sa("hr-assistant", pid, "9990000000061", "HR Assistant Runtime")],
        "keys": [],
        "apis": [SVC_VERTEX, "modelarmor.googleapis.com", "dlp.googleapis.com", "agentregistry.googleapis.com", "iap.googleapis.com"],
        "ma": "active", "ma_threats": (0, 0, 60),
        "resources": [_reasoning_engine("hr-assistant-engine", "europe-west8", ref, 60, pid, "Answers questions about HR policies"),
                      _simple_res("DLP_INSPECT_TEMPLATE", "🛡️ Sensitive Data Protection (DLP Template)", "hr-pii-template", "europe-west8", ref, 55, pid, "security/dlp", "PII redaction template"),
                      _simple_res("AGENT_REGISTRY_AGENT", "🗂️ Agent Registry (Governed Agent)", "hr-assistant-registry-entry", "europe-west8", ref, 50, pid, "agent-registry", "Registered agent")],
    })

    # 10. Sales copilot: Agent Registry, MCP server, partner model
    pid = "acme-sales-copilot"
    specs.append({
        "pid": pid, "name": "Acme Sales Copilot", "number": "555000000110", "age": 180, "budget": 350.0, "latency": 1560.0,
        "streams": [
            _llm("sc-flash", "gemini-2.5-flash", SVC_VERTEX, "serviceaccount:9990000000071", "europe-west1", 3800, 2000, 340, think=0.15, cache=0.4, err=0.0),
            _llm("sc-claude", "claude-sonnet-4", SVC_VERTEX, "serviceaccount:9990000000071", "europe-west1", 260, 3600, 500, err=0.0),
        ],
        "sas": [_sa("sales-copilot", pid, "9990000000071", "Sales Copilot Runtime")],
        "keys": [],
        "apis": [SVC_VERTEX, "modelarmor.googleapis.com", "agentregistry.googleapis.com"],
        "ma": "active", "ma_threats": (0, 0, 40),
        "resources": [_reasoning_engine("sales-copilot-engine", "europe-west1", ref, 70, pid, "Preparazione trattative"),
                      _simple_res("AGENT_REGISTRY_MCP", "🔌 Agent Registry MCP Server", "crm-mcp-server", "europe-west1", ref, 65, pid, "agent-registry", "Registered MCP server"),
                      _simple_res("AGENT_REGISTRY_AGENT", "🗂️ Agent Registry (Governed Agent)", "sales-copilot-registry-entry", "europe-west1", ref, 65, pid, "agent-registry", "Registered agent")],
    })

    # 11. No billing: excluded from the scan
    specs.append({"pid": "acme-research-sandbox", "name": "Acme Research Sandbox", "number": "555000000111", "age": 700, "no_billing": True})
    # 12. Free-tier AI Studio project without billing
    specs.append({"pid": "acme-hackathon-2026", "name": "Acme Hackathon 2026", "number": "555000000112", "age": 90, "no_billing": True, "aistudio": True,
                  "streams": [_llm("hk-flash", "gemini-2.5-flash", SVC_GEMINI, f"apikey:{_key(10, '', '', [], 0)['uid']}", "global", 240, 1400, 220, e429=0.06, free=True, wk=0.5)],
                  "keys": [_key(10, "Hackathon Free Key", _contractor(3), [], 30, ai_studio=True)], "apis": [SVC_GEMINI], "ma": "off",
                  "users": [{"email": _contractor(3), "type": "EXTERNAL_USER"}], "sas": [], "resources": []})
    # 13. Access denied (403)
    specs.append({"pid": "acme-partner-portal", "name": "Acme Partner Portal", "number": "555000000113", "age": 450, "denied": True})
    # 14. Not verified (Google throttled the scan)
    specs.append({"pid": "acme-pilot-unverified", "name": "Acme Pilot (not verified)", "number": "555000000114", "age": 30, "unverified": True})
    return specs


# ---------------------------------------------------------------------------------------------------------
# Permissions / Model Armor (shape only)
# ---------------------------------------------------------------------------------------------------------


def _area(aid, title, granted, http, perm, role, detail, status=None, partial=False, status_label=None, extra=None):
    a = {
        "id": aid, "title": title, "label": title, "granted": granted, "partial": partial,
        "status": status or ("GRANTED" if granted else "DENIED"),
        "statusLabel": status_label or ("✅ OK (200)" if granted else f"🔒 Denied ({http})"), "httpCode": http,
        "permission": perm, "requiredRole": role, "detail": detail,
    }
    if extra:
        a.update(extra)
    return a


_DENIED_403 = "🔒 Permission Denied (403)"


def _permissions(full: bool, partial: bool, billing_ok: bool, n_apis: int, n_keys: int, n_sas: int, billing_enabled: bool) -> dict:
    """Same shape and wording as ``build_project_permissions_summary`` of the backend (backend/gcp_discovery.py)."""
    missing = [] if full else (["modelarmor.floorSettings.get", "modelarmor.templates.list"] if partial else list(IAM_PERMISSIONS[1:]))
    granted_list = [p for p in IAM_PERMISSIONS if p not in missing]
    can_mon = "monitoring.timeSeries.list" in granted_list
    res_keys = ["aiplatform.endpoints.list", "aiplatform.reasoningEngines.list", "dialogflow.agents.list", "discoveryengine.engines.list"]
    res_granted = [p for p in res_keys if p in granted_list]
    res_missing = [p for p in res_keys if p not in res_granted]
    res_status = "GRANTED" if len(res_granted) == len(res_keys) else ("PARTIAL" if res_granted else "DENIED")
    ma_keys = ["modelarmor.floorSettings.get", "modelarmor.templates.list"]
    ma_granted = [p for p in ma_keys if p in granted_list]
    ma_status = "GRANTED" if len(ma_granted) == len(ma_keys) else ("PARTIAL" if ma_granted else "DENIED")
    can_ma = len(ma_granted) > 0
    can_su = "serviceusage.services.list" in granted_list
    can_keys = "serviceusage.apiKeys.list" in granted_list
    can_sas = "iam.serviceAccounts.list" in granted_list
    areas = {
        "billingInfo": _area("billingInfo", "Project Billing Status", True, 200, "billing.resourceAssociations.list", "roles/viewer (billing.resourceAssociations.list)",
                             "Billing linked and visible" if billing_enabled else "No Billing linked"),
        "billingCosts": _area("billingCosts", "Actual Billing Account Invoices", billing_ok, 200 if billing_ok else 403,
                              "billing.accounts.get / getSpendingInformation (roles/billing.viewer on Billing Account)", "roles/billing.viewer (on Billing Account)",
                              "Direct Billing Account access enabled" if billing_ok else "🔒 Missing permission on the Billing Account (403) — Costs calculated from Tokens & Cloud Monitoring Metrics",
                              status="GRANTED" if billing_ok else "ESTIMATED_ONLY", partial=not billing_ok,
                              status_label="✅ OK (200)" if billing_ok else "📊 From Metrics"),
        "serviceUsage": _area("serviceUsage", "Enabled APIs & Services", can_su, 200 if can_su else 403, "serviceusage.services.list",
                              "roles/serviceusage.serviceUsageViewer",
                              f"Visible ({n_apis} active AI APIs)" if can_su else f"{_DENIED_403}: unable to verify which APIs are enabled on the project"),
        "monitoring": _area("monitoring", "Calls, Models, Tokens & Costs", can_mon, 200 if can_mon else 403, "monitoring.timeSeries.list", "roles/monitoring.viewer",
                            "Visible: full read of API calls, LLM models, tokens and cost estimates" if can_mon
                            else f"{_DENIED_403}: unable to read calls, models, tokens and costs from Cloud Monitoring"),
        "aiResources": _area("aiResources", "Deployed AI Resources (Vertex / Dialogflow / Agentspace)", len(res_granted) > 0,
                             200 if res_status == "GRANTED" else (206 if res_status == "PARTIAL" else 403), ", ".join(res_keys),
                             "roles/aiplatform.viewer, roles/dialogflow.reader, roles/discoveryengine.viewer",
                             "Visible (4/4 permissions for Vertex Endpoints, Reasoning Engines, Dialogflow CX and Agentspace)" if res_status == "GRANTED"
                             else (f"Partial ({len(res_granted)}/4 permissions granted; missing: {', '.join(res_missing)})" if res_status == "PARTIAL"
                                   else f"{_DENIED_403}: unable to inspect Vertex Endpoints, Dialogflow CX Agents or Agentspace Apps"),
                             status=res_status, partial=res_status == "PARTIAL",
                             status_label="✅ OK (4/4)" if res_status == "GRANTED" else (f"⚠️ Partial ({len(res_granted)}/4)" if res_status == "PARTIAL" else "🔒 Denied (403)"),
                             extra={"grantedSubPermissions": res_granted, "missingSubPermissions": res_missing}),
        "modelArmor": _area("modelArmor", "Model Armor Configurations & Templates", can_ma, 200 if ma_status == "GRANTED" else 403,
                            "modelarmor.floorSettings.get, modelarmor.templates.list", "roles/modelarmor.viewer",
                            "Visible: reading Floor Settings and Model Armor Templates is allowed" if ma_status == "GRANTED"
                            else f"{_DENIED_403}: unable to read Floor Settings and Model Armor Templates", status=ma_status),
        "apiKeys": _area("apiKeys", "API Key Names Inventory", can_keys, 200 if can_keys else 403, "serviceusage.apiKeys.list",
                         "roles/serviceusage.apiKeysViewer",
                         f"Visible ({n_keys} API Keys listed)" if can_keys else f"{_DENIED_403}: unable to read API Key names (any traffic appears only as UID)"),
        "serviceAccounts": _area("serviceAccounts", "IAM Service Accounts Inventory", can_sas, 200 if can_sas else 403, "iam.serviceAccounts.list",
                                 "roles/iam.securityReviewer (iam.serviceAccounts.list)",
                                 f"Visible ({n_sas} Service Accounts listed)" if can_sas else f"{_DENIED_403}: unable to read the project's IAM Service Accounts list"),
    }
    missing_summary = []
    if billing_enabled and not billing_ok:
        missing_summary.append("Billing Account Invoice (Monitoring Estimate Only)")
    if not can_su:
        missing_summary.append("Active API List / ServiceUsage (403)")
    if not can_mon:
        missing_summary.append("Metrics, Calls, Models, Tokens & Costs (403)")
    if res_status == "DENIED":
        missing_summary.append("AI Resources / Deployed Agents Inspection (403)")
    elif res_status == "PARTIAL":
        missing_summary.append(f"Partial AI Resources ({len(res_granted)}/4)")
    if ma_status == "DENIED":
        missing_summary.append("Model Armor Configurations & Templates (403)")
    if not can_keys:
        missing_summary.append("API Key Names (403)")
    if not can_sas:
        missing_summary.append("IAM Service Accounts List (403)")
    if len(granted_list) == len(IAM_PERMISSIONS):
        level, badge = "FULL", f"🟢 Project Permissions OK ({len(granted_list)}/{len(IAM_PERMISSIONS)})"
    elif can_mon:
        level, badge = "PARTIAL", f"⚠️ Partial Permissions ({len(granted_list)}/{len(IAM_PERMISSIONS)})"
    else:
        level, badge = "NO_MONITORING_ACCESS", f"🔒 Access Denied to Metrics/Costs ({len(granted_list)}/{len(IAM_PERMISSIONS)})"
    return {
        "accessLevel": level, "badgeLabel": badge, "iamGrantedCount": len(granted_list), "iamTotalCount": len(IAM_PERMISSIONS),
        "grantedIamPermissions": granted_list, "missingIamPermissions": missing,
        "missingSummary": missing_summary, "areas": areas,
    }


def _denied_permissions() -> dict:
    """Project where only ``resourcemanager.projects.get`` is granted (the backend builds it from the same function)."""
    granted = ["resourcemanager.projects.get"]
    perms = _permissions(False, False, False, 0, 0, 0, True)
    perms["grantedIamPermissions"] = granted
    perms["iamGrantedCount"] = 1
    perms["missingIamPermissions"] = [p for p in IAM_PERMISSIONS if p not in granted]
    perms["badgeLabel"] = f"🔒 Access Denied to Metrics/Costs (1/{len(IAM_PERMISSIONS)})"
    perms["accessLevel"] = "NO_MONITORING_ACCESS"
    return perms


def _model_armor(mode: str, threats: tuple, pid: str, ref: date, locations: list[str]) -> dict:
    flagged, blocked, sanitize_logs = threats
    base = {
        "enabled": mode != "off", "permissionGranted": True, "status": "DISABLED", "statusLabel": "Not Enabled",
        "totalRequests": 0, "sanitizeRequests": 0, "methodsCalled": [], "activeLocations": [], "floorSetting": None,
        "templates": [], "rawFloorSetting": None,
        "threatTelemetry": {"logQueryExecuted": False, "totalSanitizeLogs": 0, "flaggedCount": 0, "blockedCount": 0, "passedCount": 0,
                            "byCategory": {"promptInjectionAndJailbreak": 0, "sdpDlp": 0, "rai": 0, "maliciousUri": 0, "csam": 0}, "recentViolations": []},
    }
    if mode == "off":
        return base
    filters = {"hasConfiguredFilters": True, "promptInjectionAndJailbreak": "MEDIUM_AND_ABOVE", "raiFilters": ["HATE_SPEECH", "HARASSMENT"],
               "sdpDlp": "ENABLED", "maliciousUri": "ENABLED", "csam": "ENABLED", "summaryBadges": ["PI&Jailbreak", "SDP", "URI"]}
    floor = {"name": f"projects/{pid}/locations/global/floorSetting", "enforcementEnabled": True, "enforcementMode": "INSPECT_AND_BLOCK (Blocks Prompts/Responses)",
             "integratedServices": ["AI_PLATFORM"], "cloudLoggingEnabled": True, "updateTime": _iso(ref, 40), "filters": filters}
    template = {"templateId": "default-guardrails", "fullName": f"projects/{pid}/locations/europe-west1/templates/default-guardrails", "location": "europe-west1",
                "createTime": _iso(ref, 80), "updateTime": _iso(ref, 40), "labels": {}, "enforcementType": "INSPECT_AND_BLOCK",
                "logSanitizeOperations": True, "customPromptErrorMessage": "", "filters": filters}
    base.update({
        "status": "CONFIGURED_ACTIVE", "statusLabel": "Active (1 Templates, Floor Policy ON)", "totalRequests": sanitize_logs + 40,
        "sanitizeRequests": sanitize_logs, "methodsCalled": ["google.cloud.modelarmor.v1.ModelArmor.SanitizeUserPrompt"], "activeLocations": locations,
        "floorSetting": floor, "templates": [template],
        "rawFloorSetting": {"name": floor["name"], "createTime": _iso(ref, 80), "updateTime": _iso(ref, 40)},
    })
    if mode == "partial":
        base.update({"status": "API_ENABLED_DEFAULT", "statusLabel": "API Enabled (0 Templates / Default Floor Setting not configured)", "floorSetting": None, "templates": []})
    cats_total = flagged
    base["threatTelemetry"] = {
        "logQueryExecuted": True, "totalSanitizeLogs": sanitize_logs, "flaggedCount": flagged, "blockedCount": blocked,
        "passedCount": max(0, sanitize_logs - flagged),
        "byCategory": {"promptInjectionAndJailbreak": int(cats_total * 0.5), "sdpDlp": int(cats_total * 0.3), "rai": int(cats_total * 0.1),
                       "maliciousUri": cats_total - int(cats_total * 0.5) - int(cats_total * 0.3) - int(cats_total * 0.1), "csam": 0},
        "recentViolations": [],
    }
    return base


# ---------------------------------------------------------------------------------------------------------
# Project construction
# ---------------------------------------------------------------------------------------------------------


def _blank_project(spec: dict) -> dict:
    return {
        "projectId": spec["pid"], "name": spec["name"], "projectNumber": spec["number"], "billingEnabled": False,
        "billingAccountName": None, "skippedNoBilling": False, "aiActive": False, "scanStatus": "SCANNED",
        "vertexEnabled": False, "geminiApiEnabled": False, "modelArmorEnabled": False, "enabledAiApis": [], "vertexFeatures": [],
        "deployedAiResources": [], "modelArmor": _model_armor("off", (0, 0, 0), spec["pid"], date(2026, 1, 1), []),
        "permissions": {}, "vertexRequests": 0, "vertexInferenceRequests": 0, "geminiApiRequests": 0, "geminiInferenceRequests": 0,
        "inferenceRequests": 0, "systemRequests": 0, "totalRequests": 0, "errors429": 0, "errors5xx": 0,
        "httpStatusBreakdown": {"200": 0, "400": 0, "403": 0, "404": 0, "429": 0, "500": 0, "other": 0}, "avgLatencyMs": 0.0,
        "inputTokens": 0, "outputTokens": 0, "cachedTokens": 0, "thinkingTokens": 0, "totalTokens": 0,
        "vertexGrossCostUsd": 0.0, "vertexCacheSavingsUsd": 0.0, "vertexCostUsd": 0.0, "geminiGrossCostUsd": 0.0,
        "geminiCacheSavingsUsd": 0.0, "geminiCostUsd": 0.0, "geminiRequestBytes": 0, "geminiResponseBytes": 0,
        "otherAiGrossCostUsd": 0.0, "otherAiCacheSavingsUsd": 0.0, "otherAiCostUsd": 0.0, "estimatedCostUsd": 0.0, "costUsd": 0.0,
        "models": [], "credentialsUsage": [], "usersUsage": [], "apiKeys": [], "serviceAccounts": [], "dailySeries": {},
        "budgetUsd": 100.0, "blocked": False, "createTime": _iso(date(2026, 1, 1), 0),
    }


def _enabled_apis(services: list[str]) -> list[dict]:
    out = []
    for s in services:
        label, cat, icon, desc = API_CATALOG[s]
        out.append({"service": s, "label": label, "category": cat, "icon": icon, "description": desc})
    return out


def _cred_meta(cid: str, spec: dict, keys_by_uid: dict, sas_by_uid: dict, oauth_by_client: dict) -> dict:
    """resolvedName / resolvedType / ownerEmail / email of a credential id."""
    if cid.startswith("apikey:"):
        k = keys_by_uid[cid.split(":", 1)[1]]
        suffix = " (Eliminata)" if k["status"] == "DELETED_OR_EXTERNAL" else ""
        return {"resolvedName": f"API Key: {k['name']}{suffix}", "resolvedType": "API_KEY", "ownerEmail": k["owner"]}
    if cid.startswith("serviceaccount:"):
        sa = sas_by_uid[cid.split(":", 1)[1]]
        return {"resolvedName": f"SA: {sa['email']}", "resolvedType": "SERVICE_ACCOUNT", "ownerEmail": None, "email": sa["email"]}
    if cid.startswith("oauth2:"):
        o = oauth_by_client[cid.split(":", 1)[1]]
        return {"resolvedName": f"{o['display']} — {o['owner']}" if "@" in o["owner"] else o["display"], "resolvedType": "OAUTH_CLIENT", "ownerEmail": o["owner"]}
    return {"resolvedName": "Non attribuibile (Data Access Audit Logs disattivati)", "resolvedType": "OAUTH_CLIENT", "ownerEmail": None}


def _simulate_project(spec: dict, days_list: list[date], seed: int) -> dict:
    """Runs every stream over every day and aggregates per project / model / credential / pool user."""
    n = len(days_list)
    proj_ds: dict[str, dict] = {}
    model_ds: dict[str, dict[str, dict]] = {}
    model_meta: dict[str, dict] = {}
    cred_ds: dict[str, dict[str, dict]] = {}
    cred_meta: dict[str, dict] = {}
    pool_tot: dict[str, dict] = {}
    extra = {"saved": {"vertex": 0.0, "gemini": 0.0, "other": 0.0}, "other_err": 0, "reqBytes": 0, "respBytes": 0, "geminiInf": 0}
    model_saved: dict[str, float] = {}
    cred_saved: dict[str, float] = {}
    cred_bytes: dict[str, list[int]] = {}
    cred_other_err: dict[str, int] = {}
    for st in spec.get("streams", []):
        burst_days = {n - 1 - k for k in st.get("burst", [])} if st.get("burst") else set()
        for i, d in enumerate(days_list):
            rnd = _Rnd(seed, spec["pid"], st["key"], d.isoformat())
            f = _day_factor(st, d, i, n, rnd)
            if f <= 0:
                continue
            if st["kind"] == "llm":
                b, ex = _simulate_llm_day(st, f, rnd, i in burst_days or (st.get("e429", 0) >= 0.01 and rnd.random() < 0.08))
                mid = st["model"]
                svc_key = "vertex" if st["svc"] == SVC_VERTEX else ("gemini" if st["svc"] == SVC_GEMINI else "other")
                model_ds.setdefault(mid, {}).setdefault(d.isoformat(), _empty_bucket())
                _add_bucket(model_ds[mid][d.isoformat()], b)
                model_meta.setdefault(mid, {"service": st["svc"], "locations": set()})["locations"].add(st["loc"])
                cid = st["cred"]
                cred_ds.setdefault(cid, {}).setdefault(d.isoformat(), _empty_bucket())
                _add_bucket(cred_ds[cid][d.isoformat()], b)
                cm = cred_meta.setdefault(cid, {"services": set(), "methods": set(), "inferenceMethods": set(), "models": set()})
                cm["services"].add(st["svc"])
                cm["models"].add(mid)
                mth = METHODS["embed"] if "embedding" in mid else METHODS[st["svc"]]
                cm["inferenceMethods"].update(mth)
                cm["methods"].update(mth)
                extra["saved"][svc_key] = round(extra["saved"][svc_key] + ex["saved"], 4)
                model_saved[mid] = round(model_saved.get(mid, 0.0) + ex["saved"], 4)
                cred_saved[cid] = round(cred_saved.get(cid, 0.0) + ex["saved"], 4)
                cb = cred_bytes.setdefault(cid, [0, 0])
                cb[0] += ex["reqBytes"]
                cb[1] += ex["respBytes"]
                cred_other_err[cid] = cred_other_err.get(cid, 0) + ex["other_err"]
                extra["other_err"] += ex["other_err"]
                extra["reqBytes"] += ex["reqBytes"]
                extra["respBytes"] += ex["respBytes"]
                if st["svc"] == SVC_GEMINI:
                    extra["geminiInf"] += b["inferenceRequests"]
            else:
                b, ex = _simulate_pool_day(st, f, rnd)
                # split the daily pool bucket per pseudo-model so that models sum up to the project
                for kind, cnt in ex["counts"].items():
                    if cnt <= 0:
                        continue
                    mid = POOL_MODEL[kind]
                    mb = _empty_bucket()
                    pin, pout = POOL_TOKENS[kind]
                    cost = round(cnt * POOL_RATES[kind], 4)
                    mb.update({"requests": cnt, "inferenceRequests": cnt, "ok200": cnt, "ok200Inference": cnt, "tokens": cnt * (pin + pout),
                               "inputTokens": cnt * pin, "outputTokens": cnt * pout, "costUsd": cost, "otherAiCostUsd": cost})
                    model_ds.setdefault(mid, {}).setdefault(d.isoformat(), _empty_bucket())
                    _add_bucket(model_ds[mid][d.isoformat()], mb)
                    model_meta.setdefault(mid, {"service": POOL_SERVICE[kind], "locations": set()})["locations"].add("eu")
                # exact consistency: rebuild the project bucket from the per-model parts
                b = _empty_bucket()
                for kind, cnt in ex["counts"].items():
                    if cnt <= 0:
                        continue
                    pin, pout = POOL_TOKENS[kind]
                    cost = round(cnt * POOL_RATES[kind], 4)
                    b["requests"] += cnt
                    b["inferenceRequests"] += cnt
                    b["ok200"] += cnt
                    b["ok200Inference"] += cnt
                    b["tokens"] += cnt * (pin + pout)
                    b["inputTokens"] += cnt * pin
                    b["outputTokens"] += cnt * pout
                    b["costUsd"] = round(b["costUsd"] + cost, 4)
                    b["otherAiCostUsd"] = round(b["otherAiCostUsd"] + cost, 4)
                pt = pool_tot.setdefault(st["user"], {"assist": 0, "search": 0, "code": 0, "nb": 0, "tokIn": 0, "tokOut": 0, "cost": 0.0,
                                                      "days": set(), "first": d.isoformat(), "last": d.isoformat(),
                                                      "engines": list(st.get("engines", [])), "datastores": list(st.get("datastores", []))})
                for kind, cnt in ex["counts"].items():
                    pt[kind] += cnt
                    pt["tokIn"] += cnt * POOL_TOKENS[kind][0]
                    pt["tokOut"] += cnt * POOL_TOKENS[kind][1]
                    pt["cost"] = round(pt["cost"] + cnt * POOL_RATES[kind], 4)
                if sum(ex["counts"].values()) > 0:
                    pt["days"].add(d.isoformat())
                    pt["last"] = d.isoformat()
            proj_ds.setdefault(d.isoformat(), _empty_bucket())
            _add_bucket(proj_ds[d.isoformat()], b)
    return {"proj_ds": proj_ds, "model_ds": model_ds, "model_meta": model_meta, "cred_ds": cred_ds, "cred_meta": cred_meta,
            "pool_tot": pool_tot, "extra": extra, "model_saved": model_saved, "cred_saved": cred_saved, "cred_bytes": cred_bytes,
            "cred_other_err": cred_other_err}


def _series_fill(ds: dict, days_list: list[date]) -> dict:
    """Every day of the window is present (quiet days are zero buckets), sorted by date."""
    return {d.isoformat(): ds.get(d.isoformat(), _empty_bucket()) for d in days_list}


def _totals(series: dict) -> dict:
    t = _empty_bucket()
    for v in series.values():
        _add_bucket(t, v)
    return t


def _build_active_project(spec: dict, days_list: list[date], ref: date, seed: int) -> dict:
    pid = spec["pid"]
    p = _blank_project(spec)
    sim = _simulate_project(spec, days_list, seed)
    ref_str = ref.isoformat()
    yest_str = (ref - timedelta(days=1)).isoformat()

    keys = spec.get("keys", [])
    keys_by_uid = {k["uid"]: k for k in keys}
    sas_by_uid = {s["uniqueId"]: s for s in spec.get("sas", [])}
    oauth_by_client = {o["client"]: o for o in spec.get("oauth", [])}

    # --- project level
    series = _series_fill(sim["proj_ds"], days_list)
    tot = _totals(series)
    ex = sim["extra"]
    p["dailySeries"] = series
    p["billingEnabled"] = not spec.get("no_billing")
    p["skippedNoBilling"] = False
    p["billingAccountName"] = "billingAccounts/DEMO00-000000-000000" if p["billingEnabled"] else None
    p["aiActive"] = tot["requests"] > 0 or bool(spec.get("resources"))
    p["vertexEnabled"] = SVC_VERTEX in spec["apis"]
    p["geminiApiEnabled"] = SVC_GEMINI in spec["apis"]
    p["modelArmorEnabled"] = spec.get("ma", "off") == "active"
    p["enabledAiApis"] = _enabled_apis(spec["apis"])
    p["createTime"] = _iso(ref, spec["age"])
    p["budgetUsd"] = float(spec.get("budget", 100.0))
    p["isAiStudioProject"] = bool(spec.get("aistudio"))
    p["avgLatencyMs"] = float(spec.get("latency", 0.0))
    p["vertexRequests"] = tot["vertexRequests"]
    p["vertexInferenceRequests"] = tot["vertexInferenceRequests"]
    p["geminiApiRequests"] = tot["geminiApiRequests"]
    p["geminiInferenceRequests"] = ex["geminiInf"]
    p["inferenceRequests"] = tot["inferenceRequests"]
    p["systemRequests"] = tot["systemRequests"]
    p["totalRequests"] = tot["requests"]
    p["errors429"] = tot["errors429"]
    e5 = int(ex["other_err"] * 0.3)
    p["errors5xx"] = e5
    p["httpStatusBreakdown"] = {"200": tot["ok200"], "400": int(ex["other_err"] * 0.2), "403": ex["other_err"] - e5 - int(ex["other_err"] * 0.2),
                                "404": 0, "429": tot["errors429"], "500": e5, "other": 0}
    for k_in, k_out in (("inputTokens", "inputTokens"), ("outputTokens", "outputTokens"), ("cachedTokens", "cachedTokens"),
                        ("thinkingTokens", "thinkingTokens"), ("tokens", "totalTokens")):
        p[k_out] = tot[k_in]
    p["vertexCostUsd"] = tot["vertexCostUsd"]
    p["geminiCostUsd"] = tot["geminiCostUsd"]
    p["otherAiCostUsd"] = tot["otherAiCostUsd"]
    for cls, key in (("vertex", "vertex"), ("gemini", "gemini"), ("other", "otherAi")):
        p[f"{key}CacheSavingsUsd"] = ex["saved"][cls]
        p[f"{key}GrossCostUsd"] = round(p[f"{key}CostUsd"] + ex["saved"][cls], 4)
    p["geminiRequestBytes"] = ex["reqBytes"]
    p["geminiResponseBytes"] = ex["respBytes"]
    p["estimatedCostUsd"] = tot["costUsd"]
    p["costUsd"] = tot["costUsd"]


    # --- models
    models = []
    for mid, mseries in sim["model_ds"].items():
        s = _series_fill(mseries, days_list)
        t = _totals(s)
        saved = sim["model_saved"].get(mid, 0.0)
        meta = sim["model_meta"][mid]
        models.append({
            "modelId": mid, "service": meta["service"], "locations": sorted(meta["locations"]), "invocations": t["inferenceRequests"],
            "inputTokens": t["inputTokens"], "outputTokens": t["outputTokens"], "cachedTokens": t["cachedTokens"], "thinkingTokens": t["thinkingTokens"],
            "totalTokens": t["tokens"], "grossCostUsd": round(t["costUsd"] + saved, 4), "cacheSavingsUsd": saved, "costUsd": t["costUsd"], "dailySeries": s,
        })
    models.sort(key=lambda m: (m["costUsd"], m["totalTokens"]), reverse=True)
    p["models"] = models

    # --- credentials
    creds = []
    for cid, cseries in sim["cred_ds"].items():
        s = _series_fill(cseries, days_list)
        t = _totals(s)
        saved = sim["cred_saved"].get(cid, 0.0)
        meta = sim["cred_meta"][cid]
        cm = _cred_meta(cid, spec, keys_by_uid, sas_by_uid, oauth_by_client)
        rb = sim["cred_bytes"].get(cid, [0, 0])
        other_err = sim["cred_other_err"].get(cid, 0)
        today = s.get(ref_str, _empty_bucket())
        yest = s.get(yest_str, _empty_bucket())
        c = {
            "credentialId": cid, "service": ", ".join(sorted(meta["services"])), "services": sorted(meta["services"]),
            "requests": t["requests"], "inferenceRequests": t["inferenceRequests"], "vertexInferenceRequests": t["vertexInferenceRequests"],
            "systemRequests": t["systemRequests"], "ok200": t["ok200"], "ok200Inference": t["ok200Inference"], "errors429": t["errors429"],
            "otherErrors": other_err, "inputTokens": t["inputTokens"], "outputTokens": t["outputTokens"], "cachedTokens": t["cachedTokens"],
            "totalTokens": t["tokens"], "requestBytes": rb[0], "responseBytes": rb[1], "grossCostUsd": round(t["costUsd"] + saved, 4),
            "cacheSavingsUsd": saved, "estimatedCostUsd": t["costUsd"], "costSource": "MONITORING_TOKENS",
            "methods": sorted(meta["methods"]), "inferenceMethods": sorted(meta["inferenceMethods"]), "systemMethods": [],
            "dailySeries": s, "todayDate": ref_str, "todayCalls": today["inferenceRequests"], "todayTokens": today["tokens"], "todayCostUsd": today["costUsd"],
            "yesterdayDate": yest_str, "yesterdayCalls": yest["inferenceRequests"], "yesterdayTokens": yest["tokens"], "yesterdayCostUsd": yest["costUsd"],
            "modelsUsed": sorted(meta["models"]),
        }
        c.update({k: v for k, v in cm.items() if v is not None})
        creds.append(c)
    creds.sort(key=lambda c: (c["estimatedCostUsd"], c["inferenceRequests"], c["requests"]), reverse=True)
    p["credentialsUsage"] = creds
    creds_by_id = {c["credentialId"]: c for c in creds}

    # --- API keys
    api_keys = []
    for k in keys:
        c = creds_by_id.get(f"apikey:{k['uid']}", {})
        api_keys.append({
            "uid": k["uid"], "name": f"projects/{spec['number']}/locations/global/keys/{k['uid']}", "displayName": k["name"] + (" (Eliminata)" if k["status"] != "ACTIVE" else ""),
            "ownerEmail": k["owner"], "status": k["status"], "createTime": _iso(ref, k["age"]), "restrictions": list(k["targets"]),
            "apiTargets": list(k["targets"]), "isAiStudioKey": bool(k["aiStudio"]), "services": c.get("services", list(k["targets"])),
            "requests": c.get("requests", 0), "inferenceRequests": c.get("inferenceRequests", 0), "ok200Inference": c.get("ok200Inference", 0),
            "failedInference": max(0, c.get("inferenceRequests", 0) - c.get("ok200Inference", 0)), "systemRequests": c.get("systemRequests", 0),
            "ok200": c.get("ok200", 0), "errors429": c.get("errors429", 0), "otherErrors": c.get("otherErrors", 0),
            "inputTokens": c.get("inputTokens", 0), "outputTokens": c.get("outputTokens", 0), "cachedTokens": c.get("cachedTokens", 0),
            "totalTokens": c.get("totalTokens", 0), "requestBytes": c.get("requestBytes", 0), "responseBytes": c.get("responseBytes", 0),
            "grossCostUsd": c.get("grossCostUsd", 0.0), "cacheSavingsUsd": c.get("cacheSavingsUsd", 0.0), "estimatedCostUsd": c.get("estimatedCostUsd", 0.0),
            "todayDate": ref_str, "todayCalls": c.get("todayCalls", 0), "todayTokens": c.get("todayTokens", 0), "todayCostUsd": c.get("todayCostUsd", 0.0),
            "yesterdayDate": yest_str, "yesterdayCalls": c.get("yesterdayCalls", 0), "yesterdayTokens": c.get("yesterdayTokens", 0),
            "yesterdayCostUsd": c.get("yesterdayCostUsd", 0.0), "costSource": "MONITORING_TOKENS" if c else "NONE",
            "methods": c.get("methods", []), "inferenceMethods": c.get("inferenceMethods", []), "ageDays": k["age"],
        })
    api_keys.sort(key=lambda x: (x["estimatedCostUsd"], x["requests"]), reverse=True)
    p["apiKeys"] = api_keys

    # --- service accounts
    sas = []
    for s_ in spec.get("sas", []):
        c = creds_by_id.get(f"serviceaccount:{s_['uniqueId']}", {})
        key_list = [{"keyId": f"demo-key-{s_['uniqueId'][-3:]}-{j + 1:02d}", "keyType": "USER_MANAGED", "keyOrigin": "GOOGLE_PROVIDED",
                     "validAfterTime": _iso(ref, 400 - j * 30), "validBeforeTime": "9999-12-31T23:59:59Z"} for j in range(s_["keys"])]
        sas.append({
            "uniqueId": s_["uniqueId"], "email": s_["email"], "displayName": s_["name"], "disabled": s_["disabled"], "isDefaultGcpSa": s_["default"],
            "requests": c.get("requests", 0), "inferenceRequests": c.get("inferenceRequests", 0), "systemRequests": c.get("systemRequests", 0),
            "ok200": c.get("ok200", 0), "errors429": c.get("errors429", 0), "totalTokens": c.get("totalTokens", 0),
            "estimatedCostUsd": round(c.get("estimatedCostUsd", 0.0), 4), "methods": c.get("methods", []),
            "userManagedKeysCount": s_["keys"], "expiredOrOldKeysCount": s_["oldKeys"], "keys": key_list,
            "lastSeen": _iso(ref, 0, 8, 30) if c else None, "modelsUsed": c.get("modelsUsed", []),
        })
    p["serviceAccounts"] = sas

    # --- users
    p["usersUsage"] = _build_users(spec, sim, creds_by_id, api_keys, keys, oauth_by_client, p, ref)

    # --- vertex features (feature requests derived from stream totals)
    p["vertexFeatures"] = _build_features(spec, sim, days_list)

    # --- resources, Model Armor, permissions
    p["deployedAiResources"] = [dict(r) for r in spec.get("resources", [])]
    locs = sorted({st["loc"] for st in spec.get("streams", []) if st["kind"] == "llm"})[:3]
    ma_mode = spec.get("ma", "off")
    p["modelArmor"] = _model_armor(ma_mode, spec.get("ma_threats", (0, 0, 0)), pid, ref, locs)
    p["permissions"] = _permissions(ma_mode != "partial", ma_mode == "partial", pid in ("acme-finance-prod", "acme-hr-assistant"),
                                    len(spec["apis"]), len(keys), len(sas), True)
    return p


def _build_features(spec: dict, sim: dict, days_list: list[date]) -> list[dict]:
    feats = []
    for feat in spec.get("features", []):
        fid, name, cat, icon, prefix = feat[:5]
        req = inf = 0
        if len(feat) > 5:
            req = inf = int(feat[5])
        elif prefix and prefix in POOL_RATES:
            for pt in sim["pool_tot"].values():
                req += pt[prefix]
            inf = req
        elif prefix:
            for st in spec["streams"]:
                if st["kind"] == "llm" and st["key"].startswith(prefix):
                    t = _totals(_series_fill(sim["cred_ds"].get(st["cred"], {}), days_list))
                    req = inf = t["inferenceRequests"]
        else:
            req = inf = 0
        feats.append({"id": fid, "name": name, "service": SVC_VERTEX, "category": cat, "icon": icon,
                      "description": name, "status": "ACTIVE_TRAFFIC" if req > 0 else "ENABLED_NO_TRAFFIC", "requests": req,
                      "inferenceRequests": inf, "methods": [], "locations": sorted({st.get("loc", "eu") for st in spec["streams"] if st["kind"] == "llm"})[:2],
                      "isControlPlaneOnly": False})
    return feats


def _user_template(email: str, pid: str, utype: str) -> dict:
    return {
        "userEmail": email, "projectId": pid, "userType": utype, "totalInteractions": 0, "assistTurns": 0, "searchQueries": 0, "fileOps": 0,
        "codeAssistCalls": 0, "codeAssistAcceptedLines": 0, "codeAssistAcceptedCount": 0, "codeAssistExposedCount": 0, "codeAssistAcceptanceRatePct": 0.0,
        "codeAssistInputChars": 0, "codeAssistOutputChars": 0, "codeAssistSeatMonthlyUsd": 0.0, "codeAssistLanguages": [], "codeAssistWorkspaces": [],
        "notebookLmCalls": 0, "colabCalls": 0, "aiStudioCalls": 0, "otherCalls": 0, "toolsUsed": [], "loggedInferenceOps": 0, "loggedInputTokens": 0,
        "loggedOutputTokens": 0, "loggedCachedTokens": 0, "loggedTotalTokens": 0, "attributedTokens": 0, "vertexOauthCalls": 0,
        "vertexOauthInputTokens": 0, "vertexOauthOutputTokens": 0, "vertexOauthCachedTokens": 0, "vertexOauthTokens": 0, "vertexOauthGrossCostUsd": 0.0,
        "vertexOauthCacheSavingsUsd": 0.0, "vertexOauthCostUsd": 0.0, "vertexOauthTodayCalls": 0, "vertexOauthTodayTokens": 0, "vertexOauthTodayCostUsd": 0.0,
        "vertexOauthYesterdayCalls": 0, "vertexOauthYesterdayTokens": 0, "vertexOauthYesterdayCostUsd": 0.0, "oauthClientsDetails": [],
        "apiKeysCount": 0, "apiKeysNames": [], "apiKeysDetails": [], "apiKeysCalls": 0, "apiKeysInputTokens": 0, "apiKeysOutputTokens": 0,
        "apiKeysCachedTokens": 0, "apiKeysTotalTokens": 0, "apiKeysRequestBytes": 0, "apiKeysResponseBytes": 0, "apiKeysGrossCostUsd": 0.0,
        "apiKeysCacheSavingsUsd": 0.0, "apiKeysCostUsd": 0.0, "apiKeysTodayCalls": 0, "apiKeysTodayTokens": 0, "apiKeysTodayCostUsd": 0.0,
        "apiKeysYesterdayCalls": 0, "apiKeysYesterdayTokens": 0, "apiKeysYesterdayCostUsd": 0.0, "oauthCostUsd": 0.0, "oauthSharePct": 0.0,
        "directCostUsd": 0.0, "estimatedCostUsd": 0.0, "sharePct": 0.0, "methods": [], "engines": [], "dataStores": [], "ideClients": [], "services": [],
        "firstSeen": "", "lastSeen": "", "codeAssistCostUsd": 0.0, "codeAssistTokens": 0, "antigravityIdeCalls": 0, "antigravityIdeTokens": 0,
        "antigravityIdeCostUsd": 0.0, "activeDaysCount": 0, "queriesCount": 0, "conversationsCount": 0, "antigravityIdeMode": "NO_GCP_IDE_BILLING",
    }


def _build_users(spec, sim, creds_by_id, api_keys, keys, oauth_by_client, p, ref) -> list[dict]:
    pid = spec["pid"]
    users: dict[str, dict] = {}
    types = {u["email"]: u["type"] for u in spec.get("users", [])}

    def get(email: str) -> dict:
        if email not in users:
            users[email] = _user_template(email, pid, types.get(email, "OAUTH_WORKLOAD" if email.startswith("oauth-workload:") else "INTERNAL_USER"))
        return users[email]

    # pool users (Gemini Enterprise / Code Assist / NotebookLM)
    for email, pt in sim["pool_tot"].items():
        u = get(email)
        u["assistTurns"], u["searchQueries"], u["codeAssistCalls"], u["notebookLmCalls"] = pt["assist"], pt["search"], pt["code"], pt["nb"]
        u["loggedInputTokens"], u["loggedOutputTokens"] = pt["tokIn"], pt["tokOut"]
        u["loggedTotalTokens"] = pt["tokIn"] + pt["tokOut"]
        u["loggedInferenceOps"] = pt["assist"] + pt["search"] + pt["code"] + pt["nb"]
        u["oauthCostUsd"] = pt["cost"]
        u["engines"], u["dataStores"] = pt["engines"], pt["datastores"]
        u["firstSeen"], u["lastSeen"], u["activeDaysCount"] = pt["first"], pt["last"], len(pt["days"])
        u["services"] = sorted({SVC_COMPANION if pt["code"] else SVC_DISCOVERY})
        u["methods"] = (["google.cloud.discoveryengine.v1alpha.AssistantService.StreamAssist"] if pt["assist"] else []) + \
                       (["google.cloud.discoveryengine.v1.SearchService.Search"] if pt["search"] else []) + \
                       (["google.cloud.cloudaicompanion.v1.CodeCompletionService.CompleteCode"] if pt["code"] else [])
        if pt["code"]:
            accepted = int(pt["code"] * 0.31)
            u["codeAssistExposedCount"], u["codeAssistAcceptedCount"] = pt["code"], accepted
            u["codeAssistAcceptedLines"] = accepted * 3
            u["codeAssistAcceptanceRatePct"] = round(100.0 * accepted / max(1, pt["code"]), 1)
            u["codeAssistInputChars"], u["codeAssistOutputChars"] = pt["code"] * 2400, pt["code"] * 520
            u["codeAssistSeatMonthlyUsd"] = 19.0
            u["codeAssistLanguages"] = ["python", "typescript", "go"][: 1 + (len(email) % 3)]
            u["codeAssistWorkspaces"] = [f"acme-{email.split('.')[0]}-workspace"]
            u["ideClients"] = ["VS Code (Gemini Code Assist)"]
        if pt["nb"]:
            u["methods"].append("google.cloud.discoveryengine.v1alpha.NotebookService.ListNotebooks")
        u["toolsUsed"] = []

    # credential-attributed users (API keys, shared OAuth client)
    keys_by_uid = {k["uid"]: k for k in keys}
    for cid, c in creds_by_id.items():
        owner = c.get("ownerEmail")
        if not owner:
            continue
        u = get(owner)
        today_d, yest_d = c["todayDate"], c["yesterdayDate"]
        if cid.startswith("apikey:"):
            k = keys_by_uid[cid.split(":", 1)[1]]
            detail = {"uid": k["uid"], "displayName": k["name"], "status": k["status"], "calls": c["inferenceRequests"], "ok200Calls": c["ok200Inference"],
                      "inputTokens": c["inputTokens"], "outputTokens": c["outputTokens"], "totalTokens": c["totalTokens"],
                      "requestBytes": c["requestBytes"], "responseBytes": c["responseBytes"], "grossCostUsd": c["grossCostUsd"],
                      "cacheSavingsUsd": c["cacheSavingsUsd"], "costUsd": c["estimatedCostUsd"], "todayDate": today_d, "todayCalls": c["todayCalls"],
                      "todayTokens": c["todayTokens"], "todayCostUsd": c["todayCostUsd"], "yesterdayDate": yest_d, "yesterdayCalls": c["yesterdayCalls"],
                      "yesterdayTokens": c["yesterdayTokens"], "yesterdayCostUsd": c["yesterdayCostUsd"], "methods": c["methods"]}
            u["apiKeysDetails"].append(detail)
            u["apiKeysNames"].append(k["name"])
            u["apiKeysCount"] += 1
            u["apiKeysCalls"] += detail["calls"]
            u["apiKeysInputTokens"] += detail["inputTokens"]
            u["apiKeysOutputTokens"] += detail["outputTokens"]
            u["apiKeysCachedTokens"] += c["cachedTokens"]
            u["apiKeysTotalTokens"] += detail["totalTokens"]
            u["apiKeysRequestBytes"] += detail["requestBytes"]
            u["apiKeysResponseBytes"] += detail["responseBytes"]
            u["apiKeysGrossCostUsd"] = round(u["apiKeysGrossCostUsd"] + detail["grossCostUsd"], 4)
            u["apiKeysCacheSavingsUsd"] = round(u["apiKeysCacheSavingsUsd"] + detail["cacheSavingsUsd"], 4)
            u["apiKeysCostUsd"] = round(u["apiKeysCostUsd"] + detail["costUsd"], 4)
            u["apiKeysTodayCalls"] += detail["todayCalls"]
            u["apiKeysTodayTokens"] += detail["todayTokens"]
            u["apiKeysTodayCostUsd"] = round(u["apiKeysTodayCostUsd"] + detail["todayCostUsd"], 4)
            u["apiKeysYesterdayCalls"] += detail["yesterdayCalls"]
            u["apiKeysYesterdayTokens"] += detail["yesterdayTokens"]
            u["apiKeysYesterdayCostUsd"] = round(u["apiKeysYesterdayCostUsd"] + detail["yesterdayCostUsd"], 4)
            u["services"] = sorted(set(u["services"]) | set(c["services"]))
            u["methods"] = sorted(set(u["methods"]) | set(c["methods"]))
            if SVC_GEMINI in c["services"]:
                u["aiStudioCalls"] += detail["calls"]
        elif cid.startswith("oauth2:"):
            o = oauth_by_client[cid.split(":", 1)[1]]
            raw = cid.split(":", 1)[1]
            detail = {"credentialId": cid, "clientId": raw, "displayName": o["display"], "tool": o["tool"], "calls": c["inferenceRequests"],
                      "ok200Calls": c["ok200Inference"], "errors429": c["errors429"], "inputTokens": c["inputTokens"], "outputTokens": c["outputTokens"],
                      "cachedTokens": c["cachedTokens"], "totalTokens": c["totalTokens"], "grossCostUsd": c["grossCostUsd"],
                      "cacheSavingsUsd": c["cacheSavingsUsd"], "costUsd": c["estimatedCostUsd"], "todayDate": today_d, "todayCalls": c["todayCalls"],
                      "todayTokens": c["todayTokens"], "todayCostUsd": c["todayCostUsd"], "yesterdayDate": yest_d, "yesterdayCalls": c["yesterdayCalls"],
                      "yesterdayTokens": c["yesterdayTokens"], "yesterdayCostUsd": c["yesterdayCostUsd"], "services": c["services"],
                      "models": c["modelsUsed"], "methods": c["methods"]}
            u["oauthClientsDetails"].append(detail)
            u["vertexOauthCalls"] += detail["calls"]
            u["vertexOauthInputTokens"] += detail["inputTokens"]
            u["vertexOauthOutputTokens"] += detail["outputTokens"]
            u["vertexOauthCachedTokens"] += detail["cachedTokens"]
            u["vertexOauthTokens"] += detail["totalTokens"]
            u["vertexOauthGrossCostUsd"] = round(u["vertexOauthGrossCostUsd"] + detail["grossCostUsd"], 4)
            u["vertexOauthCacheSavingsUsd"] = round(u["vertexOauthCacheSavingsUsd"] + detail["cacheSavingsUsd"], 4)
            u["vertexOauthCostUsd"] = round(u["vertexOauthCostUsd"] + detail["costUsd"], 4)
            u["vertexOauthTodayCalls"] += detail["todayCalls"]
            u["vertexOauthTodayTokens"] += detail["todayTokens"]
            u["vertexOauthTodayCostUsd"] = round(u["vertexOauthTodayCostUsd"] + detail["todayCostUsd"], 4)
            u["vertexOauthYesterdayCalls"] += detail["yesterdayCalls"]
            u["vertexOauthYesterdayTokens"] += detail["yesterdayTokens"]
            u["vertexOauthYesterdayCostUsd"] = round(u["vertexOauthYesterdayCostUsd"] + detail["yesterdayCostUsd"], 4)
            u["services"] = sorted(set(u["services"]) | set(c["services"]))
            u["methods"] = sorted(set(u["methods"]) | set(c["methods"]))
            u["ideClients"] = ["Antigravity IDE (Vertex AI OAuth)"]
            active = [d for d, v in c["dailySeries"].items() if v["inferenceRequests"] > 0]
            u["firstSeen"], u["lastSeen"], u["activeDaysCount"] = (min(active), max(active), len(active)) if active else ("", "", 0)
    # colab / workbench users from notebook resources
    for r in spec.get("resources", []):
        if r["resourceType"] in ("COLAB_ENTERPRISE_RUNTIME", "COLAB_EXECUTION_JOB") and r.get("runtimeUser"):
            get(r["runtimeUser"])["colabCalls"] += 1

    total_cost = p["estimatedCostUsd"] or 0.0
    out = []
    for u in users.values():
        u["oauthCostUsd"] = round(u["oauthCostUsd"] + u["vertexOauthCostUsd"], 4)
        u["directCostUsd"] = round(u["oauthCostUsd"] + u["apiKeysCostUsd"], 4)
        u["estimatedCostUsd"] = u["directCostUsd"]
        u["oauthSharePct"] = round(100.0 * u["oauthCostUsd"] / u["directCostUsd"], 1) if u["directCostUsd"] > 0 else 0.0
        u["sharePct"] = round(100.0 * u["estimatedCostUsd"] / total_cost, 2) if total_cost > 0 else 0.0
        u["attributedTokens"] = u["loggedTotalTokens"] + u["vertexOauthTokens"] + u["apiKeysTotalTokens"]
        u["totalInteractions"] = u["assistTurns"] + u["searchQueries"] + u["codeAssistCalls"] + u["notebookLmCalls"] + u["fileOps"] + u["otherCalls"] + u["vertexOauthCalls"]
        if u["estimatedCostUsd"] > 0 or u["colabCalls"] > 0 or u["totalInteractions"] > 0 or u["apiKeysCalls"] > 0:
            out.append(u)
    out.sort(key=lambda x: (x["estimatedCostUsd"], x["attributedTokens"], x["totalInteractions"]), reverse=True)
    return out


def _build_unscanned_project(spec: dict, ref: date, kind: str) -> dict:
    p = _blank_project(spec)
    p["createTime"] = _iso(ref, spec["age"])
    if kind == "no_billing":
        p["skippedNoBilling"] = True
        p["scanStatus"] = "SKIPPED_NO_BILLING"
        p["permissions"] = _permissions(True, False, False, 0, 0, 0, False)
        p["permissions"]["accessLevel"] = "SKIPPED_NO_BILLING"
        p["permissions"]["badgeLabel"] = "⚪ No Active Billing ($0)"
    elif kind == "denied":
        p["billingEnabled"] = True
        p["billingAccountName"] = "billingAccounts/DEMO00-000000-000000"
        p["scanStatus"] = "NO_PERMISSIONS_403"
        p["permissions"] = _denied_permissions()
    else:  # unverified
        p["billingEnabled"] = True
        p["scanStatus"] = "ERROR"
        p["transientError"] = "RATE_LIMITED"
        p["transientErrorStep"] = "serviceUsage"
        p["error"] = "serviceUsage: HTTP 429 (check not completed, retry)"
        p["permissions"] = {}
    return p


# ---------------------------------------------------------------------------------------------------------
# Payload assembly (mirrors build_scan_payload_from_projects of the backend, plus sync registry summary)
# ---------------------------------------------------------------------------------------------------------


def _sort_projects(projects: list[dict]) -> None:
    projects.sort(key=lambda x: (not x.get("skippedNoBilling", False), bool(x.get("aiActive", False)), x.get("scanStatus") != "NO_PERMISSIONS_403",
                                 x.get("estimatedCostUsd", 0.0), x.get("totalTokens", 0), x.get("inferenceRequests", 0),
                                 len(x.get("deployedAiResources", [])), bool(x.get("modelArmorEnabled", False)), x.get("totalRequests", 0),
                                 len(x.get("apiKeys", [])), x.get("projectId", "")), reverse=True)


def _build_summary(projects: list[dict]) -> dict:
    def s(key, default=0):
        return sum(p.get(key, default) or 0 for p in projects)

    def r(key, default=0.0):
        return round(sum(p.get(key, default) or 0.0 for p in projects), 4)

    users, users_cost, key_cost, oauth_cost, sa_cost = set(), 0.0, 0.0, 0.0, 0.0
    for p in projects:
        for u in p.get("usersUsage", []):
            if u.get("userEmail"):
                users.add(u["userEmail"])
            users_cost += u.get("estimatedCostUsd", 0.0)
        for c in p.get("credentialsUsage", []):
            kind, cost = c.get("resolvedType", ""), c.get("estimatedCostUsd", 0.0)
            if kind == "API_KEY":
                key_cost += cost
            elif kind == "SERVICE_ACCOUNT":
                sa_cost += cost
            else:
                oauth_cost += cost
    return {
        "totalProjects": len(projects), "billedProjects": sum(1 for p in projects if p.get("billingEnabled")),
        "skippedNoBillingProjects": sum(1 for p in projects if p.get("skippedNoBilling")),
        "aiEnabledProjects": sum(1 for p in projects if p.get("aiActive")),
        "hiddenNoAiProjects": sum(1 for p in projects if p.get("billingEnabled") and not p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403" and not p.get("transientError")),
        "noMonitoringAccessProjects": sum(1 for p in projects if p.get("scanStatus") == "NO_PERMISSIONS_403"),
        "partialAccessProjects": sum(1 for p in projects if p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403" and p.get("permissions", {}).get("accessLevel") == "PARTIAL"),
        "fullAccessProjects": sum(1 for p in projects if p.get("aiActive") and p.get("scanStatus") != "NO_PERMISSIONS_403" and p.get("permissions", {}).get("accessLevel") == "FULL"),
        "billingAccountDirectAccess": any(p.get("permissions", {}).get("areas", {}).get("billingCosts", {}).get("granted", False) for p in projects if p.get("billingEnabled")),
        "activeAiProjects": sum(1 for p in projects if p.get("totalRequests", 0) > 0 or p.get("totalTokens", 0) > 0),
        "modelArmorProjects": sum(1 for p in projects if p.get("modelArmorEnabled")),
        "totalDeployedAiResources": sum(len(p.get("deployedAiResources", [])) for p in projects),
        "totalRequests": s("totalRequests"), "inferenceRequests": s("inferenceRequests"), "systemRequests": s("systemRequests"),
        "vertexRequests": s("vertexRequests"), "geminiApiRequests": s("geminiApiRequests"), "errors429": s("errors429"),
        "totalTokens": s("totalTokens"), "inputTokens": s("inputTokens"), "outputTokens": s("outputTokens"), "cachedTokens": s("cachedTokens"),
        "thinkingTokens": s("thinkingTokens"),
        "vertexGrossCostUsd": r("vertexGrossCostUsd"), "vertexCacheSavingsUsd": r("vertexCacheSavingsUsd"), "vertexCostUsd": r("vertexCostUsd"),
        "geminiGrossCostUsd": r("geminiGrossCostUsd"), "geminiCacheSavingsUsd": r("geminiCacheSavingsUsd"), "geminiCostUsd": r("geminiCostUsd"),
        "otherAiGrossCostUsd": r("otherAiGrossCostUsd"), "otherAiCacheSavingsUsd": r("otherAiCacheSavingsUsd"), "otherAiCostUsd": r("otherAiCostUsd"),
        "estimatedCostUsd": r("estimatedCostUsd"),
        "totalApiKeys": sum(len(p.get("apiKeys", [])) for p in projects), "totalServiceAccounts": sum(len(p.get("serviceAccounts", [])) for p in projects),
        "totalActiveUsers": len(users), "totalUsersCostUsd": round(users_cost, 4), "totalApiKeysCostUsd": round(key_cost, 4),
        "totalOauthCostUsd": round(oauth_cost, 4), "totalServiceAccountsCostUsd": round(sa_cost, 4),
    }


def _timeline(projects: list[dict]) -> list[dict]:
    glob: dict[str, dict] = {}
    for p in projects:
        for day, v in p.get("dailySeries", {}).items():
            g = glob.setdefault(day, {"date": day, **_empty_bucket()})
            for k in BUCKET_INT_KEYS:
                g[k] += v.get(k, 0)
            for k in BUCKET_COST_KEYS:
                g[k] = round(g[k] + v.get(k, 0.0), 4)
    return [glob[k] for k in sorted(glob)]


NEW_PROJECT_IDS = ("acme-hackathon-2026",)
MANUAL_INCLUDE_IDS = ("acme-partner-portal",)
# services that count as "core AI" for the registry (same idea as CORE_AI_SERVICE_NAMES in backend/config.py)
_CORE_AI_SERVICES = {SVC_VERTEX, SVC_GEMINI, SVC_DISCOVERY, SVC_COMPANION, "modelarmor.googleapis.com", "dialogflow.googleapis.com",
                     "notebooks.googleapis.com", "agentregistry.googleapis.com"}


def _project_has_ai_data(p: dict) -> bool:
    """Mirror of ``project_has_ai_data`` (backend/sync_registry.py)."""
    if p.get("aiActive") or p.get("vertexEnabled") or p.get("geminiApiEnabled") or p.get("modelArmorEnabled"):
        return True
    if any((a.get("service") if isinstance(a, dict) else str(a)) in _CORE_AI_SERVICES for a in (p.get("enabledAiApis") or [])):
        return True
    if (p.get("estimatedCostUsd", 0.0) or 0.0) > 0:
        return True
    if (p.get("totalRequests", 0) or 0) > 0 or (p.get("inferenceRequests", 0) or 0) > 0 or (p.get("totalTokens", 0) or 0) > 0:
        return True
    return any(p.get(k) for k in ("models", "usersUsage", "deployedAiResources", "apiKeys"))


def _project_data_reason(p: dict) -> str:
    """Mirror of ``get_project_data_reason`` (backend/sync_registry.py)."""
    reasons = []
    apis_cnt = len(p.get("enabledAiApis") or [])
    cost = p.get("estimatedCostUsd", 0.0) or 0.0
    reqs = p.get("inferenceRequests", 0) or p.get("totalRequests", 0) or 0
    toks = p.get("totalTokens", 0) or 0
    for cnt, text in ((apis_cnt, f"{apis_cnt} APIs enabled"), (cost > 0, f"AI cost ${cost:.2f}"), (reqs > 0, f"{reqs:,} calls"), (toks > 0, f"{toks:,} tokens"),
                      (len(p.get("models") or []) > 0, f"{len(p.get('models') or [])} models"), (len(p.get("usersUsage") or []) > 0, f"{len(p.get('usersUsage') or [])} users"),
                      (len(p.get("deployedAiResources") or []) > 0, f"{len(p.get('deployedAiResources') or [])} apps/resources")):
        if cnt:
            reasons.append(text)
    if reasons:
        return " · ".join(reasons[:3])
    if p.get("skippedNoBilling"):
        return "No active Billing ($0)"
    if p.get("scanStatus") == "NO_PERMISSIONS_403":
        return "Missing IAM permissions (403)"
    if p.get("aiActive"):
        return "AI APIs enabled (0 traffic in the period)"
    return "No AI APIs enabled"


def build_demo_sync_registry_entries(projects: list[dict], ref: date) -> dict:
    """Registry entries (``projects_sync_registry.json``) of the demo account: the same fields that
    ``update_registry_entry_from_project`` (backend/sync_registry.py) writes, for the first scan of a project."""
    scanned_at = _iso(ref, 0, 6)
    entries: dict = {}
    for p in projects:
        pid = p["projectId"]
        is_err = p.get("scanStatus") == "ERROR"
        has_data = _project_has_ai_data(p)
        reason = _project_data_reason(p)
        if is_err and p.get("transientError"):
            has_data = True
            reason = "Check not completed (Google request limit): will retry on the next scan"
        is_new = pid in NEW_PROJECT_IDS
        manual = pid in MANUAL_INCLUDE_IDS
        entries[pid] = {
            "projectId": pid, "name": p.get("name") or pid, "hasAiData": has_data,
            "scanEnabled": True if manual else bool(has_data), "scanRule": "MANUAL_INCLUDE" if manual else ("AUTO_INCLUDE_HAS_DATA" if has_data else "AUTO_EXCLUDE_NO_DATA"),
            "dataReason": reason, "isNewProject": is_new, "firstSeenAt": _iso(ref, 3 if is_new else 120, 6), "lastScannedAt": scanned_at,
            "billingEnabled": bool(p.get("billingEnabled", False)), "skippedNoBilling": bool(p.get("skippedNoBilling", False)), "aiActive": bool(p.get("aiActive", False)),
            "scanStatus": p.get("scanStatus", "OK"), "estimatedCostUsd": round(p.get("estimatedCostUsd", 0.0) or 0.0, 4),
            "inferenceRequests": int(p.get("inferenceRequests", 0) or 0), "totalRequests": int(p.get("totalRequests", 0) or 0), "totalTokens": int(p.get("totalTokens", 0) or 0),
            "modelsCount": len(p.get("models", []) or []), "usersCount": len(p.get("usersUsage", []) or []), "resourcesCount": len(p.get("deployedAiResources", []) or []),
            "apiKeysCount": len(p.get("apiKeys", []) or []), "serviceAccountsCount": len(p.get("serviceAccounts", []) or []), "enabledApisCount": len(p.get("enabledAiApis", []) or []),
        }
    return entries


def build_demo_sync_registry(projects: list[dict], ref: date) -> dict:
    """Content of ``projects_sync_registry.json`` for the demo account."""
    entries = build_demo_sync_registry_entries(projects, ref)
    scanned_at = _iso(ref, 0, 6)
    return {
        "accounts": {DEMO_ACCOUNT: {"account": DEMO_ACCOUNT, "bootstrappedAt": _iso(ref, 120, 6), "lastSyncAt": scanned_at,
                                    "newProjectsDetected": [pid for pid, e in entries.items() if e["isNewProject"]], "projects": entries}},
        "updatedAt": scanned_at,
    }


def _sync_block(projects: list[dict], ref: date) -> dict:
    """Same fields as ``build_sync_summary_for_account`` plus the scan-mode counters added by the live scan."""
    reg = build_demo_sync_registry(projects, ref)["accounts"][DEMO_ACCOUNT]
    items = list(reg["projects"].values())
    items.sort(key=lambda x: (bool(x["isNewProject"]), bool(x["scanEnabled"]), bool(x["hasAiData"]), x["estimatedCostUsd"], x["totalTokens"],
                              x["inferenceRequests"], x["projectId"]), reverse=True)
    included = [x for x in items if x["scanEnabled"]]
    with_data = [x for x in items if x["hasAiData"]]
    return {
        "account": DEMO_ACCOUNT, "lastSyncAt": reg["lastSyncAt"], "totalSynchronized": len(items), "includedToScanCount": len(included),
        "excludedFromScanCount": len(items) - len(included), "withAiDataCount": len(with_data), "withoutAiDataCount": len(items) - len(with_data),
        "manualOverridesCount": sum(1 for x in items if str(x["scanRule"]).startswith("MANUAL_")), "newProjectsCount": sum(1 for x in items if x["isNewProject"]),
        "newProjectsDetected": reg["newProjectsDetected"], "projects": items, "lastScanMode": "smart",
        "scannedLiveCount": len(included), "reusedFromCacheCount": 0,
    }


def _attach_sync_meta(projects: list[dict], ref: date) -> None:
    """``syncMeta`` of every project, as ``_attach_sync_meta_to_projects`` (backend/http_routes.py) writes it."""
    entries = build_demo_sync_registry_entries(projects, ref)
    for p in projects:
        e = entries.get(p["projectId"])
        if e:
            p["syncMeta"] = {"scanEnabled": e["scanEnabled"], "hasAiData": e["hasAiData"], "scanRule": e["scanRule"], "dataReason": e["dataReason"],
                             "isNewProject": e["isNewProject"], "lastScannedAt": e["lastScannedAt"]}


def build_demo_auth_status(reference_date: str = DEFAULT_REFERENCE_DATE, session_id: str = "demo-session") -> dict:
    """Invented authentication state, same shape as the ``auth`` object of ``/api/auth/status`` (no real token)."""
    return {
        "accounts": [{"account": DEMO_ACCOUNT, "active": True, "loginDate": reference_date, "dailyExpiresAtIso": "23:59"}],
        "activeAccount": DEMO_ACCOUNT, "tokenValid": True, "needsLogin": False, "tokenError": None, "loginDate": reference_date,
        "dailyExpiresAtIso": "23:59", "sessionId": session_id, "sessionToken": session_id, "dailyZeroTrust": True,
        "usdToEurRate": FAKE_USD_TO_EUR,
    }


def build_demo_token_store(login_date: str, session_id: str, now_ts: float, daily_expires_ts: float) -> dict:
    """Content of ``oauth_tokens.json`` for demo mode: one account logged in today, a placeholder access token that is
    never valid anywhere and NO refresh token (nothing here can authenticate against Google)."""
    return {"accounts": {DEMO_ACCOUNT: {
        "email": DEMO_ACCOUNT, "access_token": "demo-access-token-not-valid", "refresh_token": None,
        "expires_at": daily_expires_ts, "login_date": login_date, "daily_expires_at": daily_expires_ts,
        "daily_expires_at_iso": "23:59", "session_id": session_id, "needs_reauth": False, "demo": True,
    }}}


def build_demo_models_pricing_config(reference_date: str = DEFAULT_REFERENCE_DATE, base: dict | None = None) -> dict:
    """Content of ``models_pricing_config.json`` for demo mode, in the shape ``load_models_pricing_config`` returns and
    ``sanitize_models_pricing_config_for_http`` serves to ``/api/models-pricing`` (``config``). With ``base`` (the
    backend's own default config) its models are reused, so the list is the one a fresh install shows; the models the demo
    traffic uses are priced like the demo costs and marked as read from the (invented) price catalog sync."""
    stamp = f"{reference_date}T06:00:00+00:00"

    def entry(mid: str, p_in: float, p_out: float) -> dict:
        cache = round(p_in * 0.25, 5)
        return {
            "modelId": mid, "displayName": mid, "publisher": "anthropic" if "claude" in mid else "google", "input": p_in, "output": p_out,
            "thinking": p_out, "cache_read_input": cache, "regional_input": round(p_in * 1.1, 4), "regional_output": round(p_out * 1.1, 4),
            "regional_thinking": round(p_out * 1.1, 4), "regional_cache_read_input": round(cache * 1.1, 4), "source": "GCP_BILLING_API:C7E2-9256-1C43",
            "lastSkuIdGlobal": "", "lastSkuIdRegional": "", "updatedAt": stamp,
        }

    demo_cal = {
        "activeSource": "DEFAULT_LIST_PRICES",
        "manualOverride": False,
        "bigqueryAutoSync": False,
        "bigqueryStatus": "NOT_FOUND",
        "bigqueryCheckedAt": stamp,
        "billingExportTable": "",
        "discoveredTable": "",
        "jobProject": "",
        "deniedTargets": [],
        "bigqueryMessage": (
            "Demo mode runs offline without Google Cloud API access. "
            "You can upload a sample Cloud Billing CSV report or adjust billing parameters locally in this temporary demo session."
        ),
        "calibratedAt": None,
        "csvFiles": [],
        "windowDays": 30,
        "rowCount": 0,
        "derivedSettings": {},
        "perModelGeminiCacheCount": 0,
        "notes": [],
    }

    if base is not None:
        cfg = json.loads(json.dumps(base))
        cfg["updatedAt"] = stamp
        for m in cfg.get("models", {}).values():
            if isinstance(m, dict):
                m["updatedAt"] = stamp
        for mid, (p_in, p_out) in MODEL_PRICES.items():  # every model the demo traffic uses is priced like the demo costs
            cfg["models"][mid] = entry(mid, p_in, p_out)
        cfg["billingCalibration"] = dict(demo_cal)
        cfg["lastApiSync"].update({"syncedAt": stamp, "skusScanned": 1240, "skusMatched": len(MODEL_PRICES), "publisherModelsDiscovered": len(cfg["models"]),
                                   "totalConfiguredModels": len(cfg["models"])})
        return cfg
    models = {mid: entry(mid, p_in, p_out) for mid, (p_in, p_out) in MODEL_PRICES.items()}
    return {
        "schemaVersion": "1.0", "updatedAt": stamp,
        "sourceServices": {"vertexAiServiceId": "C7E2-9256-1C43", "geminiApiServiceId": "AEFD-7695-64FA",
                           "publisherModelsApi": "https://aiplatform.googleapis.com/v1beta1/publishers/google/models"},
        "billingSettings": {"vertexBillingCreditDiscountPct": 0.0, "geminiApiBillingCreditDiscountPct": 0.0, "vertexImplicitCacheHitRatioPct": 93.0,
                            "regionalMultiplierDefault": 1.10, "managedServiceSavingsPct": 0.0,
                            "geminiApiImplicitCacheHitRatioPct": 0.0, "usdToEurRate": FAKE_USD_TO_EUR, "usdToEurRateAuto": True},
        "billingCalibration": dict(demo_cal),
        "oauthClientOwners": {},
        "lastApiSync": {"syncedAt": stamp, "skusScanned": 1240, "skusMatched": len(models), "publisherModelsDiscovered": len(models),
                        "totalConfiguredModels": len(models), "partial": False, "errors": []},
        "models": models,
    }


def build_demo_scan_payload(days: int = 30, seed: int = DEFAULT_SEED, reference_date: str = DEFAULT_REFERENCE_DATE, enrich: bool = True, enricher=None) -> dict:
    """Invented ``/api/scan`` payload for the fictitious company "Acme Corp".

    Deterministic: the same ``(days, seed, reference_date)`` always produce the same payload. ``reference_date`` is
    the last day of the window (the wall clock is never read). With ``enrich=True`` (default) the project's own
    backend enrichment is applied: the ``enricher`` callable when given (demo mode passes the running app's own
    ``enrich_scan_payload_security``), otherwise a private copy of the backend is loaded; if that is not possible the
    payload is returned un-enriched.
    """
    days = max(1, int(days))
    ref = date.fromisoformat(reference_date)
    days_list = [ref - timedelta(days=days - 1 - i) for i in range(days)]
    projects: list[dict] = []
    for spec in _project_specs(ref):
        if spec.get("denied"):
            p = _build_unscanned_project(spec, ref, "denied")
        elif spec.get("unverified"):
            p = _build_unscanned_project(spec, ref, "unverified")
        elif spec.get("no_billing") and not spec.get("streams"):
            p = _build_unscanned_project(spec, ref, "no_billing")
        else:
            p = _build_active_project(spec, days_list, ref, seed)
        projects.append(p)
    _sort_projects(projects)
    _attach_sync_meta(projects, ref)
    scanned_at = f"{ref.isoformat()}T06:30:00+00:00"
    payload = {
        "success": True, "scannedAt": scanned_at, "elapsedSeconds": 42.17, "days": days,
        "auth": {k: v for k, v in build_demo_auth_status(reference_date).items() if k in ("accounts", "activeAccount", "tokenValid")},
        "summary": _build_summary(projects), "timeline": _timeline(projects), "projects": projects, "sync": _sync_block(projects, ref),
        "periodRange": {"days": days, "startDate": days_list[0].isoformat(), "endDate": ref.isoformat()},
        "fromCache": False, "scanMode": "smart",
        "demo": {"company": COMPANY, "seed": seed, "referenceDate": reference_date, "enriched": False},
    }
    if enrich:
        enricher = enricher or _load_backend_enricher(ref)
        if enricher is not None:
            enricher(payload)
            payload["demo"]["enriched"] = True
    return payload


# ---------------------------------------------------------------------------------------------------------
# Optional enrichment through the project's own backend (frozen clock, private namespace)
# ---------------------------------------------------------------------------------------------------------


def _load_backend_enricher(ref: date):
    root = Path(__file__).resolve().parent.parent
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import server  # noqa: PLC0415 - imported lazily: the generator itself needs only the standard library

        # The flag tells backend/demo_mode.py this private copy is only used to enrich a payload: it stays inert (a throw-away
        # temporary DATA_DIR, nothing populated, no server), so it can never touch <repo>/data.
        ns = {"__name__": "janustower_demo", "__file__": server.__file__, "_JT_DEMO_ENRICH_ONLY": True}
        server.load_backend_modules(ns)
        enricher = ns["enrich_scan_payload_security"]
    except Exception:  # noqa: BLE001 - missing optional dependencies: fall back to the un-enriched payload
        return None
    frozen = datetime(ref.year, ref.month, ref.day, 12, 0, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return frozen.replace(tzinfo=None)

    ns["datetime"] = _FrozenDatetime
    return enricher


# ---------------------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------------------


def _outside_repo(path: Path) -> bool:
    root = Path(__file__).resolve().parent.parent
    resolved = path.resolve()
    return root != resolved and root not in resolved.parents


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write invented JanusTower demo data (Acme Corp) as JSON, outside the repository.")
    ap.add_argument("--output", required=True, help="where to write the scan payload JSON (must be outside the repository)")
    ap.add_argument("--auth-output", help="optional: where to write the invented auth status JSON (outside the repository)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--reference-date", default=DEFAULT_REFERENCE_DATE, help="last day of the window, YYYY-MM-DD (default: fixed)")
    ap.add_argument("--no-enrich", action="store_true", help="skip the backend enrichment step")
    args = ap.parse_args(argv)

    targets = [Path(args.output)] + ([Path(args.auth_output)] if args.auth_output else [])
    for t in targets:
        if not _outside_repo(t):
            print(f"Refusing to write inside the repository: {t}", file=sys.stderr)
            return 2
    payload = build_demo_scan_payload(days=args.days, seed=args.seed, reference_date=args.reference_date, enrich=not args.no_enrich)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.auth_output:
        Path(args.auth_output).write_text(json.dumps(build_demo_auth_status(args.reference_date), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {args.output} ({len(payload['projects'])} projects, {len(payload['timeline'])} days, enriched={payload['demo']['enriched']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
