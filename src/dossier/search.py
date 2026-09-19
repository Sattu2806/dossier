"""The one place that knows we search the web with Tavily.

Same idea as llm.py: nodes call `web_search()`, so swapping Tavily for Brave,
Exa or an internal index later means editing this file only. In Phase 2 the
document (RAG) search will sit next to this function with the same signature.
"""

import os
from functools import cache

from tavily import TavilyClient

# 3 results per sub-question. Each result is one Note, so 4 sub-questions gives
# ~12 notes — enough evidence without blowing up the Writer's prompt.
MAX_RESULTS = 3
SEARCH_TIMEOUT_SECONDS = 20


@cache
def search_client() -> TavilyClient:
    """Built on first use, not at import, so tests never need a key."""
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def web_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Return raw Tavily results. Errors are the caller's problem: the
    researcher node decides whether a failed search kills the run."""
    response = search_client().search(
        query=query,
        max_results=max_results,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    return response.get("results", [])
