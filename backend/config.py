import os
import sys
import json
import math
import re
import time
import base64
import secrets
import logging
import threading
import contextlib
import http.client
import urllib.request
import urllib.parse
import urllib.error
from http.cookies import SimpleCookie
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    with contextlib.suppress(OSError, ValueError, AttributeError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if "is_demo_mode" not in globals():
    # `import backend.config` on its own (not through server.py): load the demo switch the way server.py does.
    _demo_mode_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_mode.py")
    with open(_demo_mode_path, "r", encoding="utf-8") as _demo_f:
        exec(compile(_demo_f.read(), _demo_mode_path, "exec"), globals())  # noqa: S102  # nosec B102 - fixed repository file

IS_FROZEN = getattr(sys, "frozen", False)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_THIS_DIR).lower() == "backend":
    _THIS_DIR = os.path.dirname(_THIS_DIR)
RESOURCE_DIR = getattr(sys, "_MEIPASS", _THIS_DIR)
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if IS_FROZEN else _THIS_DIR


def load_dotenv_file(path: str) -> None:
    """Minimal .env reader (KEY=VALUE per line, # comments). Real environment variables always win."""
    if not os.path.isfile(path):
        return
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
                os.environ.setdefault(key, value)


# Demo mode (backend/demo_mode.py, decided once at startup): `.env` is not read, the data directory is a temporary
# folder outside the repository and the Host allow-list is fixed to the loopback names.
if not is_demo_mode():
    load_dotenv_file(os.path.join(BASE_DIR, ".env"))
# HOST is honoured in demo too: the demo holds only invented data, and the Docker image needs HOST=0.0.0.0 inside the
# container (compose publishes the port on the host's loopback only). The default stays 127.0.0.1.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8888 if IS_FROZEN else 8095))
DATA_DIR = DEMO_DATA_DIR if is_demo_mode() else os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
BUDGETS_FILE = os.path.join(DATA_DIR, "budgets_config.json")
MODELS_PRICING_FILE = os.path.join(DATA_DIR, "models_pricing_config.json")
CACHE_FILE = os.path.join(DATA_DIR, "last_scan_cache.json")
TOKENS_FILE = os.path.join(DATA_DIR, "oauth_tokens.json")
COOKIE_NAME = f"gcp_monitor_account_{PORT}"
SESSION_COOKIE_NAME = f"gcp_monitor_sid_{PORT}"
OAUTH_STATE_COOKIE_NAME = f"gcp_oauth_state_{PORT}"
RAM_PAYLOAD_CACHE = {}
_MODELS_PRICING_MEM_CACHE = {"mtime": 0.0, "data": None}
MODELS_PRICING_SYNC_LOCK = threading.Lock()
_MODEL_ID_VALID_RE = re.compile(r"^[a-z0-9._-]{1,80}$")

# Your own OAuth client (type "Desktop app", supports loopback /oauth2callback on any port).
# No built-in default: if it is not configured, login fails closed (see /auth/google/start).
LOOPBACK_HOST = "localhost" if is_demo_mode() else os.environ.get("LOOPBACK_HOST", "localhost")
# Demo mode never holds a real OAuth client in memory, even if one is present in the environment.
OAUTH_CLIENT_ID = "" if is_demo_mode() else os.environ.get("GCP_OAUTH_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = "" if is_demo_mode() else os.environ.get("GCP_OAUTH_CLIENT_SECRET", "").strip()
OAUTH_CONFIGURED = bool(OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET)
OAUTH_NOT_CONFIGURED_MSG = (
    "OAuth client not configured: set GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET "
    "in .env (see README, section 'Create your OAuth client')."
)
OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform"
]
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", f"http://{LOOPBACK_HOST}:{PORT}/oauth2callback")

# Default Billing & Calibration Settings (overridable in data/models_pricing_config.json)
DEFAULT_BILLING_SETTINGS = {
    "vertexBillingCreditDiscountPct": 0.0,
    "geminiApiBillingCreditDiscountPct": 0.0,
    # Typical share of Vertex AI input tokens billed at the cached rate (Gemini implicit caching); calibrate it on your billing export
    "vertexImplicitCacheHitRatioPct": 93.0,
    "regionalMultiplierDefault": 1.10,
    "managedServiceSavingsPct": 0.0,
    "geminiApiImplicitCacheHitRatioPct": 0.0,
    "usdToEurRate": 0.92,
    "usdToEurRateAuto": True,
}

# Optional OAuth 2.0 Client ID -> owner mapping (overridable in data/models_pricing_config.json)
DEFAULT_OAUTH_CLIENT_OWNERS = {}

# Default fallback rates — NOT YET VERIFIED; override via data/models_pricing_config.json or Cloud Billing sync.
# Indicative list prices (USD per 1M tokens), used ONLY for cost ESTIMATES.
# Source to check against: https://cloud.google.com/vertex-ai/generative-ai/pricing
# Last verified against the official price list: NOT YET VERIFIED.
MODEL_PRICING_PER_1M = {
    "gemini-4-argon": {"input": 0.56, "output": 2.80, "thinking": 2.80, "cache_read_input": 0.14},
    "gemini-3.8-flash": {"input": 0.30, "output": 2.50, "thinking": 2.50, "cache_read_input": 0.075},
    "gemini-3.1-pro": {"input": 1.25, "output": 10.00, "thinking": 10.00, "cache_read_input": 0.3125},
    "gemini-3.1-flash-lite": {"input": 0.10, "output": 0.40, "thinking": 0.40, "cache_read_input": 0.025},
    "gemini-3.0-pro": {"input": 1.25, "output": 10.00, "thinking": 10.00, "cache_read_input": 0.3125},
    "gemini-3.0-flash": {"input": 0.30, "output": 2.50, "thinking": 2.50, "cache_read_input": 0.075},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "thinking": 10.00, "cache_read_input": 0.3125},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50, "thinking": 2.50, "cache_read_input": 0.075},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40, "thinking": 0.40, "cache_read_input": 0.025},
    "gemini-2.0-flash": {"input": 0.15, "output": 0.60, "thinking": 0.60, "cache_read_input": 0.0375},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30, "thinking": 0.30, "cache_read_input": 0.01875},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "thinking": 5.00, "cache_read_input": 0.3125},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "thinking": 0.30, "cache_read_input": 0.01875},
    # Generative Media (Veo 3.1 Video, Lyria 3 Audio, Imagen 3/4)
    "veo-3.1": {"input": 2.50, "output": 20.00, "thinking": 20.00, "cache_read_input": 0.50},
    "veo-3.0": {"input": 2.50, "output": 20.00, "thinking": 20.00, "cache_read_input": 0.50},
    "veo-2.0": {"input": 2.00, "output": 15.00, "thinking": 15.00, "cache_read_input": 0.50},
    "lyria-3": {"input": 1.00, "output": 8.00, "thinking": 8.00, "cache_read_input": 0.25},
    "lyria": {"input": 1.00, "output": 8.00, "thinking": 8.00, "cache_read_input": 0.25},
    "imagen-4": {"input": 1.00, "output": 10.00, "thinking": 10.00, "cache_read_input": 0.25},
    "imagen-3": {"input": 0.80, "output": 8.00, "thinking": 8.00, "cache_read_input": 0.20},
    # Partner Models on Vertex AI Model Garden (Anthropic Claude, xAI Grok, Mistral, AI21)
    "claude-opus-4": {"input": 15.00, "output": 75.00, "thinking": 75.00, "cache_read_input": 1.50},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "thinking": 15.00, "cache_read_input": 0.30},
    "claude-3-7-sonnet": {"input": 3.00, "output": 15.00, "thinking": 15.00, "cache_read_input": 0.30},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00, "thinking": 15.00, "cache_read_input": 0.30},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00, "thinking": 4.00, "cache_read_input": 0.08},
    "claude-3-opus": {"input": 15.00, "output": 75.00, "thinking": 75.00, "cache_read_input": 1.50},
    "grok-3": {"input": 3.00, "output": 15.00, "thinking": 15.00, "cache_read_input": 0.75},
    "mistral-large": {"input": 2.00, "output": 6.00, "thinking": 6.00, "cache_read_input": 0.50},
    "codestral": {"input": 0.30, "output": 0.90, "thinking": 0.90, "cache_read_input": 0.10},
    # Open Models on Vertex AI (Llama, DeepSeek, Qwen, Gemma)
    "deepseek-r1": {"input": 0.55, "output": 2.19, "thinking": 2.19, "cache_read_input": 0.14},
    "deepseek-v3": {"input": 0.27, "output": 1.10, "thinking": 1.10, "cache_read_input": 0.07},
    "llama-4": {"input": 0.50, "output": 1.50, "thinking": 1.50, "cache_read_input": 0.12},
    "llama-3.3": {"input": 0.60, "output": 0.60, "thinking": 0.60, "cache_read_input": 0.15},
    "llama-3.1": {"input": 0.60, "output": 0.60, "thinking": 0.60, "cache_read_input": 0.15},
    "qwen": {"input": 0.40, "output": 1.20, "thinking": 1.20, "cache_read_input": 0.10},
    "gemma": {"input": 0.10, "output": 0.30, "thinking": 0.30, "cache_read_input": 0.025},
    "default": {"input": 0.50, "output": 2.50, "thinking": 2.50, "cache_read_input": 0.10}
}

# Standard estimation profile for direct AI Studio / Gemini API (generativelanguage.googleapis.com)
GEMINI_API_EST_INPUT_TOKENS_PER_CALL = 2800
GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL = 700
GEMINI_API_EST_COST_PER_OK_CALL = (
    (GEMINI_API_EST_INPUT_TOKENS_PER_CALL / 1_000_000.0) * MODEL_PRICING_PER_1M["gemini-2.5-flash"]["input"] +
    (GEMINI_API_EST_OUTPUT_TOKENS_PER_CALL / 1_000_000.0) * MODEL_PRICING_PER_1M["gemini-2.5-flash"]["output"]
)

