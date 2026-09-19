# Lesson 8 — Your own documents, and a separate fact-checker

**Goal:** search uploaded documents alongside the web, and give claim-checking
its own node instead of asking the Critic to do two jobs.

## 1. One function signature is the whole design

```python
def web_search(query) -> list[dict]   # {title, url, content}
def doc_search(query) -> list[dict]   # {title, url, content}

SOURCES = {"web": web_search, "docs": doc_search}
```

The Researcher does not know there are two kinds of source. It is handed a
name, looks it up, and treats the results identically — which is why adding
documents changed the researcher by about five lines, and why an internal wiki
would be one more entry in that dict.

The `Note` gained an `origin` field so a citation can say where it came from,
but every downstream node still treats a PDF chunk and a web page the same.

## 2. Fan-out now covers questions × sources

```python
return [
    Send("researcher", ResearcherTask(question=question, origin=origin))
    for question in state["sub_questions"]
    for origin in available_origins()
]
```

Four sub-questions across two sources is **eight researchers in one
super-step**. The UI shows it as "Researching ×8 in parallel".

`available_origins()` is routing, not decoration: with no documents ingested it
returns `["web"]` only. Without that check, every run would pay for a document
search that cannot succeed. It also has to be cheap and key-free — it runs on
every request, and "no documents yet" is the common case, so it checks whether
the index directory exists before building any client.

## 3. The bug a vector store always has

The first hybrid run in the browser produced this: a report on **rent control**
whose only evidence was a survey about the **Zorblex fish**.

A vector store returns its k nearest chunks, *however far away they are*. With
one document ingested, every query matches it. Nothing was broken — cosine
similarity did exactly what it is supposed to do.

The fix is a relevance floor, and the number was **measured, not guessed**:

| query | relevance |
|---|---|
| Zorblex fish breeding grounds | 0.612 |
| Zorblex migration routes | 0.636 |
| rent control housing supply | 0.406 |
| the historical background of rent control policies | 0.318 |
| solid-state battery electrolytes | 0.373 |

On-topic 0.61–0.64, off-topic 0.32–0.41, so the threshold is 0.5 — and the
comment in the code says to re-measure if the embedding model changes, because
the number belongs to that model, not to the idea.

**Irrelevant evidence is worse than no evidence**: it fills the prompt and
invites the model to draw a connection to justify its presence.

## 4. Why the Fact-Checker is not part of the Critic

```
writer → fact_checker → critic ─┬─ grounded AND passed → finalize
   ▲                            │
   └──── either one rejects ────┘
```

Your prototype had a separate fact-checker, and that instinct was right. The
two nodes answer questions that need different attention:

| | Fact-Checker | Critic |
|---|---|---|
| Question | Does the evidence support this sentence? | Is this report any good? |
| Method | Statement by statement against numbered evidence | A rubric over the whole thing |
| Output | Quoted unsupported statements | Scores and actionable issues |
| Failure it catches | A fabricated number that reads beautifully | A well-sourced report that ignores a sub-question |

A single node asked to do both does neither carefully — it drifts towards style
because style is easier to judge than provenance.

Two independent gates guard the loop, and **either can send a draft back**:

```python
if state.get("grounded", True) and state["critique_passed"]:
    return "finalize"
```

A test pins the case that matters: the Critic loves the report, the
Fact-Checker caught an invented figure, and the draft still goes back.

## 5. The verdict is computed, not asked for

```python
class FactCheck(BaseModel):
    unsupported_claims: list[str]  # the only field
```

No `grounded: bool`. The model reports what it found; `grounded = not claims`
is our line of code. Same principle as the Critic's `PASS_THRESHOLD` and
`finalize`'s citation filter: **models produce observations, code makes
decisions.** A test asserts the schema has exactly one field, so nobody
"helpfully" adds the boolean back.

---

## Exercises

1. **Ingest something of your own.** `uv run dossier ingest ~/some-paper.pdf`,
   then research a topic it covers. Which sub-questions cite `[n]` entries
   whose source is your file?
2. **Prove the threshold matters.** Set `DOSSIER_MIN_RELEVANCE=0` and research
   something unrelated to your document. Watch the irrelevant chunk come back.
3. **Plant a lie.** Take a finished report, edit one number to something the
   sources don't say, and run only the fact-checker over it.
4. **Measure your own threshold.** Run
   `similarity_search_with_relevance_scores` for three on-topic and three
   off-topic queries against your documents. Where is the gap?
5. **Watch the fan-out widen.** Run a topic with documents ingested and count
   the researchers in one step; then remove the documents and count again.

## Interview check

1. Why do `web_search` and `doc_search` share a return shape?
2. What does `available_origins()` prevent, and why must it be cheap?
3. Your RAG returns an irrelevant chunk for every query. What's happening?
4. How did you choose the relevance threshold, and when does it stop being valid?
5. Why separate the Fact-Checker from the Critic?
6. Why doesn't the fact-check schema have a `grounded` field?

---

## Postscript: the fact-checker woke the loop up

Lesson 6 ended on an uncomfortable result — the revision loop never fired, even
with the pass threshold raised to 5, because the Critic found no fault in any
real draft. Re-running six topics after this phase:

| | before | after |
|---|---|---|
| average drafts | 1.00 | **1.50** |
| passed on the first draft | 100% | **67%** |
| judge groundedness | 4.85 | **5.00** |

**A second reviewer with a narrower question is what made the difference.** The
Critic judges a whole report and grades it kindly; the Fact-Checker reads one
sentence at a time against numbered evidence and finds things to send back.

That is the argument for decomposition in one number: not "more agents are
better", but "a node with one small question outperforms a node with a big
one". It is also why the eval harness was worth building first — without it
this would be a feeling rather than a measurement.
