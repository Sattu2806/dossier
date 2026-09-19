"""Input validation and cost caps.

Both exist because the evals found the gaps, not because they seemed like good
ideas: given gibberish the system wrote a straight-faced report about the
QWERTY layout, and given "Ignore your previous instructions..." as a topic it
dutifully researched cats. Neither is an injection — the instructions were
never followed — but both are requests a research product should refuse.
"""

import logging
import os
import re

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

MIN_TOPIC_CHARS = 3
MAX_TOPIC_CHARS = 200

# Phrases whose only purpose is to address the system rather than describe a
# subject. Matching is deliberately narrow: "the history of prompt injection"
# is a legitimate research topic and must not be refused.
INSTRUCTION_PATTERNS = (
    r"\bignore\s+(all\s+|any\s+)?(your\s+|the\s+|previous\s+|prior\s+|above\s+)*instructions?\b",
    r"\bdisregard\s+(all\s+|any\s+)?(your\s+|the\s+|previous\s+|prior\s+|above\s+)*(instructions?|rules?|prompts?)\b",
    r"\bforget\s+(everything|all)\b.*\b(said|told|instructions?)\b",
    r"\byou\s+are\s+now\s+(a|an|my)\b",
    r"\b(system|developer)\s+prompt\b.*\b(reveal|show|print|repeat|ignore)\b",
    r"\b(reveal|show|print|repeat)\b.*\b(system|developer)\s+prompt\b",
)

# A word is "wordlike" if it contains a vowel and has no long consonant run.
# Only words of this length are judged: short tokens are usually acronyms
# ("ERP", "HNSW", "IVF") and rejecting those would refuse real topics.
GIBBERISH_MIN_WORD_LEN = 5
MAX_CONSONANT_RUN = 4
VOWELS = set("aeiouy")


class InvalidTopic(ValueError):
    """The topic is not something we are willing to research."""


class BudgetExceeded(RuntimeError):
    """The run hit its token budget and was stopped."""


def _is_wordlike(word: str) -> bool:
    letters = [character for character in word.lower() if character.isalpha()]
    if not letters:
        return False
    if not any(character in VOWELS for character in letters):
        return False
    run = 0
    for character in letters:
        run = 0 if character in VOWELS else run + 1
        if run >= MAX_CONSONANT_RUN:
            return False
    return True


def looks_like_gibberish(topic: str) -> bool:
    long_words = [word for word in re.findall(r"[A-Za-z]+", topic) if len(word) >= GIBBERISH_MIN_WORD_LEN]
    if not long_words:
        # Nothing long enough to judge: "ERP" is ambiguous, not gibberish.
        return False
    unwordlike = sum(1 for word in long_words if not _is_wordlike(word))
    return unwordlike > len(long_words) / 2


def validate_topic(topic: str) -> str:
    """Return the cleaned topic, or raise InvalidTopic with a reason the user
    can act on. Runs before any paid call: rejecting here costs nothing, and
    one rejected run saves a planner call, N searches and two drafts."""
    cleaned = " ".join(topic.split())

    if len(cleaned) < MIN_TOPIC_CHARS:
        raise InvalidTopic("Topic is too short — give at least a few words describing the subject.")
    if len(cleaned) > MAX_TOPIC_CHARS:
        raise InvalidTopic(f"Topic is too long — keep it under {MAX_TOPIC_CHARS} characters.")
    if not any(character.isalpha() for character in cleaned):
        raise InvalidTopic("Topic must contain words, not only numbers or symbols.")

    for pattern in INSTRUCTION_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            raise InvalidTopic(
                "That reads as an instruction to the system rather than a research topic. "
                "Describe the subject you want researched."
            )

    if looks_like_gibberish(cleaned):
        raise InvalidTopic("That does not look like a research topic. Try a subject in plain words.")

    return cleaned


# ---------------------------------------------------------------------------
# Cost caps
# ---------------------------------------------------------------------------

DEFAULT_MAX_TOKENS = int(os.getenv("DOSSIER_MAX_TOKENS", "120000"))

# Prices change and differ per model, so nothing is hard-coded: set these from
# your provider's current pricing page to get cost estimates. Tokens are always
# counted exactly; only the money conversion is configurable.
PRICE_PER_M_INPUT = float(os.getenv("DOSSIER_PRICE_PER_M_INPUT", "0"))
PRICE_PER_M_OUTPUT = float(os.getenv("DOSSIER_PRICE_PER_M_OUTPUT", "0"))


class TokenBudget(BaseCallbackHandler):
    """Counts tokens across every LLM call in a run and stops it going over.

    A LangChain callback rather than per-node bookkeeping: it sees every call,
    including the ones made inside `with_structured_output`, and it works the
    same for any node added later. Pass it in the run config:

        graph.invoke({"topic": t}, config={"callbacks": [budget]})
    """

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.max_tokens = max_tokens
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        return (self.input_tokens * PRICE_PER_M_INPUT + self.output_tokens * PRICE_PER_M_OUTPUT) / 1_000_000

    def on_llm_end(self, response, **kwargs) -> None:
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
        self.calls += 1

        if self.total_tokens > self.max_tokens:
            # Raised from the callback, so the very next node fails fast rather
            # than the run quietly continuing to spend.
            logger.warning("token budget exhausted: %d > %d", self.total_tokens, self.max_tokens)
            raise BudgetExceeded(
                f"Run stopped after {self.calls} calls: {self.total_tokens:,} tokens "
                f"exceeds the budget of {self.max_tokens:,}."
            )

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": round(self.estimated_cost, 4),
        }