# Core AI / Vertex / Gemini Enterprise Agent Platform / Model Armor APIs catalog
AI_SERVICES_CATALOG = {
    "aiplatform.googleapis.com": {
        "label": "Vertex AI & Gemini Enterprise Agent Platform",
        "category": "CORE_VERTEX",
        "icon": "🧠",
        "description": "Piattaforma centrale Vertex AI (Gemini 3.1/2.5, Model Garden, Agent Engine, RAG, Vector Search, Endpoints, Colab Enterprise)"
    },
    "generativelanguage.googleapis.com": {
        "label": "Gemini API (Google AI Studio)",
        "category": "CORE_AI",
        "icon": "✨",
        "description": "Direct Gemini API / Google AI Studio (often invoked via API Key without IAM/VPC-SC)"
    },
    "modelarmor.googleapis.com": {
        "label": "Google Cloud Model Armor",
        "category": "AI_SECURITY",
        "icon": "🛡️",
        "description": "Inline Prompt Injection, Jailbreak, RAI Filter, DLP/SDP and Malicious URI protection for LLMs and Agents"
    },
    "discoveryengine.googleapis.com": {
        "label": "Google Agentspace / Vertex AI Search & NotebookLM",
        "category": "VERTEX_FEATURE",
        "icon": "🌐",
        "description": "Enterprise engine for Agentspace, Vertex AI Search, NotebookLM Enterprise and RAG DataStores"
    },
    "dialogflow.googleapis.com": {
        "label": "Dialogflow CX / Conversational Agents (LLM Playbooks)",
        "category": "VERTEX_FEATURE",
        "icon": "🗣️",
        "description": "Enterprise conversational agents, LLM Generative Playbooks, voicebots and chatbots on Vertex AI"
    },
    "ces.googleapis.com": {
        "label": "Customer Engagement Suite (Conversational Agents v2)",
        "category": "VERTEX_FEATURE",
        "icon": "💬",
        "description": "New Google Cloud Customer Engagement Suite & Next-Gen Conversational Agents platform"
    },
    "contactcenterinsights.googleapis.com": {
        "label": "Contact Center AI Insights (CCAI)",
        "category": "VERTEX_FEATURE",
        "icon": "🎧",
        "description": "Conversation analytics, sentiment and generative summarization for Contact Centers"
    },
    "agentregistry.googleapis.com": {
        "label": "Google Cloud Agent Registry (Agents & MCP Servers)",
        "category": "AGENT_PLATFORM",
        "icon": "📇",
        "description": "Centralized Gemini Enterprise Agent Platform registry for discovery and governance of AI Agents, MCP Servers and Skills"
    },
    "notebooks.googleapis.com": {
        "label": "Vertex AI Workbench (Notebooks)",
        "category": "VERTEX_FEATURE",
        "icon": "📓",
        "description": "Managed JupyterLab instances on Vertex AI Workbench for Data Science and ML"
    },
    "geminicodeassistmanagement.googleapis.com": {
        "label": "Gemini Code Assist Management",
        "category": "GEMINI_ASSIST",
        "icon": "💻",
        "description": "License management and telemetry for Gemini Code Assist developers"
    },
    "geminidataanalytics.googleapis.com": {
        "label": "Gemini in BigQuery & Data Analytics",
        "category": "GEMINI_ASSIST",
        "icon": "📊",
        "description": "Generative AI features for BigQuery, Looker and data analysis"
    },
    "documentai.googleapis.com": {
        "label": "Cloud Document AI",
        "category": "SPECIALIZED_AI",
        "icon": "📄",
        "description": "Structured extraction and intelligent OCR from documents and PDFs"
    },
    "vision.googleapis.com": {
        "label": "Cloud Vision AI",
        "category": "SPECIALIZED_AI",
        "icon": "👁️",
        "description": "Analisi immagini, OCR e classificazione visiva"
    },
    "visionai.googleapis.com": {
        "label": "Vertex AI Vision",
        "category": "VERTEX_FEATURE",
        "icon": "🎥",
        "description": "Video stream analysis and computer vision on Vertex AI"
    },
    "speech.googleapis.com": {
        "label": "Cloud Speech-to-Text AI",
        "category": "SPECIALIZED_AI",
        "icon": "🎙️",
        "description": "Trascrizione audio-testo tramite modelli Chirp / Speech AI"
    },
    "texttospeech.googleapis.com": {
        "label": "Cloud Text-to-Speech AI",
        "category": "SPECIALIZED_AI",
        "icon": "🔊",
        "description": "Sintesi vocale neurale e voci Journey/Studio"
    },
    "translate.googleapis.com": {
        "label": "Cloud Translation AI",
        "category": "SPECIALIZED_AI",
        "icon": "🌍",
        "description": "Traduzione neurale adattiva e LLM Translation"
    },
    "cloudaicompanion.googleapis.com": {
        "label": "Gemini Code Assist & Cloud Assist",
        "category": "CONSOLE_COMPANION",
        "icon": "💻",
        "description": "Code generation (GenerateCode / Chat) and Gemini assistant for Google Cloud"
    },
    "geminicloudassist.googleapis.com": {
        "label": "Gemini Cloud Assist API",
        "category": "CONSOLE_COMPANION",
        "icon": "☁️",
        "description": "Gemini operational support service for Google Cloud"
    },
    # Gemini Enterprise Agent Platform Governance & Security Support APIs
    "dlp.googleapis.com": {
        "label": "Sensitive Data Protection (Cloud DLP / SDP for AI)",
        "category": "AI_GOVERNANCE_SUPPORT",
        "icon": "🕵️",
        "description": "Inspection and de-identification of sensitive data/PII in prompts and responses via Model Armor SDP"
    },
    "iap.googleapis.com": {
        "label": "Identity-Aware Proxy (Agent Gateway UAP)",
        "category": "AI_GOVERNANCE_SUPPORT",
        "icon": "🚪",
        "description": "Zero-Trust access control and Unified Access Policies (UAP) for Agent Gateway (user -> agent -> MCP)"
    },
    "networksecurity.googleapis.com": {
        "label": "Cloud Network Security (Agent Gateway Policies)",
        "category": "AI_GOVERNANCE_SUPPORT",
        "icon": "🧱",
        "description": "Network security policies and semantic governance for Agent Gateway on Gemini Enterprise Agent Platform"
    },
    "serviceextensions.googleapis.com": {
        "label": "Service Extensions (Agent Gateway Inline Callouts)",
        "category": "AI_GOVERNANCE_SUPPORT",
        "icon": "🔌",
        "description": "Inline extensions for Agent Gateway traffic interception and synchronous Model Armor invocation"
    }
}

# Core AI APIs that qualify a project as having real AI / Vertex / Gemini / Code Assist active (excluding generic non-AI infra APIs alone)
CORE_AI_SERVICE_NAMES = {
    k for k, v in AI_SERVICES_CATALOG.items()
    if v["category"] not in ("AI_GOVERNANCE_SUPPORT",)
}

INFERENCE_METHOD_KEYWORDS = (
    "generatecontent",
    "streamgeneratecontent",
    "chatcompletions",
    "predict",
    "rawpredict",
    "streamrawpredict",
    "directpredict",
    "streamdirectpredict",
    "explain",
    "embedcontent",
    "batchembedcontents",
    "counttokens",
    "streamqueryreasoningengine",
    "queryreasoningengine",
    "retrievecontexts",
    "generateanswer",
    "answerquery",
    "streamassist",
    "asyncassist",
    "recommendquestions",
    "generatefreeformstreamed",
    "generatenotebookguide",
    "generatedocumentguides",
    "getaudiooverview",
    "search",
    "converse",
    "detectintent",
    "streamingdetectintent",
    "matchintent",
    "fulfillintent",
    "synthesize",
    "recognize",
    "processdocument",
    "batchprocessdocuments",
    "annotateimage",
    "translatetext",
    "adaptivemttranslate",
    "generatecode",
    "completecode",
    "generatechat",
    "sendstreamingmessage",
    "sendmessage",
    "sanitizeuserprompt",
    "sanitizemodelresponse"
)


def is_inference_method(method_name: str) -> bool:
    if not method_name:
        return False
    short = method_name.split(".")[-1].lower()
    if (
        short.startswith("list") or
        short.startswith("get") and short != "getaudiooverview" or
        short.startswith("check") or
        short.startswith("delete") or
        short.startswith("update") or
        short.startswith("create") or
        short.startswith("export") or
        short.startswith("import") or
        short in ("advancedcompletequery", "completequery", "fetchuserprofile", "logevents", "collect", "reportruntimeevent")
    ):
        return False
    return any(k in short for k in INFERENCE_METHOD_KEYWORDS)


def estimate_service_call_cost(service: str, method: str) -> tuple[float, int, int, str, str]:
    """
    Estimates per-call USD cost and token equivalent (if applicable) for managed Google Cloud AI services
    that bill per request / session turn / query rather than via aiplatform token_count metrics.
    Returns: (cost_per_call_usd, est_input_tokens_per_call, est_output_tokens_per_call, model_entry_id, cost_source_label)
    Note: For Dialogflow CX, LLM tokens are ALSO fetched directly from
    dialogflow.googleapis.com/quota/ConversationalAgent*LLMTokenConsumption/usage in Step 3c,
    so est_input_tokens_per_call is 0 here to avoid double-counting tokens while accurately billing
    the $0.012/request Dialogflow CX Generative Session/Turn fee!
    """
    m_low = (method or "").lower()
    short_m = method.split(".")[-1].lower() if method else ""

    if service in ("dialogflow.googleapis.com", "ces.googleapis.com"):
        if any(k in short_m for k in ("detectintent", "streamingdetectintent", "matchintent", "fulfillintent")):
            # Official GCP Dialogflow CX Generative Agent / Chat turn rate: $0.012 per request ($12 / 1,000 requests)
            return (0.012, 0, 0, "Dialogflow CX Session Turns (DetectIntent)", "DIALOGFLOW_CX")

    elif service == "discoveryengine.googleapis.com":
        if any(k in short_m for k in ("streamassist", "asyncassist", "generateanswer", "answerquery", "converse")):
            # Agentspace Generative Assistant / Grounded Answer turn (~$0.004/turn + ~2,250 LLM tokens)
            return (0.004, 1800, 450, "Agentspace Assistant (StreamAssist / Gemini)", "AGENTSPACE")
        if any(k in short_m for k in ("generatefreeformstreamed", "generatenotebookguide", "generatedocumentguides", "getaudiooverview")):
            # NotebookLM Enterprise generative guide / audio overview / chat
            return (0.010, 3000, 800, "NotebookLM Enterprise (Gemini Generation)", "NOTEBOOKLM")
        if "notebooklmsearch" in m_low:
            return (0.0015, 0, 0, "NotebookLM Enterprise Search", "NOTEBOOKLM")
        if "search" in short_m:
            # Enterprise Search query ($1.50 / 1,000 queries)
            return (0.0015, 0, 0, "Agentspace / Vertex AI Enterprise Search", "AGENTSPACE")
        if "recommendquestions" in short_m:
            return (0.001, 400, 100, "Agentspace RecommendQuestions (Gemini)", "AGENTSPACE")

    elif service == "modelarmor.googleapis.com":
        if "sanitize" in short_m:
            # Model Armor standalone sanitization ($1.50 / 1,000 sanitize operations above free tier)
            return (0.0015, 0, 0, "Model Armor Sanitization (Prompt/Response Shield)", "MODEL_ARMOR")

    elif service in ("cloudaicompanion.googleapis.com", "geminicloudassist.googleapis.com"):
        if any(k in short_m for k in ("generatecode", "completecode", "generatechat", "sendmessage", "sendstreamingmessage")):
            return (0.0015, 1200, 300, "Gemini Code Assist / Cloud Assist (IDE & Console)", "CODE_ASSIST")

    elif service == "speech.googleapis.com":
        if "recognize" in short_m:
            return (0.016, 0, 0, "Cloud Speech-to-Text (Chirp / Recognize)", "SPEECH_AI")

    elif service == "texttospeech.googleapis.com":
        if "synthesize" in short_m:
            return (0.004, 0, 0, "Cloud Text-to-Speech (Neural / Studio)", "TTS_AI")

    elif service == "documentai.googleapis.com":
        if "process" in short_m:
            return (0.015, 0, 0, "Cloud Document AI (ProcessDocument)", "DOCUMENT_AI")

    elif service == "vision.googleapis.com":
        if "annotate" in short_m:
            return (0.0015, 0, 0, "Cloud Vision AI (AnnotateImage)", "VISION_AI")

    elif service == "translate.googleapis.com":
        if "translate" in short_m:
            return (0.002, 0, 0, "Cloud Translation AI (TranslateText)", "TRANSLATE_AI")

    return (0.0, 0, 0, "", "")


