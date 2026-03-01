"""
Central configuration — loads .env and provides paths + settings.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env from project root OR src/ (user may place it in either) ──
PROJECT_ROOT = Path(__file__).resolve().parent
_env_candidates = [PROJECT_ROOT / ".env", PROJECT_ROOT / "src" / ".env"]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
else:
    load_dotenv()  # fallback: default search

# ── Paths ──────────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
RUNBOOKS_DIR = DATA_DIR / "runbooks"
METRICS_DIR = DATA_DIR / "metrics"
ALERTS_DIR = DATA_DIR / "alerts"
SRC_DIR = PROJECT_ROOT / "src"
SERVERS_DIR = SRC_DIR / "mcp_servers"

# ── LLM Config ─────────────────────────────────────────────────────

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

# Standard OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
# Support both LLM_MODEL and OPENAI_MODEL variable names
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

# Azure OpenAI settings
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_DEPLOYMENT")
    or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
    or "gpt-4o"
)
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

# Resolve effective API key (Azure takes priority when provider is azure)
EFFECTIVE_API_KEY = AZURE_OPENAI_API_KEY if LLM_PROVIDER == "azure_openai" else OPENAI_API_KEY

# ── Context Policy ─────────────────────────────────────────────────

MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "6000"))
MAX_TOOL_RESULT_TOKENS = int(os.getenv("MAX_TOOL_RESULT_TOKENS", "2000"))

# ── Feature Flags ──────────────────────────────────────────────────

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"
ENABLE_OBSERVABILITY = os.getenv("ENABLE_OBSERVABILITY", "true").lower() == "true"
ENABLE_EVAL_HOOKS = os.getenv("ENABLE_EVAL_HOOKS", "true").lower() == "true"
