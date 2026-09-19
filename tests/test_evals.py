"""Tests for the eval harness itself.

The harness must be trustworthy before its numbers mean anything: if it
silently drops a failed run or reuses a stale cached score, every conclusion
drawn from it is wrong. All of this runs on fakes.
"""

import json

from dossier import evals, fakes
from dossier.graph import build_graph


def offline_graph(**overrides):
    return build_graph(**(fakes.FAKE_NODES | overrides))


TOPICS = [{"topic": "alpha", "category": "test"}, {"topic": "beta", "category": "test"}]


def test_run_topic_collects_metrics_from_a_finished_run():
    result = evals.run_topic("alpha", offline_graph(), judge=fakes.judge)

    assert result["error"] is None
    assert result["revision_count"] == 2  # the fake critic rejects draft 1
    assert result["critique_passed"] is True
    assert result["sources_cited"] == 1
    assert result["citations_invented"] == 0
    assert result["judge"]["usefulness"] == 3


def test_a_crashing_topic_is_recorded_not_raised():
    def exploding_writer(state):
        raise RuntimeError("model exploded")

    result = evals.run_topic("alpha", offline_graph(writer=exploding_writer), judge=fakes.judge)

    assert "RuntimeError: model exploded" in result["error"]
    assert result["report"] == ""
    assert "judge" not in result  # nothing to judge, and no judge call was paid for


def test_missing_evidence_is_counted(tmp_path):
    def failing_researcher(task):
        return {
            "research_notes": [
                {
                    "sub_question": task["question"],
                    "status": "error",
                    "title": "",
                    "source_url": "",
                    "content": "Search failed.",
                }
            ]
        }

    result = evals.run_topic("alpha", offline_graph(researcher=failing_researcher), judge=fakes.judge)
    assert result["notes_ok"] == 0 and result["notes_missing"] == 3


def test_a_failing_judge_does_not_destroy_the_run():
    def broken_judge(*args):
        raise RuntimeError("503 UNAVAILABLE")

    result = evals.run_topic("alpha", offline_graph(), judge=broken_judge)

    assert result["error"] is None  # the graph run itself succeeded
    assert result["report"]  # and the expensive part is kept
    assert "RuntimeError: 503" in result["judge_error"]


def test_a_cached_run_with_a_failed_judge_is_rejudged_without_rerunning(tmp_path):
    def broken_judge(*args):
        raise RuntimeError("503 UNAVAILABLE")

    evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=broken_judge, limit=1)

    runs = []

    def counting_graph_guard(state):
        runs.append(1)
        return fakes.planner(state)

    results = evals.evaluate(
        TOPICS,
        offline_graph(planner=counting_graph_guard),
        results_dir=tmp_path,
        judge=fakes.judge,
        limit=1,
    )

    assert runs == []  # the graph was not re-run
    assert results[0]["judge"]["usefulness"] == 3
    assert "judge_error" not in results[0]


def test_results_are_cached_and_reused(tmp_path):
    calls = []

    def counting_judge(*args):
        calls.append(1)
        return fakes.judge(*args)

    for _ in range(2):
        evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=counting_judge)

    assert len(calls) == 2  # two topics, judged once each; the second pass was cached
    assert (tmp_path / "alpha.json").exists()


def test_a_changed_node_prompt_invalidates_the_cached_run(tmp_path):
    evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge)
    stale = json.loads((tmp_path / "alpha.json").read_text())
    stale["run_config"] = "other-fingerprint"
    stale["word_count"] = 99999
    (tmp_path / "alpha.json").write_text(json.dumps(stale))

    results = evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge)

    assert results[0]["word_count"] != 99999  # re-run, not reused


def test_a_changed_judge_rescores_without_rerunning_the_graph(tmp_path):
    evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge, limit=1)
    stale = json.loads((tmp_path / "alpha.json").read_text())
    stale["judge_config"] = "older-judge"
    (tmp_path / "alpha.json").write_text(json.dumps(stale))

    runs = []

    def counting_planner(state):
        runs.append(1)
        return fakes.planner(state)

    def strict_judge(*args):
        return {**fakes.judge(*args), "usefulness": 2}

    results = evals.evaluate(
        TOPICS, offline_graph(planner=counting_planner), results_dir=tmp_path, judge=strict_judge, limit=1
    )

    assert runs == []  # graph not re-run
    assert results[0]["judge"]["usefulness"] == 2  # but re-scored
    assert results[0]["judge_config"] == evals.judge_fingerprint()


def test_failed_runs_are_not_cached_so_they_retry(tmp_path):
    def exploding_writer(state):
        raise RuntimeError("503")

    evals.evaluate(TOPICS, offline_graph(writer=exploding_writer), results_dir=tmp_path, judge=fakes.judge, limit=1)
    assert not (tmp_path / "alpha.json").exists()

    results = evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge, limit=1)
    assert results[0]["error"] is None  # retried and succeeded


def test_limit_only_runs_the_first_n_topics(tmp_path):
    results = evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge, limit=1)
    assert [result["topic"] for result in results] == ["alpha"]


def test_summary_reports_failures_separately_from_scores(tmp_path):
    good = evals.run_topic("alpha", offline_graph(), judge=fakes.judge)
    bad = evals.run_topic("beta", offline_graph(writer=lambda state: (_ for _ in ()).throw(RuntimeError("x"))))

    summary = evals.summarize([good, bad])

    assert summary["topics"] == 2
    assert summary["failed_runs"] == 1
    assert summary["judge_usefulness"] == 3  # averaged over successful runs only
    assert summary["avg_revisions"] == 2


def test_a_cached_result_without_evidence_is_not_judged():
    # Judging a report against empty evidence produces a confident, meaningless
    # "ungrounded" score. Refuse instead.
    result = {
        "topic": "alpha",
        "error": None,
        "report": "# Report [1]",
        "sub_questions": ["q"],
        "notes_ok": 12,
        "notes_missing": 0,
        "research_notes": [],
    }
    evals.ensure_judged(result, judge=fakes.judge)

    assert "judge" not in result
    assert "no research_notes" in result["judge_error"]


def test_summary_counts_unjudged_runs_next_to_the_averages():
    def broken_judge(*args):
        raise RuntimeError("quota")

    judged = evals.run_topic("alpha", offline_graph(), judge=fakes.judge)
    unjudged = evals.run_topic("beta", offline_graph(), judge=broken_judge)

    summary = evals.summarize([judged, unjudged])

    assert summary["topics"] == 2
    assert summary["judged"] == 1
    assert summary["unjudged_runs"] == 1
    assert summary["failed_runs"] == 0  # the runs themselves were fine


def test_outputs_are_written(tmp_path):
    results = evals.evaluate(TOPICS, offline_graph(), results_dir=tmp_path, judge=fakes.judge)
    evals.write_outputs(results, evals.summarize(results), results_dir=tmp_path)

    assert json.loads((tmp_path / "summary.json").read_text())["topics"] == 2
    csv_text = (tmp_path / "results.csv").read_text()
    assert "topic,category" in csv_text and "alpha" in csv_text


def test_the_topic_set_is_diverse_and_big_enough():
    topics = evals.load_topics()
    assert 20 <= len(topics) <= 30
    assert len({entry["topic"] for entry in topics}) == len(topics)
    # Adversarial cases are the point: a system that only handles nice topics
    # has not been evaluated.
    categories = {entry["category"] for entry in topics}
    assert {"adversarial-fictional", "adversarial-injection", "adversarial-gibberish"} <= categories
