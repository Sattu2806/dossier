"""Wiring: which node runs after which.

With `approval=True` an `approve` node sits between the Planner and the
fan-out, pausing the run before a single search is paid for.

                    ┌─ researcher ─┐   (one per sub-question,
START → validate → planner ─┼─ researcher ─┼──► all in the same step)
                    └─ researcher ─┘
                                    │
                                    ▼
     writer → fact_checker → critic ─┬─ grounded and passed ──► finalize → END
        ▲                             │
        └─ either one rejects, ───────┘
           under the cap
"""

from collections.abc import Callable
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from dossier import checkpoints, nodes
from dossier.state import ResearchState

# Business rule: the Writer gets at most this many attempts. After that we
# finalize anyway rather than loop forever.
MAX_REVISIONS = 3

# Safety net if the business rule is ever broken. LangGraph counts one step
# for writing the input plus one per node run; our worst case is
# 1 + validate + planner + researcher + 3x(writer + fact_checker + critic)
# + finalize = 14. Parallel
# researchers all run inside ONE step, so more sub-questions cost nothing here.
# LangGraph's
# own default is 10,007 — with real LLM calls, that is a very expensive bug.
RECURSION_LIMIT = 25

# Retries for LLM nodes. There are two ways an LLM call fails:
#   1. transport: network error, rate limit, 5xx. The Gemini client already
#      retries these itself, so we don't handle them here.
#   2. content: the reply doesn't fit our schema. That raises
#      OutputParserException, which is a ValueError, and LangGraph's default
#      retry_on deliberately does NOT retry ValueErrors because they're usually
#      bugs. Bad model output isn't a bug, so we opt in to retrying it by name.
LLM_OUTPUT_RETRY = RetryPolicy(max_attempts=3, retry_on=OutputParserException)

Node = Callable[[ResearchState], dict]


def route_after_critic(state: ResearchState) -> Literal["writer", "finalize"]:
    """A router is a pure function: it reads state and returns the NAME of
    the next node. It cannot update state — anything it returns is a
    destination, not data. That is why revision_count is incremented inside
    the Writer node, not here.

    The Literal return type tells LangGraph every possible destination, so
    it can draw the graph and validate edges without an explicit path_map.
    """
    # Two independent gates: the Fact-Checker says whether the claims hold up,
    # the Critic says whether the report is any good. A draft has to satisfy
    # both, and either one can send it back.
    if state.get("grounded", True) and state["critique_passed"]:
        return "finalize"
    if state["revision_count"] >= MAX_REVISIONS:
        return "finalize"
    return "writer"


def build_graph(
    *,
    validate: Node = nodes.validate,
    planner: Node = nodes.planner,
    researcher: Node = nodes.researcher,
    writer: Node = nodes.writer,
    fact_checker: Node = nodes.fact_checker,
    critic: Node = nodes.critic,
    finalize: Node = nodes.finalize,
    approval: bool = False,
    saver: BaseCheckpointSaver | None = None,
):
    """Build and compile the graph.

    Every node can be swapped via a keyword argument. Tests and `--offline`
    use this to run with fakes.FAKE_NODES, which needs no API key.

    `approval=True` inserts a pause after the Planner so a human can edit the
    sub-questions before any search is paid for. It needs a checkpointer, so
    one is created if the caller did not supply it — the pause has to be
    written down somewhere or there is nothing to resume into.
    """
    builder = StateGraph(ResearchState)

    builder.add_node("validate", validate)
    builder.add_node("planner", planner, retry_policy=LLM_OUTPUT_RETRY)
    builder.add_node("researcher", researcher)
    builder.add_node("writer", writer, retry_policy=LLM_OUTPUT_RETRY)
    builder.add_node("fact_checker", fact_checker, retry_policy=LLM_OUTPUT_RETRY)
    builder.add_node("critic", critic, retry_policy=LLM_OUTPUT_RETRY)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "validate")
    builder.add_edge("validate", "planner")

    # With approval on, the fan-out moves one node later: plan, pause, then
    # spend. Off, the edge is exactly as it was — the default path has no
    # extra node to execute and no checkpoint to write.
    if approval:
        builder.add_node("approve", nodes.approve_plan)
        builder.add_edge("planner", "approve")

    # Fan-out: one researcher per sub-question. The list argument tells
    # LangGraph where the Sends can land, so `dossier diagram` stays accurate.
    builder.add_conditional_edges("approve" if approval else "planner", nodes.fan_out_to_researchers, ["researcher"])
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", "fact_checker")
    builder.add_edge("fact_checker", "critic")
    builder.add_conditional_edges("critic", route_after_critic)
    builder.add_edge("finalize", END)

    # compile() checks the structure (no dangling edges, unreachable nodes)
    # and returns a runnable with .invoke() / .stream().
    if approval and saver is None:
        saver = checkpoints.checkpointer()
    return builder.compile(checkpointer=saver).with_config(recursion_limit=RECURSION_LIMIT)
