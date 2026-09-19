# Lesson 5 — The Critic: rubric, verdict, and who decides

**Goal:** a reviewer that separates good reports from bad ones, produces
feedback a writer can act on, and hands the routing decision to code rather
than to the model's mood.

## What changed

```
src/dossier/
├── llm.py       chat_model(role): per-node model choice via DOSSIER_<ROLE>_MODEL
├── prompts.py   CRITIC_SYSTEM (+ JUDGE_SYSTEM for Step 8)
├── nodes.py     real critic, Critique schema, PASS_THRESHOLD policy
├── state.py     critique_scores, so evals can report averages
└── graph.py     every node is now real
tests/test_critic.py  NEW
```

---

## 1. The model judges; the code decides

The obvious design asks the LLM for `passed: bool`. We don't:

```python
scores = {dimension: _clamp_score(getattr(review, dimension)) for dimension in RUBRIC}
passed = all(score >= PASS_THRESHOLD for score in scores.values())
```

The model scores three dimensions 1–5. **Code turns scores into a verdict.**
Why that split:

- **The bar becomes a number you can move.** Raising `PASS_THRESHOLD` from 4 to
  5 is a one-line change plus an eval run. Re-teaching a prompt what "good
  enough" means is neither reproducible nor measurable.
- **Scores carry more information than a boolean**, and they survive into
  `critique_scores`, so evals can report "average groundedness" instead of
  "pass rate" alone.
- **The word "pass" never appears in the prompt.** A test asserts that.

Same idea as `finalize` filtering citations: the model produces judgements, the
code applies policy.

## 2. It must see the evidence

```text
Evidence the writer was given:
[1] <title>
<content>
...
Report to review:
<the draft>
```

Your prototype's critic got the draft and the sub-questions but not the notes,
so "is every claim traceable to a source?" was unanswerable — it could only
grade prose style. Reusing `_prepare_evidence` means the Critic sees exactly
the numbered evidence the Writer saw, so `[3]` means the same thing to both.

## 3. Then I measured it, and it was too nice

First live run on a real report: **5/5/5, passed on the first draft.** A critic
that says "excellent" to everything is worse than no critic: it costs a call
and licenses whatever came out.

So I probed it with three drafts built from the same evidence — one good, one
with invented claims, one that skipped a sub-question and repeated itself:

| draft | groundedness | completeness | coherence | verdict |
|---|---|---|---|---|
| good | 4 | 5 | 5 | pass |
| hallucinated | **1** | 3 | 2 | fail |
| incomplete | 5 | **5** ❌ | 2 | fail |

Mostly excellent. On the hallucinated draft it named every invented claim
("claims the global market reached $4.2 billion, but [1] contains no such
information"). On the good draft it caught that the report said companies
"run" pilot lines where the source said "announced".

**But look at the incomplete row.** That draft never addressed the second
sub-question at all, and completeness still scored 5/5. The rubric had a hole.

## 4. Fixing it: make the model enumerate before it scores

```python
class Critique(BaseModel):
    uncovered_sub_questions: list[str] = Field(...)  # FIRST field, on purpose
    groundedness: int
    ...
```

Structured output is filled **in field order**, so putting the coverage check
first forces the model to walk the sub-questions one at a time *before* it
commits to a completeness number. Reasoning first, conclusion second — the same
trick the judge needed in Step 8.

**A field description alone was not enough.** I added the field, re-ran the
probe, and the model still returned an empty list and completeness 5. The
instruction also had to be a step in the system prompt:

> First, work through the list of sub-questions ONE AT A TIME... Put every
> sub-question that fails this check in uncovered_sub_questions, word for word.

Re-probed: **completeness 2, the gap listed, verdict fail.** Then the code
applies the policy, because a missing sub-question is a completeness failure
by definition, whatever the model scored:

```python
if uncovered:
    scores["completeness"] = min(scores["completeness"], UNCOVERED_COMPLETENESS_CAP)
```

That sequence — measure, find the hole, change one thing, re-measure — is the
whole method. Without the probe I would have shipped a critic that rubber-stamps
incomplete reports, and the 5/5/5 would have looked like success.

## 5. Defensive detail: a rejection always carries feedback

```python
if not passed and not feedback:
    worst = min(scores, key=scores.get)
    feedback = f"- Improve {worst} (scored {scores[worst]}/5)."
```

The Writer decides "is this a revision?" by whether feedback exists. A
rejection with an empty issues list would arrive as no feedback, and the Writer
would treat it as a fresh first draft — silently throwing away the previous
one. One `if` prevents a bug that would be invisible in production.

## 6. Cost

The critic prompt is evidence (~2,200 tokens) + draft (~700) + rubric, so about
**3,000 input tokens per review**, and it runs once per draft. A rejected draft
therefore costs a writer call *and* a critic call — roughly 6k tokens of input
before you see any improvement. `MAX_REVISIONS = 3` is the wallet's limit as
much as the patience limit.

---

## Exercises

1. **Probe your own critic.** Take a real report, paste an invented sentence
   into it, and run only the critic. Does groundedness fall? Does it name your
   sentence?
2. **Move the bar.** Set `PASS_THRESHOLD = 5` and run three topics. How many
   now go to a second draft? Was any second draft better?
3. **Break the feedback guard.** Remove the "rejection always carries feedback"
   block, force a rejection with no issues, and watch the Writer start over
   instead of revising.
4. **Model tiering.** Run with `DOSSIER_CRITIC_MODEL=gemini-3.6-flash` and
   compare its scores with the default on the same report. Is the stronger
   model harsher?
5. **Read a disagreement.** Find a topic where the Critic passed a draft but
   the Step 8 judge scored it 3 or less. Who was right?

## Interview check

1. Why doesn't the Critic return `passed: bool` itself?
2. Why must the Critic see the research notes?
3. What does field *order* in a Pydantic schema have to do with output quality?
4. Your critic scores 5/5/5 on everything. What do you do next?
5. Why cap completeness in code when the model already gave a score?
6. What breaks if a rejection carries no feedback?

---

## Next: Step 8 — evals

→ [Lesson 6](06-evals-and-judging-the-judge.md)