def classify_vertex_subfeature(service: str, method: str) -> dict | None:
    """Maps a GCP service + gRPC/REST method to a human-readable Vertex AI / Gemini Enterprise Agent Platform feature."""
    m_low = (method or "").lower()
    short_m = method.split(".")[-1] if method else ""

    if service == "aiplatform.googleapis.com":
        if "reasoningengine" in m_low:
            return {
                "id": "vertex_agent_engine",
                "name": "Vertex AI Agent Engine (Reasoning Engines / ADK)",
                "category": "Gemini Agent Platform",
                "icon": "🤖",
                "description": "Execution and orchestration of AI agents on Vertex AI Agent Engine (Google ADK / LangChain / A2A)"
            }
        if "sessionservice" in m_low or "memorybank" in m_low:
            return {
                "id": "vertex_agent_sessions",
                "name": "Vertex AI Agent Sessions & Memory Bank",
                "category": "Gemini Agent Platform",
                "icon": "💬",
                "description": "Conversational state management, long-term Memory Bank and persistent sessions for Vertex AI Agents"
            }
        if "extensionexecution" in m_low or "extensionregistry" in m_low:
            return {
                "id": "vertex_agent_extensions",
                "name": "Vertex AI Agent Extensions & Tool Use",
                "category": "Gemini Agent Platform",
                "icon": "🧰",
                "description": "Invocation of tools, external APIs and connectors managed by Vertex AI Agents"
            }
        if "notebook" in m_low or "runtime" in m_low:
            return {
                "id": "vertex_colab_enterprise",
                "name": "Colab Enterprise & Vertex AI Notebooks Runtime",
                "category": "Vertex AI Notebooks",
                "icon": "📓",
                "description": "Esecuzione notebook Colab Enterprise, runtime GPU/CPU e job di esecuzione schedulati"
            }
        if "ragdata" in m_low or "vertexrag" in m_low or "ragcorpora" in m_low or "retrievecontexts" in m_low:
            return {
                "id": "vertex_rag_engine",
                "name": "Vertex AI RAG Engine (RagCorpora)",
                "category": "Vertex AI Grounding & RAG",
                "icon": "📚",
                "description": "Managed document indexing and Retrieval-Augmented Generation on Vertex AI"
            }
        if any(k in short_m.lower() for k in ("generatecontent", "streamgeneratecontent", "chatcompletions", "counttokens")):
            return {
                "id": "vertex_gemini_inference",
                "name": "Vertex AI Online Inference (Gemini / Model Garden)",
                "category": "Vertex AI LLM Inference",
                "icon": "✨",
                "description": "Direct calls to foundation models (GenerateContent, StreamGenerateContent, ChatCompletions)"
            }
        if any(k in short_m.lower() for k in ("predict", "rawpredict", "directpredict", "embedcontent", "explain")):
            return {
                "id": "vertex_custom_prediction",
                "name": "Vertex AI Prediction & Embeddings Service",
                "category": "Vertex AI ML / Embeddings",
                "icon": "📐",
                "description": "Custom prediction endpoints, One-Click Deploy models and Embeddings"
            }
        if "endpointservice" in m_low:
            return {
                "id": "vertex_endpoints",
                "name": "Vertex AI Online Endpoints",
                "category": "Vertex AI Serving",
                "icon": "🔌",
                "description": "Dedicated Endpoint management for online serving of custom or Model Garden models"
            }
        if "index" in m_low or "matchservice" in m_low:
            return {
                "id": "vertex_vector_search",
                "name": "Vertex AI Vector Search (Matching Engine)",
                "category": "Vertex AI Grounding & RAG",
                "icon": "🔎",
                "description": "High-performance ANN vector search on Vertex AI for RAG and semantic memory"
            }
        if "pipeline" in m_low or "jobservice" in m_low or "customjob" in m_low or "batchprediction" in m_low:
            return {
                "id": "vertex_pipelines_jobs",
                "name": "Vertex AI Pipelines, Training & Batch Jobs",
                "category": "Vertex AI MLOps",
                "icon": "⚙️",
                "description": "Pipeline orchestrate Kubeflow/Vertex, job di training e predizione batch"
            }
        if "tuning" in m_low:
            return {
                "id": "vertex_tuning",
                "name": "Vertex AI Supervised Fine-Tuning (SFT)",
                "category": "Vertex AI Customization",
                "icon": "🎯",
                "description": "Model training and fine-tuning on Vertex AI"
            }
        if "evaluation" in m_low:
            return {
                "id": "vertex_evaluation",
                "name": "Vertex AI GenAI Evaluation Service",
                "category": "Vertex AI MLOps",
                "icon": "📏",
                "description": "Automated evaluation of quality, safety and hallucination metrics of generative models"
            }
        if "dataset" in m_low or "modelservice" in m_low or "metadata" in m_low:
            return {
                "id": "vertex_model_registry",
                "name": "Vertex AI Model Registry & Datasets",
                "category": "Vertex AI MLOps",
                "icon": "🗂️",
                "description": "Model catalog, datasets and MLOps metadata"
            }
        if "cache" in m_low:
            return {
                "id": "vertex_context_caching",
                "name": "Vertex AI Context Caching",
                "category": "Vertex AI LLM Inference",
                "icon": "⚡",
                "description": "Prompt context caching to reduce costs (-75%) and latency on LLM calls"
            }

    if service == "agentregistry.googleapis.com":
        return {
            "id": "svc_agentregistry",
            "name": "Google Cloud Agent Registry (Agenti, MCP Server & Skill)",
            "category": "Gemini Agent Platform",
            "icon": "📇",
            "description": "Governed catalog of approved AI Agents, MCP Servers and enterprise Skills"
        }

    if service == "discoveryengine.googleapis.com":
        if "notebooklm" in m_low or "audiooverview" in m_low or "notebookguide" in m_low or "documentguides" in m_low:
            return {
                "id": "svc_notebooklm_enterprise",
                "name": "NotebookLM Enterprise (Audio Overview, Guide & Search)",
                "category": "VERTEX_FEATURE",
                "icon": "📔",
                "description": "Guide generation, document summaries, Audio Overview and NotebookLM Enterprise search"
            }
        if "assistantservice" in m_low or "streamassist" in m_low or "asyncassist" in m_low:
            return {
                "id": "svc_agentspace_assistant",
                "name": "Google Agentspace Generative Assistant (StreamAssist)",
                "category": "Gemini Agent Platform",
                "icon": "🌐",
                "description": "Enterprise Agentspace conversational assistant with grounding on enterprise DataStores"
            }

    if service in AI_SERVICES_CATALOG and service != "aiplatform.googleapis.com":
        cat = AI_SERVICES_CATALOG[service]
        return {
            "id": f"svc_{service.split('.')[0]}",
            "name": cat["label"],
            "category": cat["category"],
            "icon": cat["icon"],
            "description": cat["description"]
        }

    return None


def _build_default_models_pricing_config() -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    reg_mult = float(DEFAULT_BILLING_SETTINGS.get("regionalMultiplierDefault", 1.10) or 1.10)
    models_cfg = {}
    for m_key, m_rates in MODEL_PRICING_PER_1M.items():
        if m_key == "default":
            continue
        if not ("gemini" in m_key or "veo" in m_key or "imagen" in m_key or "lyria" in m_key or "gemma" in m_key):
            continue  # the list only shows Google models; other families keep their rates as a calculation fallback
        in_val = float(m_rates.get("input", 0.50))
        out_val = float(m_rates.get("output", 2.50))
        thk_val = float(m_rates.get("thinking", out_val))
        cache_val = float(m_rates.get("cache_read_input", 0.10))
        models_cfg[m_key] = {
            "modelId": m_key,
            "displayName": m_key,
            "publisher": "anthropic" if "claude" in m_key else ("google" if ("gemini" in m_key or "veo" in m_key or "imagen" in m_key or "lyria" in m_key or "gemma" in m_key) else "partner"),
            "input": in_val,
            "output": out_val,
            "thinking": thk_val,
            "cache_read_input": cache_val,
            "regional_input": float(m_rates.get("regional_input", round(in_val * reg_mult, 4))),
            "regional_output": float(m_rates.get("regional_output", round(out_val * reg_mult, 4))),
            "regional_thinking": float(m_rates.get("regional_thinking", round(thk_val * reg_mult, 4))),
            "regional_cache_read_input": float(m_rates.get("regional_cache_read_input", round(cache_val * reg_mult, 4))),
            "source": "BUILTIN_DEFAULT",
            "lastSkuIdGlobal": "",
            "lastSkuIdRegional": "",
            "updatedAt": now_iso,
        }
    return {
        "schemaVersion": "1.0",
        "updatedAt": now_iso,
        "sourceServices": {
            "vertexAiServiceId": "C7E2-9256-1C43",
            "geminiApiServiceId": "AEFD-7695-64FA",
            "publisherModelsApi": "https://aiplatform.googleapis.com/v1beta1/publishers/google/models",
        },
        "billingSettings": dict(DEFAULT_BILLING_SETTINGS),
        "oauthClientOwners": dict(DEFAULT_OAUTH_CLIENT_OWNERS),
        "lastApiSync": {
            "syncedAt": None,
            "skusScanned": 0,
            "skusMatched": 0,
            "publisherModelsDiscovered": 0,
            "totalConfiguredModels": len(models_cfg),
            "partial": False,
            "errors": [],
        },
        "models": models_cfg,
    }


