"""Command line entry point.

uv run dossier run "solid-state batteries"             # real LLM nodes (needs .env keys)
uv run dossier run --offline "solid-state batteries"   # fake nodes, no keys needed
uv run dossier diagram                                  # print the graph as Mermaid
"""

import argparse
import os

from dotenv import load_dotenv

from dossier.fakes import FAKE_NODES
from dossier.graph import build_graph
from dossier.guardrails import InvalidTopic, TokenBudget


def _preview(value: object, limit: int = 90) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def run(topic: str, offline: bool) -> None:
    graph = build_graph(**FAKE_NODES) if offline else build_graph()
    budget = TokenBudget()
    final_report = None

    print(f"Researching: {topic}")
    print("(tasks that share a step number ran in parallel)")

    # stream_mode="debug" instead of "updates": it reports the real super-step
    # number, so a fan-out shows up as several tasks in ONE step. "updates"
    # yields one chunk per task with no step boundaries, which makes parallel
    # researchers look like separate sequential steps.
    config = {
        "callbacks": [budget],
        "run_name": f"research: {topic[:60]}",
        "tags": ["dossier", "cli"],
        "metadata": {"topic": topic},
    }
    stream = graph.stream({"topic": topic}, stream_mode="debug", config=config)
    for event in stream:
        if event["type"] != "task_result":
            continue
        payload = event["payload"]
        print(f"\n[step {event['step']}] {payload['name']}")
        if payload["error"]:
            print(f"    error: {payload['error']}")
        for key, value in payload["result"].items():
            print(f"    {key} = {_preview(value)}")
            if key == "final_report":
                final_report = value

    print("\n" + "=" * 70)
    print(final_report or "(no report produced)")
    usage = budget.summary()
    print(
        f"\n{usage['calls']} LLM calls, {usage['total_tokens']:,} tokens "
        f"(in {usage['input_tokens']:,} / out {usage['output_tokens']:,})"
    )


def main() -> None:
    # Load .env before anything runs: LangSmith picks up LANGSMITH_* from the
    # environment at trace time, so this alone turns on tracing.
    load_dotenv()

    parser = argparse.ArgumentParser(prog="dossier", description="Multi-agent research assistant")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="research a topic")
    run_cmd.add_argument("topic")
    run_cmd.add_argument("--offline", action="store_true", help="use fake nodes: no LLM, no API keys")

    commands.add_parser("diagram", help="print the graph as a Mermaid diagram")

    ingest_cmd = commands.add_parser("ingest", help="add your own documents (PDF, text, Markdown)")
    ingest_cmd.add_argument("paths", nargs="+")

    commands.add_parser("mcp", help="serve the research tools over MCP (stdio)")

    serve_cmd = commands.add_parser("serve", help="run the HTTP API")
    serve_cmd.add_argument("--port", type=int, help="defaults to $PORT, then $DOSSIER_PORT, then 8500")

    user_cmd = commands.add_parser("user", help="create an API user")
    user_cmd.add_argument("email")
    user_cmd.add_argument("--daily-token-limit", type=int)

    eval_cmd = commands.add_parser("eval", help="run the eval set and score it")
    eval_cmd.add_argument("--limit", type=int, help="only the first N topics (free-tier quotas are small)")
    eval_cmd.add_argument("--force", action="store_true", help="ignore cached results")
    eval_cmd.add_argument("--offline", action="store_true", help="fake nodes and fake judge: exercises the harness")
    eval_cmd.add_argument("--judge-first-draft", action="store_true", help="also score draft 1 (doubles judge calls)")
    eval_cmd.add_argument("--results-dir", help="write results elsewhere, e.g. for an experiment")
    eval_cmd.add_argument("--topic", action="append", help="only these topics (repeatable)")

    args = parser.parse_args()
    if args.command == "run":
        try:
            run(args.topic, offline=args.offline)
        except InvalidTopic as exc:
            raise SystemExit(f"Rejected: {exc}") from None
    elif args.command == "diagram":
        print(build_graph().get_graph().draw_mermaid())
    elif args.command == "eval":
        run_eval(args)
    elif args.command == "ingest":
        ingest_documents(args.paths)
    elif args.command == "mcp":
        from dossier.mcp_server import main as serve_mcp

        serve_mcp()
    elif args.command == "serve":
        import uvicorn

        from dossier.api import create_app, port

        uvicorn.run(create_app(), host=os.getenv("DOSSIER_HOST", "127.0.0.1"), port=args.port or port())
    elif args.command == "user":
        create_api_user(args.email, args.daily_token_limit)


def create_api_user(email: str, daily_token_limit: int | None) -> None:
    from dossier import db

    engine = db.engine()
    db.init(engine)
    _, api_key = db.create_user(engine, email, daily_token_limit=daily_token_limit or db.DAILY_TOKEN_LIMIT)

    print(f"Created {email}")
    print(f"API key: {api_key}")
    # Only the hash is stored, so this is genuinely the only time it exists.
    print("\nSave it now — only its hash is stored, so it cannot be shown again.")


def ingest_documents(paths: list[str]) -> None:
    from pathlib import Path

    from dossier import docstore

    files = [Path(path) for path in paths]
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"Not a file: {', '.join(str(path) for path in missing)}")

    result = docstore.ingest(files)
    for entry in result["files"]:
        print(f"  {entry['chunks']:4} chunks  {entry['path']}")
    print(f"\n{result['chunks']} chunks stored; {docstore.document_count()} in the collection.")
    print("Runs will now search your documents alongside the web.")


def run_eval(args) -> None:
    from pathlib import Path

    from dossier import evals, fakes

    graph = build_graph(**FAKE_NODES) if args.offline else build_graph()
    topics = evals.load_topics()
    if args.topic:
        wanted = set(args.topic)
        topics = [entry for entry in topics if entry["topic"] in wanted]
    results = evals.evaluate(
        topics,
        graph,
        results_dir=Path(args.results_dir) if args.results_dir else evals.RESULTS_DIR,
        limit=args.limit,
        force=args.force,
        judge=fakes.judge if args.offline else evals.judge_report,
        judge_first_draft=args.judge_first_draft,
    )
    summary = evals.summarize(results)
    results_dir = Path(args.results_dir) if args.results_dir else evals.RESULTS_DIR
    evals.write_outputs(results, summary, results_dir=results_dir)

    print("\n" + "=" * 60)
    for key, value in summary.items():
        print(f"  {key:28} {value}")
    print(f"\nwritten to {results_dir}")
