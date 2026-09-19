"""The one place that knows which LLM provider we use.

Nodes ask this module for a model instead of constructing one themselves, so
swapping Gemini for Claude or GPT later means editing this file only.
"""

import logging
import os
from functools import cache

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

# Free-tier Gemini quotas are per model, per day: gemini-3.5-flash allows only
# 20 requests/day, and one full run makes ~8 calls. Lite has its own quota
# and handles these tasks well. Per-node model choice gets decided by evals.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# The judge should not be the same model that wrote the report: models tend to
# score their own style generously. A different model is the cheap defence; a
# different *provider* would be better still, and remains an honest weakness
# of this benchmark. A "lite" model is chosen deliberately: judging 27 topics
# needs more daily quota than the 20/day the bigger models allow, and this one
# was verified to separate good drafts from bad before being trusted.
ROLE_DEFAULTS = {"judge": "gemini-3.1-flash-lite"}


def model_name(role: str) -> str:
    """DOSSIER_<ROLE>_MODEL, else DOSSIER_MODEL, else the role's default."""
    return (
        os.getenv(f"DOSSIER_{role.upper()}_MODEL")
        or os.getenv("DOSSIER_MODEL")
        or ROLE_DEFAULTS.get(role, DEFAULT_MODEL)
    )


@cache
def chat_model(role: str = "default") -> BaseChatModel:
    """Build the client for a role on first use, then reuse it.

    Lazy on purpose: building it at import time would make `import dossier`
    fail without an API key — and tests import dossier.

    Roles ("planner", "writer", "critic", "judge") exist so a weak node can run
    on a cheap model and a demanding one on a stronger model, without touching
    node code. The client reads GEMINI_API_KEY from the environment and already
    retries network errors and rate limits on its own (6 attempts by default).
    """
    # google-genai logs a warning about "automatic function calling" on every
    # run because of how langchain-google-genai calls it. We don't use that
    # feature, so the warning is noise.
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)
    return ChatGoogleGenerativeAI(model=model_name(role))