def load_models_pricing_config() -> dict:
    if os.path.exists(MODELS_PRICING_FILE):
        with contextlib.suppress(OSError, ValueError, TypeError):
            mtime = os.path.getmtime(MODELS_PRICING_FILE)
            if _MODELS_PRICING_MEM_CACHE["data"] is not None and _MODELS_PRICING_MEM_CACHE["mtime"] == mtime:
                return _MODELS_PRICING_MEM_CACHE["data"]
            with open(MODELS_PRICING_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("models"), dict):
                default_cfg = _build_default_models_pricing_config()
                upgraded = False
                bs = dict(default_cfg["billingSettings"])
                if isinstance(loaded.get("billingSettings"), dict):
                    bs.update(loaded["billingSettings"])
                loaded["billingSettings"] = bs
                oc = dict(default_cfg["oauthClientOwners"])
                if isinstance(loaded.get("oauthClientOwners"), dict):
                    oc.update(loaded["oauthClientOwners"])
                loaded["oauthClientOwners"] = oc
                if not isinstance(loaded.get("lastApiSync"), dict):
                    loaded["lastApiSync"] = dict(default_cfg["lastApiSync"])
                    upgraded = True
                else:
                    for k_ls, v_ls in default_cfg["lastApiSync"].items():
                        if k_ls not in loaded["lastApiSync"]:
                            loaded["lastApiSync"][k_ls] = v_ls
                            upgraded = True
                for def_k, def_v in default_cfg["models"].items():
                    if def_k not in loaded["models"]:
                        if loaded.get("modelListFromApi"):
                            continue  # list is driven by the Google APIs: never resurrect removed/retired built-ins
                        loaded["models"][def_k] = def_v
                        upgraded = True
                    elif isinstance(loaded["models"][def_k], dict):
                        m_item = loaded["models"][def_k]
                        if m_item.get("source") == "DEFAULT_UNVERIFIED":
                            m_item["source"] = "BUILTIN_DEFAULT"
                            upgraded = True
                        for req_k, req_v in (
                            ("lastSkuIdGlobal", ""),
                            ("lastSkuIdRegional", ""),
                            ("updatedAt", loaded.get("updatedAt") or default_cfg["updatedAt"]),
                        ):
                            if req_k not in m_item:
                                m_item[req_k] = req_v
                                upgraded = True
                loaded["lastApiSync"]["totalConfiguredModels"] = len(loaded["models"])
                if upgraded:
                    save_models_pricing_config(loaded)
                else:
                    _MODELS_PRICING_MEM_CACHE["mtime"] = mtime
                    _MODELS_PRICING_MEM_CACHE["data"] = loaded
                return loaded
    if os.path.exists(MODELS_PRICING_FILE):
        # unreadable file: keep a dated copy before recreating defaults, never silently lose overrides
        with contextlib.suppress(OSError):
            os.replace(MODELS_PRICING_FILE, f"{MODELS_PRICING_FILE}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    cfg = _build_default_models_pricing_config()
    save_models_pricing_config(cfg)
    return cfg


def save_models_pricing_config(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    with contextlib.suppress(OSError, ValueError, TypeError):
        tmp_path = f"{MODELS_PRICING_FILE}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, MODELS_PRICING_FILE)  # atomic: a crash never leaves a truncated file
        _MODELS_PRICING_MEM_CACHE["mtime"] = os.path.getmtime(MODELS_PRICING_FILE)
        _MODELS_PRICING_MEM_CACHE["data"] = data


def sanitize_models_pricing_config_for_http(cfg: dict) -> dict:
    """Returns a copy of models_pricing_config safe for HTTP responses (excludes oauthClientOwners)."""
    if not isinstance(cfg, dict):
        return {}
    return {k: v for k, v in cfg.items() if k != "oauthClientOwners"}


def get_billing_settings() -> dict:
    cfg = load_models_pricing_config()
    return cfg.get("billingSettings") or dict(DEFAULT_BILLING_SETTINGS)


def get_usd_to_eur_rate() -> float:
    """EUR per 1 USD, used only to display euro amounts.

    With `usdToEurRateAuto` (default) it is the rate Google Cloud applies, read from the Cloud Billing
    Catalog (`currencyConversionRate`, see sync); otherwise (or if not yet synced) the manual `usdToEurRate`.
    """
    default = DEFAULT_BILLING_SETTINGS["usdToEurRate"]
    try:
        cfg = load_models_pricing_config()
        bs = cfg.get("billingSettings") or {}
        if bs.get("usdToEurRateAuto", True):
            fx = cfg.get("fxRate") if isinstance(cfg.get("fxRate"), dict) else {}
            auto_rate = fx.get("usdToEur")
            if isinstance(auto_rate, (int, float)) and not isinstance(auto_rate, bool) and 0.5 <= float(auto_rate) <= 1.5:
                return float(auto_rate)
        rate = float(bs.get("usdToEurRate", default))
    except (TypeError, ValueError, AttributeError):
        rate = default
    if not (0.5 <= rate <= 1.5):
        rate = default
    return rate


def extract_catalog_fx_rate(body: dict) -> tuple[float, str] | None:
    """(EUR per 1 USD, effective time) from a Cloud Billing Catalog SKU page requested with currencyCode=EUR."""
    for sku in (body.get("skus") or []) if isinstance(body, dict) else []:
        for pi in (sku.get("pricingInfo") or []) if isinstance(sku, dict) else []:
            rate = pi.get("currencyConversionRate") if isinstance(pi, dict) else None
            if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0.5 <= float(rate) <= 1.5 and float(rate) != 1.0:
                return round(float(rate), 6), str(pi.get("effectiveTime") or "")
    return None


def get_oauth_client_owners() -> dict:
    cfg = load_models_pricing_config()
    return cfg.get("oauthClientOwners") or dict(DEFAULT_OAUTH_CLIENT_OWNERS)


def _select_location_rates(raw_rates: dict, location: str = "global", is_estimated: bool = False) -> dict:
    loc_clean = (location or "global").strip().lower()
    # Any location other than "global" (including multi-regions "eu" and "us") uses regional rates
    is_regional = bool(loc_clean and not loc_clean.startswith("global"))
    bs = get_billing_settings()
    reg_mult = float(bs.get("regionalMultiplierDefault", 1.10) or 1.10)
    mo = raw_rates.get("manualOverride") if isinstance(raw_rates.get("manualOverride"), dict) else {}

    def _pick(key: str, default: float) -> float:
        # A manual override of 0 is a valid rate: only a missing/None value falls back.
        v = mo.get(key)
        if v is None:
            v = raw_rates.get(key)
        return float(default if v is None else v)

    in_base = _pick("input", 0.50)
    out_base = _pick("output", 2.50)
    thk_base = _pick("thinking", out_base)
    cache_base = _pick("cache_read_input", round(in_base * 0.10, 4))

    has_official_reg_sku = bool(raw_rates.get("lastSkuIdRegional"))
    has_manual_reg = any(k.startswith("regional_") for k in mo)

    if "regional_input" in mo:
        reg_in = float(mo["regional_input"])
    elif has_official_reg_sku and raw_rates.get("regional_input") is not None:
        reg_in = float(raw_rates.get("regional_input"))
    else:
        reg_in = round(in_base * reg_mult, 4)

    if "regional_output" in mo:
        reg_out = float(mo["regional_output"])
    elif has_official_reg_sku and raw_rates.get("regional_output") is not None:
        reg_out = float(raw_rates.get("regional_output"))
    else:
        reg_out = round(out_base * reg_mult, 4)

    if "regional_thinking" in mo:
        reg_thk = float(mo["regional_thinking"])
    elif has_official_reg_sku and raw_rates.get("regional_thinking") is not None:
        reg_thk = float(raw_rates.get("regional_thinking"))
    else:
        reg_thk = round(thk_base * reg_mult, 4)

    if "regional_cache_read_input" in mo:
        reg_cache = float(mo["regional_cache_read_input"])
    elif has_official_reg_sku and raw_rates.get("regional_cache_read_input") is not None:
        reg_cache = float(raw_rates.get("regional_cache_read_input"))
    else:
        reg_cache = round(cache_base * reg_mult, 4)

    if is_regional:
        eff_in, eff_out, eff_thk, eff_cache = reg_in, reg_out, reg_thk, reg_cache
    else:
        eff_in, eff_out, eff_thk, eff_cache = in_base, out_base, thk_base, cache_base

    src = "MANUAL" if mo else str(raw_rates.get("source") or ("DEFAULT_FALLBACK" if is_estimated else "BUILTIN_DEFAULT"))
    reg_calculated = bool(is_regional and not has_official_reg_sku and not has_manual_reg)
    return {
        "input": eff_in,
        "output": eff_out,
        "thinking": eff_thk,
        "cache_read_input": eff_cache,
        "global_input": in_base,
        "global_output": out_base,
        "regional_input": reg_in,
        "regional_output": reg_out,
        "implicitCacheHitRatioPct": float(raw_rates.get("implicitCacheHitRatioPct", bs.get("vertexImplicitCacheHitRatioPct", DEFAULT_BILLING_SETTINGS["vertexImplicitCacheHitRatioPct"])) or 0.0),
        "billingCreditDiscountPct": float(raw_rates.get("billingCreditDiscountPct", bs.get("vertexBillingCreditDiscountPct", 0.0)) or 0.0),
        "source": src,
        "isEstimated": bool(is_estimated or reg_calculated),
    }


def _find_model_config_entry(model_name: str) -> dict:
    """Same lookup order as get_model_rates, but returns the raw config entry (or {})."""
    m = (model_name or "").strip().lower()
    if "/" in m:
        m = m.split("/")[-1]
    if "@" in m:
        m = m.split("@")[0]
    cfg_models = load_models_pricing_config().get("models") or {}
    if isinstance(cfg_models.get(m), dict):
        return cfg_models[m]
    for key in sorted(cfg_models.keys(), key=len, reverse=True):
        if key != "default" and key in m and isinstance(cfg_models[key], dict):
            return cfg_models[key]
    return {}


def get_gemini_api_rates(model_name: str) -> dict:
    """Rates for the direct Gemini API (generativelanguage), which can differ from Vertex AI.

    Uses the model's `geminiApiRates` (filled by the Cloud Billing Catalog sync from the Gemini API
    service) unless a manual override exists; cache hit ratio comes from the model's
    `geminiApiCacheHitRatioPct` or the global `geminiApiImplicitCacheHitRatioPct` (default 0).
    """
    base = get_model_rates(model_name, "global")
    entry = _find_model_config_entry(model_name)
    rates = {
        "input": float(base["input"]),
        "output": float(base["output"]),
        "cache_read_input": float(base["cache_read_input"]),
        "source": "VERTEX_RATES",
    }
    gem = entry.get("geminiApiRates") if isinstance(entry.get("geminiApiRates"), dict) else {}
    if gem and not isinstance(entry.get("manualOverride"), dict):
        for k in ("input", "output", "cache_read_input"):
            v = gem.get(k)
            if isinstance(v, (int, float)) and v > 0:
                rates[k] = float(v)
        if "cache_read_input" not in gem and "input" in gem:
            rates["cache_read_input"] = round(rates["input"] * 0.10, 6)
        rates["source"] = "GEMINI_API_CATALOG"
    pct = entry.get("geminiApiCacheHitRatioPct")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        pct = get_billing_settings().get("geminiApiImplicitCacheHitRatioPct", 0.0)
    try:
        pct = float(pct or 0.0)
    except (TypeError, ValueError):
        pct = 0.0
    rates["cacheHitRatioPct"] = max(0.0, min(98.0, pct))
    return rates


def get_model_rates(model_name: str, location: str = "global") -> dict:
    m = (model_name or "").strip().lower()
    if "/" in m:
        m = m.split("/")[-1]
    if "@" in m:
        m = m.split("@")[0]
    cfg = load_models_pricing_config()
    cfg_models = cfg.get("models") or {}

    if m in cfg_models:
        return _select_location_rates(cfg_models[m], location)

    # Sort keys longest-first so e.g. 'gemini-2.5-flash-lite' matches before 'gemini-2.5-flash'
    for key in sorted(cfg_models.keys(), key=len, reverse=True):
        if key != "default" and key in m:
            return _select_location_rates(cfg_models[key], location)

    for key in sorted(MODEL_PRICING_PER_1M.keys(), key=len, reverse=True):
        if key != "default" and key in m:
            return _select_location_rates(MODEL_PRICING_PER_1M[key], location)

    if "veo" in m:
        return _select_location_rates(cfg_models.get("veo-3.1") or MODEL_PRICING_PER_1M["veo-3.1"], location)
    if "lyria" in m:
        return _select_location_rates(cfg_models.get("lyria-3") or MODEL_PRICING_PER_1M["lyria-3"], location)
    if "imagen" in m:
        return _select_location_rates(cfg_models.get("imagen-3") or MODEL_PRICING_PER_1M["imagen-3"], location)
    if "claude" in m and "opus" in m:
        return _select_location_rates(cfg_models.get("claude-opus-4") or MODEL_PRICING_PER_1M["claude-opus-4"], location)
    if "claude" in m and "haiku" in m:
        return _select_location_rates(cfg_models.get("claude-3-5-haiku") or MODEL_PRICING_PER_1M["claude-3-5-haiku"], location)
    if "claude" in m:
        return _select_location_rates(cfg_models.get("claude-3-7-sonnet") or MODEL_PRICING_PER_1M["claude-3-7-sonnet"], location)
    if "deepseek" in m:
        return _select_location_rates(cfg_models.get("deepseek-r1") or MODEL_PRICING_PER_1M["deepseek-r1"], location)
    if "llama" in m:
        return _select_location_rates(cfg_models.get("llama-3.3") or MODEL_PRICING_PER_1M["llama-3.3"], location)
    if "mistral" in m:
        return _select_location_rates(cfg_models.get("mistral-large") or MODEL_PRICING_PER_1M["mistral-large"], location)
    if "flash-lite" in m or "lite" in m:
        return _select_location_rates(cfg_models.get("gemini-2.5-flash-lite") or MODEL_PRICING_PER_1M["gemini-2.5-flash-lite"], location)
    if "flash" in m:
        return _select_location_rates(cfg_models.get("gemini-2.5-flash") or MODEL_PRICING_PER_1M["gemini-2.5-flash"], location)
    if "pro" in m:
        return _select_location_rates(cfg_models.get("gemini-2.5-pro") or MODEL_PRICING_PER_1M["gemini-2.5-pro"], location)
    return _select_location_rates(MODEL_PRICING_PER_1M["default"], location, is_estimated=True)


def _extract_sku_usd_per_1m(sku: dict) -> float | None:
    p_info = sku.get("pricingInfo") or []
    if not p_info:
        return None
    expr = p_info[0].get("pricingExpression") or {}
    unit_desc = (
        str(expr.get("usageUnitDescription") or "") + " " + str(expr.get("usageUnit") or "")
    ).strip().lower()
    rates = expr.get("tieredRates") or []
    if not rates:
        return None
    # Pick first non-zero tiered rate (since Gemini API free tier has tier 0 = $0 and tier 1 = paid rate)
    best_price = 0.0
    for tr in rates:
        up = tr.get("unitPrice") or {}
        val = float(up.get("units", 0) or 0) + float(up.get("nanos", 0) or 0) / 1e9
        if val > 0:
            best_price = val
            break
    if best_price <= 0:
        return None
    if "1,000,000" in unit_desc or "million" in unit_desc or "1m" in unit_desc:
        return round(best_price, 4)
    if "1,000" in unit_desc or "thousand" in unit_desc or "1k" in unit_desc:
        return round(best_price * 1000.0, 4)
    # In Cloud Billing Catalog for Vertex AI / Gemini API, token SKUs with usageUnit="count" are priced per 1M tokens
    if best_price >= 0.005:
        return round(best_price, 4)
    return round(best_price * 1_000_000.0, 4)


# ---------------------------------------------------------------------------
# Cloud Billing Catalog -> per-model rates (generic SKU reader, no hard-coded model families)
# ---------------------------------------------------------------------------
_CATALOG_SKIP_WORDS = (
    "batch", "priority", "flex", "offpeak", "off-peak", "deferred", "provisioned", "tuning", "training", "tuned",
    "grounding", "storage", "token hour", "token-hour", "over a period of time", "cache write", "cyber",
    "codemender", "contributor", "(long)", "long output", "long input", "long context", "long-context",
    "longer than", "above 128k", "above 200k", "over 128k", "over 200k", "> 128k", ">128k", "> 200k", ">200k",
    "128k+", "200k+", "1m+", "context caching", "and long", "long)", "bidi", "200001",
)
# words that may follow a model's name inside an SKU description without making it a different model
_CATALOG_STRUCT_WORDS = frozenset((
    "text", "image", "audio", "video", "input", "output", "global", "regional", "cached", "caching", "cache",
    "token", "tokens", "count", "predictions", "prediction", "online", "thinking", "generation", "standard",
    "experimental", "preview", "exp", "short", "us", "eu", "europe", "asia", "api", "for", "when", "generate",
    "content", "read", "usage", "multimodal", "response", "prompt", "candidates", "context", "window",
))
_CATALOG_MODALITIES = ("text", "image", "audio", "video")
_CATALOG_PRODUCT_WORDS = ("gemini", "claude", "imagen", "veo", "lyria", "gemma")
_ID_DROP_TOKENS = frozenset(("preview", "exp", "experimental", "latest", "default", "stable"))


def _join_version_digits(toks: list[str]) -> list[str]:
    """['claude','opus','5','5'] -> ['claude','opus','5.5']: ids and SKU names write versions both ways."""
    out: list[str] = []
    for t in toks:
        if out and re.fullmatch(r"\d", t) and re.fullmatch(r"\d", out[-1]):
            out[-1] = f"{out[-1]}.{t}"
        else:
            out.append(t)
    return out


def _catalog_id_tokens(model_id: str) -> list[str]:
    toks = [t for t in re.split(r"[-_]", str(model_id or "").lower().split("@")[0]) if t]
    return _join_version_digits([t for t in toks if t not in _ID_DROP_TOKENS and not re.fullmatch(r"\d{3}|\d{8}", t)])


def _catalog_phrase(desc: str) -> list[str]:
    toks = re.sub(r"[^a-z0-9.]+", " ", str(desc or "").lower()).split()
    for i, t in enumerate(toks):
        if t in _CATALOG_PRODUCT_WORDS:
            return _join_version_digits(toks[i:])
    return toks


def _catalog_sku_unit_price(sku: dict) -> tuple[float | None, str]:
    """First non-zero tier unit price (USD per usage unit, untouched) and its usage unit."""
    p_info = sku.get("pricingInfo") or []
    if not p_info:
        return None, ""
    expr = p_info[0].get("pricingExpression") or {}
    for tr in (expr.get("tieredRates") or []):
        up = tr.get("unitPrice") or {}
        val = float(up.get("units", 0) or 0) + float(up.get("nanos", 0) or 0) / 1e9
        if val > 0:
            return val, str(expr.get("usageUnit") or "")
    return None, str(expr.get("usageUnit") or "")


_VERSION_PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")


def _expand_version_pairs(sku: dict) -> list[dict]:
    """'Gemini 3.0 / 3.1 Pro ...' prices both versions: return one SKU copy per version."""
    desc = str(sku.get("description") or "")
    m = _VERSION_PAIR_RE.search(desc)
    if not m:
        return [sku]
    return [dict(sku, description=desc[:m.start()] + v + desc[m.end():]) for v in (m.group(1), m.group(2))]


def parse_catalog_sku(sku: dict, id_token_map: dict) -> dict | None:
    """Map one Cloud Billing SKU to {model, modality, field, scope, token, usd, unit, rank, skuId} or None.

    `id_token_map` is {model_id: token list}. The SKU belongs to the longest model id whose tokens are a prefix of the
    product phrase, provided the next word is structural (not part of a longer, different model name).
    """
    desc = str(sku.get("description") or "")
    low = desc.lower()
    if any(w in low for w in _CATALOG_SKIP_WORDS):
        return None
    phrase = _catalog_phrase(desc)
    best_id, best_len = None, 0
    for mid, toks in id_token_map.items():
        n = len(toks)
        if n <= best_len or n > len(phrase) or phrase[:n] != toks:
            continue
        nxt = phrase[n] if n < len(phrase) else ""
        if nxt and nxt not in _CATALOG_STRUCT_WORDS and not re.fullmatch(r"\d+(\.\d+)?k?", nxt):
            continue
        if nxt in _CATALOG_MODALITIES and n + 1 < len(phrase) and phrase[n + 1] in _CATALOG_MODALITIES:
            continue  # "<model> Image Text Input": the name of a different (image) model, not a base-model SKU
        best_id, best_len = mid, n
    if not best_id:
        return None
    all_toks = _join_version_digits(re.sub(r"[^a-z0-9.]+", " ", low).split())
    name_toks = list(id_token_map[best_id])
    rest = list(all_toks)
    for t in name_toks:  # drop the model's own words, keep everything else (incl. words before the product name)
        if t in rest:
            rest.remove(t)
    rest_txt = " ".join(rest)
    modality = next((m for m in _CATALOG_MODALITIES if m in rest), "text")
    if "cach" in rest_txt:
        field = "cache_read_input"
    elif "output" in rest:
        field = "thinking" if "thinking" in rest else "output"
    elif "input" in rest:
        field = "input"
    else:
        field = None
    token_like = "token" in low or best_id.startswith(("gemini", "claude"))
    if best_id.startswith("gemini-1.5") and "token" not in low:
        return None  # legacy per-character SKUs
    regions = [str(r).lower() for r in (sku.get("serviceRegions") or [])]
    if "global" not in rest and any(w in rest for w in ("regional", "us", "eu", "europe", "asia", "apac")):
        scope = "regional"
    elif "global" in rest:
        scope = "global"
    else:
        scope = "global" if ("global" in regions or not regions) else "regional"
    if token_like and field is None:
        return None
    usd, unit = (_extract_sku_usd_per_1m(sku), "") if token_like else _catalog_sku_unit_price(sku)
    if token_like:
        usd = usd if (usd is not None and usd > 0) else None
    if usd is None:
        return None
    return {
        "model": best_id, "modality": modality, "field": field, "scope": scope, "token": bool(token_like),
        "usd": float(usd), "unit": unit, "desc": desc.strip()[:90],
        "rank": 1 if any(w in low for w in ("experimental", "preview", " exp")) else 0,
        "skuId": str(sku.get("skuId") or (sku.get("name") or "").split("/")[-1] or ""),
    }


def build_catalog_rates(vertex_skus: list, gemini_api_skus: list, known_ids) -> dict:
    """{model_id: {"vertex": {modality: {field: usd_per_1M, regional_field: ...}}, "geminiApi": {...},
    "perUnit": [{sku, usd, unit}], "skuIds": {...}, "skuCount": n, "ambiguous": [slot, ...]}}.

    Ids whose names differ only by a suffix such as -preview/-exp share the same SKUs. When several standard SKUs
    compete for one slot the most plain one wins (no parenthesised qualifier, not preview/experimental) and the slot
    is listed in `ambiguous` if the competing prices differ, so nothing is guessed silently."""
    id_token_map: dict = {}
    by_tokens: dict = {}
    for mid in known_ids:
        toks = _catalog_id_tokens(mid)
        if toks:
            by_tokens.setdefault(tuple(toks), []).append(mid)
    for toks, ids in by_tokens.items():
        id_token_map[ids[0]] = list(toks)  # one representative per distinct name
    candidates: dict = {}
    per_unit: dict = {}
    sku_counts: dict = {}
    sku_ids: dict = {}
    for svc_key, skus in (("vertex", vertex_skus), ("geminiApi", gemini_api_skus)):
        expanded = [variant for raw_sku in (skus or []) for variant in _expand_version_pairs(raw_sku)]
        for sku in expanded:
            parsed = parse_catalog_sku(sku, id_token_map)
            if not parsed:
                continue
            rep = parsed["model"]
            sku_counts[rep] = sku_counts.get(rep, 0) + 1
            if not parsed["token"]:
                lst = per_unit.setdefault(rep, [])
                item = {"sku": parsed["desc"], "usd": round(parsed["usd"], 6), "unit": parsed["unit"] or "unit"}
                if len(lst) < 12 and item not in lst:
                    lst.append(item)
                continue
            key = parsed["field"] if parsed["scope"] == "global" else "regional_" + parsed["field"]
            plain = 0 if ("(" not in parsed["desc"]) else 1
            candidates.setdefault((rep, svc_key, parsed["modality"], key), []).append(
                (parsed["rank"], plain, round(parsed["usd"], 6), parsed["skuId"])
            )
    reps: dict = {}
    for (rep, svc_key, modality, key), cands in candidates.items():
        entry = reps.setdefault(rep, {"vertex": {}, "geminiApi": {}, "ambiguous": []})
        cands.sort(key=lambda c: (c[0], c[1], -c[2], c[3]))  # plain & non-preview first, then the HIGHEST price (conservative)
        best = cands[0]
        entry[svc_key].setdefault(modality, {})[key] = best[2]
        top_class = [c for c in cands if (c[0], c[1]) == (best[0], best[1])]
        if len({c[2] for c in top_class}) > 1:
            entry["ambiguous"].append(f"{svc_key}.{modality}.{key}")
        if modality == "text" and key.replace("regional_", "") in ("input", "output"):
            slot_name = "regional" if key.startswith("regional_") else "global"
            is_input = key.replace("regional_", "") == "input"
            current = sku_ids.get(rep, {}).get(slot_name)
            if current is None or (svc_key == "vertex" and is_input) or (svc_key == "vertex" and slot_name + "_svc" not in sku_ids.get(rep, {})):
                sku_ids.setdefault(rep, {})[slot_name] = best[3]
                sku_ids[rep][slot_name + "_svc"] = svc_key
            elif is_input and sku_ids[rep].get(slot_name + "_svc") == svc_key:
                sku_ids[rep][slot_name] = best[3]
    out: dict = {}
    for rep, toks in id_token_map.items():
        data = reps.get(rep)
        if not data and rep not in per_unit:
            continue
        data = data or {"vertex": {}, "geminiApi": {}, "ambiguous": []}
        data["perUnit"] = per_unit.get(rep, [])
        data["skuIds"] = {k: v for k, v in sku_ids.get(rep, {}).items() if not k.endswith("_svc")}
        data["skuCount"] = sku_counts.get(rep, 0)
        for alias in by_tokens.get(tuple(toks), [rep]):
            out[alias] = json.loads(json.dumps(data))
    return out


def _sanitize_sync_error_text(label: str, status: int, body: dict, token: str = None) -> str:
    raw_err = ""
    if isinstance(body, dict):
        err_obj = body.get("error")
        if isinstance(err_obj, dict):
            raw_err = str(err_obj.get("message") or err_obj.get("status") or "")
        elif err_obj:
            raw_err = str(err_obj)
    if token and token in raw_err:
        raw_err = raw_err.replace(token, "[REDACTED]")
    raw_err = " ".join(raw_err.split())[:120]
    if status == 429:
        return f"{label}: HTTP 429 rate-limited" + (f" ({raw_err})" if raw_err else "")
    if status > 0:
        return f"{label}: HTTP {status}" + (f" ({raw_err})" if raw_err else "")
    return f"{label}: connection error" + (f" ({raw_err})" if raw_err else "")


def register_observed_models_in_pricing_config(observed_model_ids: list | set) -> dict:
    """
    Registers model IDs observed in Cloud Monitoring into models_pricing_config.json
    with source='CLOUD_MONITORING_DISCOVERED' WITHOUT making any network requests.
    """
    cfg = load_models_pricing_config()
    models_map = cfg.setdefault("models", {})
    reg_mult = float(cfg.get("billingSettings", {}).get("regionalMultiplierDefault", 1.10) or 1.10)
    now_iso = datetime.now(timezone.utc).isoformat()
    added_any = False

    for ext_m in (observed_model_ids or []):
        raw_str = str(ext_m or "").strip()
        if not raw_str or " (" in raw_str:
            continue
        ext_clean = raw_str.split("/")[-1].split("@")[0].strip().lower()
        if (
            not ext_clean
            or ext_clean == "unknown-model"
            or "streamgeneratecontent" in ext_clean
            or not _MODEL_ID_VALID_RE.match(ext_clean)
        ):
            continue
        if ext_clean not in models_map:
            inferred = get_model_rates(ext_clean, "global")
            models_map[ext_clean] = {
                "modelId": ext_clean,
                "displayName": ext_clean,
                "publisher": "anthropic" if "claude" in ext_clean else ("google" if ("gemini" in ext_clean or "veo" in ext_clean or "imagen" in ext_clean or "lyria" in ext_clean or "gemma" in ext_clean) else "partner"),
                "input": inferred["global_input"],
                "output": inferred["global_output"],
                "thinking": inferred["global_output"],
                "cache_read_input": inferred["cache_read_input"],
                "regional_input": inferred["regional_input"],
                "regional_output": inferred["regional_output"],
                "regional_thinking": inferred["regional_output"],
                "regional_cache_read_input": round(inferred["cache_read_input"] * reg_mult, 4),
                "source": "CLOUD_MONITORING_DISCOVERED",
                "lastSkuIdGlobal": "",
                "lastSkuIdRegional": "",
                "updatedAt": now_iso,
            }
            added_any = True

    if added_any:
        cfg.setdefault("lastApiSync", {})["totalConfiguredModels"] = len(models_map)
        save_models_pricing_config(cfg)
    return cfg


def sync_models_and_pricing_from_gcp_api(
    token: str,
    user_project: str = None,
    extra_model_ids: list = None,
    quota_project: str = None,
    quota_candidates: list = None,
) -> dict:
    """
    Queries live Google Cloud APIs using gcp_api_get (with 429 retry & 403 user_project fallback):
    1. Cloud Billing Catalog API (`services/AEFD-7695-64FA/skus` for Gemini API & `services/C7E2-9256-1C43/skus` for Vertex AI)
    2. Vertex AI Publisher Models API (`aiplatform.googleapis.com/v1beta1/publishers/google/models` & `publishers/anthropic/models`)
    Preserves manualOverride entries, records errors/429s in lastApiSync.errors with partial=True, and persists data/models_pricing_config.json.
    """
    eff_user_project = (user_project or quota_project or "").strip() or None
    cfg = load_models_pricing_config()
    models_map = cfg.setdefault("models", {})
    skus_scanned = 0
    skus_matched = 0
    models_discovered_api = []
    sync_errors = []
    partial = False
    now_iso = datetime.now(timezone.utc).isoformat()

    # Quota-project candidates for APIs that need a billing/quota project (403 without it): the first
    # project that answers is remembered for the next calls and stored in lastApiSync.quotaProject.
    quota_order = list(dict.fromkeys(
        p for p in ([eff_user_project] + [str(c).strip() for c in (quota_candidates or [])]) if p
    ))[:4]
    working_quota = {"project": None}

    def _fetch_with_fallback(url: str, timeout_s: int = 20) -> tuple[int, dict]:
        st_code, resp_body = gcp_api_get(url, token, timeout=timeout_s, user_project=None)
        if st_code == 403 and quota_order:
            order = ([working_quota["project"]] if working_quota["project"] else []) + [
                q for q in quota_order if q != working_quota["project"]
            ]
            for q_proj in order:
                st_code, resp_body = gcp_api_get(url, token, timeout=timeout_s, user_project=q_proj)
                if st_code != 403:
                    if st_code == 200:
                        working_quota["project"] = q_proj
                    break
        if not isinstance(resp_body, dict):
            resp_body = {}
        return st_code, resp_body

    # 1. Fetch all SKUs from the Cloud Billing Catalog API (Gemini API and Vertex AI services); they are read after
    #    the model list is known, so that every SKU can be assigned to a model that really exists
    catalog_skus: dict = {"vertex": [], "geminiApi": []}
    catalog_complete = {"vertex": False, "geminiApi": False}
    for svc_label, svc_id, svc_key in (("Gemini API", "AEFD-7695-64FA", "geminiApi"), ("Vertex AI", "C7E2-9256-1C43", "vertex")):
        page_token = ""
        finished = False
        for _ in range(12):
            url = f"https://cloudbilling.googleapis.com/v1/services/{svc_id}/skus?pageSize=5000"
            if page_token:
                url += f"&pageToken={urllib.parse.quote(page_token)}"
            status, body = _fetch_with_fallback(url, timeout_s=20)
            if status != 200:
                partial = True
                sync_errors.append(_sanitize_sync_error_text(f"Billing Catalog ({svc_label})", status, body, token))
                break
            skus_list = body.get("skus") or []
            skus_scanned += len(skus_list)
            catalog_skus[svc_key].extend(skus_list)
            page_token = body.get("nextPageToken") or ""
            if not page_token:
                finished = True
                break
        catalog_complete[svc_key] = finished

    reg_mult = float(cfg.get("billingSettings", {}).get("regionalMultiplierDefault", 1.10) or 1.10)

    # 2. Fetch live Publisher Models from Vertex AI API (publishers/google/models & publishers/anthropic/models)
    api_ids: dict[str, set] = {}
    api_complete: dict[str, bool] = {}
    for pub in ("google", "anthropic"):
        ids_seen: set = set()
        complete = True
        page_token = ""
        for _page in range(10):
            pub_url = f"https://aiplatform.googleapis.com/v1beta1/publishers/{pub}/models?pageSize=200"
            if page_token:
                pub_url += f"&pageToken={urllib.parse.quote(page_token)}"
            p_status, p_body = _fetch_with_fallback(pub_url, timeout_s=15)
            if p_status != 200:
                partial = True
                complete = False
                sync_errors.append(_sanitize_sync_error_text(f"Vertex Publisher ({pub})", p_status, p_body, token))
                break
            for pm in (p_body.get("publisherModels") or []):
                raw_name = (pm.get("name") or "").split("/")[-1].split("@")[0].strip().lower()
                if not raw_name or not _MODEL_ID_VALID_RE.match(raw_name):
                    continue
                ids_seen.add(raw_name)
                models_discovered_api.append(raw_name)
                if raw_name not in models_map:
                    inferred = get_model_rates(raw_name, "global")
                    models_map[raw_name] = {
                        "modelId": raw_name,
                        "displayName": raw_name,  # model ID, never the numeric versionId
                        "publisher": pub,
                        "launchStage": pm.get("launchStage", "GA"),
                        "input": inferred["global_input"],
                        "output": inferred["global_output"],
                        "thinking": inferred["global_output"],
                        "cache_read_input": inferred["cache_read_input"],
                        "regional_input": inferred["regional_input"],
                        "regional_output": inferred["regional_output"],
                        "regional_thinking": inferred["regional_output"],
                        "regional_cache_read_input": round(inferred["cache_read_input"] * reg_mult, 4),
                        "source": f"VERTEX_PUBLISHER_API:{pub}",
                        "lastSkuIdGlobal": "",
                        "lastSkuIdRegional": "",
                        "updatedAt": now_iso,
                    }
                entry_api = models_map[raw_name]
                entry_api["publisher"] = pub
                entry_api["status"] = "active"
                entry_api["lastSeenAt"] = now_iso
                entry_api.pop("deletedAt", None)
                if pm.get("launchStage"):
                    entry_api["launchStage"] = pm.get("launchStage")
            page_token = p_body.get("nextPageToken") or ""
            if not page_token:
                break
        else:
            complete = False  # more pages than we are willing to read: the list is not authoritative
        api_ids[pub] = ids_seen
        api_complete[pub] = complete

    # 3. Also ensure any extra model IDs passed in are registered as CLOUD_MONITORING_DISCOVERED
    for ext_m in (extra_model_ids or []):
        raw_str = str(ext_m or "").strip()
        if not raw_str or " (" in raw_str:
            continue
        ext_clean = raw_str.split("/")[-1].split("@")[0].strip().lower()
        if (
            not ext_clean
            or ext_clean == "unknown-model"
            or "streamgeneratecontent" in ext_clean
            or not _MODEL_ID_VALID_RE.match(ext_clean)
        ):
            continue
        if ext_clean not in models_map:
            inferred = get_model_rates(ext_clean, "global")
            models_map[ext_clean] = {
                "modelId": ext_clean,
                "displayName": ext_clean,
                "publisher": "anthropic" if "claude" in ext_clean else ("google" if ("gemini" in ext_clean or "veo" in ext_clean or "imagen" in ext_clean or "lyria" in ext_clean or "gemma" in ext_clean) else "partner"),
                "input": inferred["global_input"],
                "output": inferred["global_output"],
                "thinking": inferred["global_output"],
                "cache_read_input": inferred["cache_read_input"],
                "regional_input": inferred["regional_input"],
                "regional_output": inferred["regional_output"],
                "regional_thinking": inferred["regional_output"],
                "regional_cache_read_input": round(inferred["cache_read_input"] * reg_mult, 4),
                "source": "CLOUD_MONITORING_DISCOVERED",
                "lastSkuIdGlobal": "",
                "lastSkuIdRegional": "",
                "updatedAt": now_iso,
            }

    # 3b. Rates per model straight from the catalog (no estimates): every model gets the prices of its own SKUs
    if catalog_complete["vertex"] or catalog_complete["geminiApi"]:
        catalog = build_catalog_rates(
            catalog_skus["vertex"] if catalog_complete["vertex"] else [],
            catalog_skus["geminiApi"] if catalog_complete["geminiApi"] else [],
            set(models_map),
        )
        for mid, ent in models_map.items():
            if not isinstance(ent, dict):
                continue
            cat_m = catalog.get(mid)
            if not cat_m:
                if catalog_complete["vertex"] and catalog_complete["geminiApi"]:
                    ent["pricingStatus"] = "NO_CATALOG_PRICE"
                continue
            manual_ov = ent.get("manualOverride") if isinstance(ent.get("manualOverride"), dict) else {}
            v_text = (cat_m.get("vertex") or {}).get("text") or {}
            g_text = (cat_m.get("geminiApi") or {}).get("text") or {}
            both_complete = catalog_complete["vertex"] and catalog_complete["geminiApi"]
            if any(k in v_text for k in ("input", "output")):
                base = v_text
            else:
                base = g_text if both_complete else {}  # never replace Vertex prices with Gemini API ones when Vertex was not fully read
            svc_id_used = "C7E2-9256-1C43" if base is v_text and v_text else "AEFD-7695-64FA"
            pre_ov = ent.get("preOverrideRates") if isinstance(ent.get("preOverrideRates"), dict) else {}
            for fld in ("input", "output", "cache_read_input"):
                if fld in base and fld not in manual_ov:
                    ent[fld] = base[fld]
                elif fld in base and fld in pre_ov:
                    pre_ov[fld] = base[fld]  # keep the snapshot aligned with the fresh catalog price
            if "thinking" in pre_ov and ("thinking" in base or "output" in base):
                pre_ov["thinking"] = base.get("thinking", base.get("output"))
            if "thinking" not in manual_ov and ("thinking" in base or "output" in base):
                ent["thinking"] = base.get("thinking", base.get("output"))
            reg_src = v_text if v_text else g_text
            for fld in ("input", "output", "cache_read_input"):
                reg_key = "regional_" + fld
                if reg_key in reg_src and reg_key not in manual_ov:
                    ent[reg_key] = reg_src[reg_key]
                elif reg_key in reg_src and reg_key in pre_ov:
                    pre_ov[reg_key] = reg_src[reg_key]
            if "regional_output" in reg_src and "regional_thinking" not in manual_ov:
                ent["regional_thinking"] = reg_src["regional_output"]
            sku_ids_m = cat_m.get("skuIds") or {}
            if sku_ids_m.get("global"):
                ent["lastSkuIdGlobal"] = sku_ids_m["global"]
            if sku_ids_m.get("regional"):
                ent["lastSkuIdRegional"] = sku_ids_m["regional"]
            gem_rates_new = {k: g_text[k] for k in ("input", "output", "cache_read_input") if k in g_text}
            if gem_rates_new:
                ent["geminiApiRates"] = gem_rates_new
            prev_catalog = ent.get("catalog") if isinstance(ent.get("catalog"), dict) else {}
            ent["catalog"] = {
                # a service that was not fully read keeps what the previous sync stored
                "vertex": (cat_m.get("vertex") or {}) if catalog_complete["vertex"] else (prev_catalog.get("vertex") or {}),
                "geminiApi": (cat_m.get("geminiApi") or {}) if catalog_complete["geminiApi"] else (prev_catalog.get("geminiApi") or {}),
                "perUnit": cat_m.get("perUnit") or [],
                "ambiguous": cat_m.get("ambiguous") or [],
                "skuCount": cat_m.get("skuCount", 0),
                "syncedAt": now_iso,
            }
            has_token_rates = bool(base)
            ent["pricingStatus"] = "CATALOG" if (has_token_rates or g_text or cat_m.get("perUnit")) else "NO_CATALOG_PRICE"
            if has_token_rates:
                ent["catalogSource"] = f"GCP_BILLING_API:{svc_id_used}"
                ent["source"] = "MANUAL" if manual_ov else f"GCP_BILLING_API:{svc_id_used}"
            ent["updatedAt"] = now_iso
        skus_matched = sum(c.get("skuCount", 0) for c in {id(v): v for v in catalog.values()}.values())

    # Normalize regional rates and ensure manualOverride fields always win
    for _m_id, m_entry in models_map.items():
        if not isinstance(m_entry, dict):
            continue
        # numeric-only names (old versionId bug) go back to the model ID; hand-chosen names are kept
        if str(m_entry.get("displayName") or "").strip().isdigit():
            m_entry["displayName"] = m_entry.get("modelId") or _m_id
        manual_ov = m_entry.get("manualOverride") if isinstance(m_entry.get("manualOverride"), dict) else {}
        for k_ov, v_ov in manual_ov.items():
            m_entry[k_ov] = v_ov
        if manual_ov:
            m_entry["source"] = "MANUAL"
        for base_f, reg_f in (
            ("input", "regional_input"),
            ("output", "regional_output"),
            ("thinking", "regional_thinking"),
            ("cache_read_input", "regional_cache_read_input"),
        ):
            if reg_f not in manual_ov and float(m_entry.get(base_f, 0) or 0) > 0 and not m_entry.get("lastSkuIdRegional"):
                m_entry[reg_f] = round(float(m_entry[base_f]) * reg_mult, 4)
        m_entry.setdefault("lastSkuIdGlobal", "")
        m_entry.setdefault("lastSkuIdRegional", "")
        m_entry.setdefault("updatedAt", now_iso)

    # 4. Reconcile the list with what Google returned (only when the Google list was read completely)
    removed_models: list = []
    deleted_models_now: list = []
    extra_clean = {
        str(e or "").strip().split("/")[-1].split("@")[0].strip().lower() for e in (extra_model_ids or [])
    }
    google_authoritative = bool(api_complete.get("google")) and len(api_ids.get("google", set())) > 0
    if google_authoritative:
        cfg["modelListFromApi"] = True
        all_api_ids = set().union(*api_ids.values())
        for mid, ent in list(models_map.items()):
            if not isinstance(ent, dict) or mid in all_api_ids:
                continue
            publisher_e = str(ent.get("publisher") or "").lower()
            src_e = str(ent.get("source") or "")
            has_manual = isinstance(ent.get("manualOverride"), dict) and bool(ent.get("manualOverride"))
            if publisher_e == "google":
                is_deleted = True
            else:
                returned_by_google_service = (
                    src_e.startswith("GCP_BILLING_API") or src_e.startswith("VERTEX_PUBLISHER_API")
                    or (src_e == "CLOUD_MONITORING_DISCOVERED" and mid in extra_clean)
                )
                publisher_list_read = (publisher_e not in ("google", "anthropic")) or bool(api_complete.get(publisher_e))
                if not returned_by_google_service and not has_manual:
                    if publisher_list_read:
                        del models_map[mid]
                        removed_models.append(mid)
                    continue  # publisher list not read completely: keep it, decide at a later sync
                # kept: flag deleted only when its publisher list was read completely and does not contain it
                is_deleted = bool(api_complete.get(publisher_e)) and publisher_e in api_ids
            if is_deleted and ent.get("status") != "deleted":
                ent["status"] = "deleted"
                ent["deletedAt"] = now_iso
                deleted_models_now.append(mid)

    # USD -> EUR rate applied by Google Cloud billing (Catalog API, currencyCode=EUR); used for the euro display
    fx_status, fx_body = _fetch_with_fallback(
        "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus?pageSize=5&currencyCode=EUR", timeout_s=20
    )
    fx_found = extract_catalog_fx_rate(fx_body) if fx_status == 200 else None
    if fx_found:
        cfg["fxRate"] = {
            "usdToEur": fx_found[0],
            "effectiveTime": fx_found[1],
            "fetchedAt": now_iso,
            "source": "GCP_BILLING_CATALOG",
        }
    elif fx_status != 200:
        sync_errors.append(_sanitize_sync_error_text("Billing Catalog (EUR rate)", fx_status, fx_body, token))

    cfg["lastApiSync"] = {
        "syncedAt": now_iso,
        "skusScanned": skus_scanned,
        "skusMatched": skus_matched,
        "publisherModelsDiscovered": len(models_discovered_api),
        "totalConfiguredModels": len(models_map),
        "partial": partial,
        "errors": sync_errors,
        "quotaProject": working_quota["project"],
        "listAuthoritative": google_authoritative,
        "modelsListedByApi": len(set().union(*api_ids.values())) if api_ids else 0,
        "modelsDeleted": sum(1 for m in models_map.values() if isinstance(m, dict) and m.get("status") == "deleted"),
        "modelsRemoved": removed_models[:100],
    }
    save_models_pricing_config(cfg)
    return cfg


_BILLING_SETTINGS_LIMITS = {
    "vertexBillingCreditDiscountPct": (0.0, 95.0),
    "geminiApiBillingCreditDiscountPct": (0.0, 95.0),
    "vertexImplicitCacheHitRatioPct": (0.0, 98.0),
    "regionalMultiplierDefault": (1.0, 3.0),
    "managedServiceSavingsPct": (0.0, 100.0),
    "geminiApiImplicitCacheHitRatioPct": (0.0, 98.0),
    "usdToEurRate": (0.5, 1.5),
}
_MODEL_RATE_KEYS = (
    "input",
    "output",
    "thinking",
    "cache_read_input",
    "regional_input",
    "regional_output",
    "regional_thinking",
    "regional_cache_read_input",
)


def _is_finite_number(val) -> bool:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return math.isfinite(float(val))


def validate_and_apply_models_pricing_update(req: dict) -> tuple[bool, str | None, dict | None]:
    """
    Validates and applies updates to billingSettings and model manual overrides.
    Never accepts oauthClientOwners (personal data edited only on disk).
    Unknown keys are discarded. Out-of-range or non-finite numbers return (False, error_msg, None).
    """
    if not isinstance(req, dict):
        return False, "Invalid JSON payload.", None
    if "oauthClientOwners" in req:
        return False, "oauthClientOwners cannot be modified via API.", None

    cfg = load_models_pricing_config()
    now_iso = datetime.now(timezone.utc).isoformat()

    if "billingSettings" in req:
        raw_bs = req.get("billingSettings")
        if not isinstance(raw_bs, dict):
            return False, "billingSettings must be an object.", None
        bs_target = cfg.setdefault("billingSettings", dict(DEFAULT_BILLING_SETTINGS))
        for k_bs, (min_v, max_v) in _BILLING_SETTINGS_LIMITS.items():
            if k_bs in raw_bs:
                val = raw_bs[k_bs]
                if not _is_finite_number(val):
                    return False, f"Invalid number for {k_bs}.", None
                f_val = float(val)
                if f_val < min_v or f_val > max_v:
                    return False, f"{k_bs} must be between {min_v} and {max_v}.", None
                bs_target[k_bs] = round(f_val, 4)

        if "usdToEurRateAuto" in raw_bs:
            if not isinstance(raw_bs["usdToEurRateAuto"], bool):
                return False, "usdToEurRateAuto must be true or false.", None
            bs_target["usdToEurRateAuto"] = raw_bs["usdToEurRateAuto"]

    reg_mult = float(cfg.get("billingSettings", {}).get("regionalMultiplierDefault", 1.10) or 1.10)
    models_map = cfg.setdefault("models", {})

    if "models" in req:
        raw_models = req.get("models")
        if not isinstance(raw_models, dict):
            return False, "models must be an object.", None
        combined_keys = set(models_map.keys()) | set(raw_models.keys())
        if len(raw_models) > 500 or len(combined_keys) > 500:
            return False, "Maximum of 500 models exceeded.", None

        for m_id, m_val in raw_models.items():
            if not isinstance(m_id, str) or not _MODEL_ID_VALID_RE.match(m_id):
                return False, f"Invalid modelId '{m_id}'.", None
            if not isinstance(m_val, dict):
                return False, f"Configuration for model '{m_id}' must be an object.", None

            # Collect rate overrides from top-level rate keys and/or nested manualOverride dict
            rate_updates = {}
            nested_mo = m_val.get("manualOverride")
            if nested_mo is not None and not isinstance(nested_mo, dict):
                return False, f"manualOverride for '{m_id}' must be an object.", None
            for src_dict in (m_val, nested_mo or {}):
                for rk in _MODEL_RATE_KEYS:
                    if rk in src_dict:
                        rv = src_dict[rk]
                        if not _is_finite_number(rv):
                            return False, f"Rate '{rk}' for '{m_id}' must be a finite number.", None
                        f_rv = float(rv)
                        if f_rv < 0.0 or f_rv > 1000.0:
                            return False, f"Rate '{rk}' for '{m_id}' must be between 0 and 1000.", None
                        rate_updates[rk] = round(f_rv, 6)

            if m_id not in models_map:
                inferred = get_model_rates(m_id, "global")
                models_map[m_id] = {
                    "modelId": m_id,
                    "displayName": m_id,
                    "publisher": "anthropic" if "claude" in m_id else ("google" if ("gemini" in m_id or "veo" in m_id or "imagen" in m_id or "lyria" in m_id or "gemma" in m_id) else "partner"),
                    "input": inferred["global_input"],
                    "output": inferred["global_output"],
                    "thinking": inferred["global_output"],
                    "cache_read_input": inferred["cache_read_input"],
                    "regional_input": inferred["regional_input"],
                    "regional_output": inferred["regional_output"],
                    "regional_thinking": inferred["regional_output"],
                    "regional_cache_read_input": round(inferred["cache_read_input"] * reg_mult, 4),
                    "source": "MANUAL",
                    "lastSkuIdGlobal": "",
                    "lastSkuIdRegional": "",
                    "updatedAt": now_iso,
                }

            entry = models_map[m_id]
            for meta_k in ("displayName", "publisher", "launchStage"):
                if isinstance(m_val.get(meta_k), str) and m_val[meta_k].strip():
                    entry[meta_k] = m_val[meta_k].strip()[:80]

            if "geminiApiCacheHitRatioPct" in m_val:
                gv = m_val["geminiApiCacheHitRatioPct"]
                if gv is None:
                    entry.pop("geminiApiCacheHitRatioPct", None)
                else:
                    if not _is_finite_number(gv):
                        return False, f"geminiApiCacheHitRatioPct for '{m_id}' must be a finite number.", None
                    if float(gv) < 0.0 or float(gv) > 98.0:
                        return False, f"geminiApiCacheHitRatioPct for '{m_id}' must be between 0 and 98.", None
                    entry["geminiApiCacheHitRatioPct"] = round(float(gv), 2)

            if m_val.get("clearManualOverride") is True:
                entry.pop("manualOverride", None)
                snap = entry.pop("preOverrideRates", None)
                if isinstance(snap, dict):
                    for rk, rv in snap.items():
                        if rk in _MODEL_RATE_KEYS and _is_finite_number(rv):
                            entry[rk] = rv
                entry["source"] = entry.get("catalogSource") or ("GCP_BILLING_API:C7E2-9256-1C43" if entry.get("lastSkuIdGlobal") else "BUILTIN_DEFAULT")

            if rate_updates:
                mo_dict = entry.get("manualOverride")
                if not isinstance(mo_dict, dict):
                    mo_dict = {}
                # Snapshot, before the first override, ONLY the fields this update will change (the overridden ones and
                # the ones derived from them), so that clearing restores exactly those and never touches fresher prices.
                # Fields already under an older override hold manual values: they are never snapshotted.
                touched = set(rate_updates)
                if "output" in rate_updates and "thinking" not in mo_dict:
                    touched.add("thinking")
                if not entry.get("lastSkuIdRegional"):
                    for reg_f in ("regional_input", "regional_output", "regional_thinking", "regional_cache_read_input"):
                        if reg_f not in mo_dict and reg_f not in rate_updates:
                            touched.add(reg_f)
                snap = entry.get("preOverrideRates") if isinstance(entry.get("preOverrideRates"), dict) else {}
                for rk in _MODEL_RATE_KEYS:
                    if rk in touched and rk not in snap and rk not in mo_dict and rk in entry:
                        snap[rk] = entry[rk]
                if snap:
                    entry["preOverrideRates"] = snap
                mo_dict.update(rate_updates)
                entry["manualOverride"] = mo_dict
                for rk, rv in rate_updates.items():
                    entry[rk] = rv
                if "output" in rate_updates and "thinking" not in mo_dict:
                    entry["thinking"] = rate_updates["output"]
                for base_f, reg_f in (
                    ("input", "regional_input"),
                    ("output", "regional_output"),
                    ("thinking", "regional_thinking"),
                    ("cache_read_input", "regional_cache_read_input"),
                ):
                    if reg_f not in mo_dict and not entry.get("lastSkuIdRegional"):
                        entry[reg_f] = round(float(entry.get(base_f, 0.0) or 0.0) * reg_mult, 4)
                entry["source"] = "MANUAL"

            entry["updatedAt"] = now_iso

    # Recompute regional fallback rates on models without regional SKU or manual override when multiplier changes
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

    cfg.setdefault("lastApiSync", {})["totalConfiguredModels"] = len(models_map)
    save_models_pricing_config(cfg)
    return True, None, cfg


def compute_observed_models_summary(active_acc: str = None, cfg: dict = None, cached_payload: dict = None) -> list[dict]:
    """
    Computes in deterministic code the list of models observed in the latest scan of active_acc:
    per model, number of projects and calls, and whether its price comes from catalog, fallback, or manual override.
    """
    if cfg is None:
        cfg = load_models_pricing_config()
    if cached_payload is None and active_acc and "load_best_cached_payload_for_account" in globals():
        with contextlib.suppress(Exception):
            cached_payload = load_best_cached_payload_for_account(active_acc, preferred_days=30)

    cfg_models = (cfg or {}).get("models") or {}
    sorted_cfg_keys = sorted((k for k in cfg_models.keys() if k != "default"), key=len, reverse=True)
    agg_map = {}

    for proj in ((cached_payload or {}).get("projects") or []):
        if not isinstance(proj, dict):
            continue
        pid = str(proj.get("projectId") or "").strip()
        for m in (proj.get("models") or []):
            if not isinstance(m, dict):
                continue
            raw_m_id = str(m.get("modelId") or "").strip()
            if not raw_m_id or " (" in raw_m_id:
                continue
            m_clean = raw_m_id.split("/")[-1].split("@")[0].strip().lower()
            if (
                not m_clean
                or m_clean == "unknown-model"
                or "streamgeneratecontent" in m_clean
                or not _MODEL_ID_VALID_RE.match(m_clean)
            ):
                continue
            calls = int(m.get("invocations", 0) or 0)
            in_tok = int(m.get("inputTokens", 0) or 0)
            out_tok = int(m.get("outputTokens", 0) or 0)
            tot_tok = int(m.get("totalTokens", 0) or 0)
            cost_usd = float(m.get("costUsd", 0.0) or 0.0)
            if calls <= 0 and tot_tok <= 0 and cost_usd <= 0:
                continue
            bucket = agg_map.setdefault(m_clean, {
                "projects": set(),
                "calls": 0,
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "costUsd": 0.0,
                "locations": set(),
            })
            if pid:
                bucket["projects"].add(pid)
            bucket["calls"] += calls
            bucket["inputTokens"] += in_tok
            bucket["outputTokens"] += out_tok
            bucket["totalTokens"] += tot_tok
            bucket["costUsd"] += cost_usd
            for loc in (m.get("locations") or []):
                if loc:
                    bucket["locations"].add(str(loc))

    observed_list = []
    for m_clean, agg in agg_map.items():
        matched_key = None
        if m_clean in cfg_models:
            matched_key = m_clean
        else:
            for k_cand in sorted_cfg_keys:
                if k_cand in m_clean:
                    matched_key = k_cand
                    break
        matched_entry = cfg_models.get(matched_key) if matched_key else None
        rates = get_model_rates(m_clean, "global")
        entry_src = str((matched_entry or {}).get("source") or rates.get("source") or "BUILTIN_DEFAULT")
        has_mo = bool(isinstance((matched_entry or {}).get("manualOverride"), dict) and (matched_entry or {}).get("manualOverride"))

        if entry_src == "MANUAL" or has_mo:
            price_origin = "manual"
        elif entry_src.startswith("GCP_BILLING_API"):
            price_origin = "catalog"
        else:
            price_origin = "fallback"

        observed_list.append({
            "modelId": m_clean,
            "projectsCount": len(agg["projects"]),
            "projects": sorted(agg["projects"]),
            "calls": agg["calls"],
            "inputTokens": agg["inputTokens"],
            "outputTokens": agg["outputTokens"],
            "totalTokens": agg["totalTokens"],
            "costUsd": round(agg["costUsd"], 4),
            "locations": sorted(agg["locations"]),
            "priceOrigin": price_origin,
            "isFallback": (price_origin == "fallback"),
            "source": entry_src,
            "matchedModelId": matched_key or "default",
            "inputRate": rates["global_input"],
            "outputRate": rates["global_output"],
            "regionalInputRate": rates["regional_input"],
            "regionalOutputRate": rates["regional_output"],
        })

    observed_list.sort(key=lambda x: (-x["calls"], -x["costUsd"], x["modelId"]))
    return observed_list


def load_budgets() -> dict:
    if os.path.exists(BUDGETS_FILE):
        with contextlib.suppress(OSError, ValueError):
            with open(BUDGETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"projects": {}, "credentials": {}}


def save_budgets(data: dict):
    with open(BUDGETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_today_date_str() -> str:
    """Returns current local calendar date YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def get_seconds_until_midnight() -> int:
    """Returns seconds remaining until 23:59:59 local time today (min 60s, max 36000s = 10h)."""
    now = datetime.now()
    midnight = now.replace(hour=23, minute=59, second=59, microsecond=0)
    remaining = int((midnight - now).total_seconds())
    return max(60, min(36000, remaining))
