# Lesson 4 — The Writer: grounding, citations, revisions

**Goal:** turn notes into a report a person would actually read, where every
claim points at a source, gaps are admitted rather than filled in, and a
revision improves the previous draft instead of starting over.

## What changed

```
src/dossier/
├── prompts.py        WRITER_SYSTEM
├── nodes.py          real writer, _prepare_evidence, cited_numbers, richer finalize
├── graph.py          writer is real + gets the retry policy
└── fakes.py          fake writer now cites [1], like the real one
tests/
├── conftest.py       NEW  shared FakeModel (structured or prose)
└── test_writer.py    NEW  evidence numbering, revision prompt, citation filtering
```

---

## 1. Prose output: no structured output here

The Planner needed fields, so it used a Pydantic schema. A report is prose, so
the Writer calls the model plainly and reads the text:

```python
reply = chat_model().invoke([SystemMessage(WRITER_SYSTEM), HumanMessage(...)])
draft = reply.text.strip()
```

`.text` is doing quiet work. A modern model can return `content` as a **list of
content blocks** (thinking blocks, text blocks, tool calls) rather than a
string. Your prototype had an `extract_text()` helper for exactly this.
langchain-core 1.x has it built in: `AIMessage.text` flattens both shapes,
verified on a plain string and a list of blocks.

Structured output has no content failure mode here except one: an **empty**
reply. That raises `OutputParserException`, so the retry policy we added for
the Planner applies to the Writer too.

## 2. The model never writes a URL

`_prepare_evidence(notes)` builds the evidence block the model sees:

```
### Sub-question: What are the primary material compositions...?
[1] All-Solid-State Batteries: Status & Research Analysis
Sulfide-based electrolytes...
[2] Solid-State Battery Electrolyte Materials Market
Halide-based electrolytes...
### Sub-question: Is X safe?
NO EVIDENCE AVAILABLE — Search failed (TimeoutError).
```

Four decisions:

- **Numbers are assigned per unique URL**, so a page found by two sub-questions
  keeps one number.
- **The model cites `[2]`, never a URL.** Models mangle and invent URLs; they
  handle small integers reliably. We render the source list ourselves from the
  same numbering, so a citation can't point at a page that doesn't exist.
- **Gaps are in the prompt**, using the `status` field from Step 3. The model
  is told there's no evidence and instructed to say so. If the gap were simply
  missing from the prompt, the model would answer from memory, which is exactly
  the hallucination we're trying to prevent.
- **It's a pure function**, so the Writer and Finalize both call it instead of
  storing its output in the state. Same notes in, same numbers out. Derive
  what you can derive; only store what you can't.

## 3. Finalize lists only what was cited

The live run gave the Writer 12 sources; the report cited 9. A "Sources"
section listing three pages the report never used is misleading, so
`finalize` filters:

```python
cited = cited_numbers(draft)  # {1, 2, 4, 5, ...} via regex
invented = cited - sources.keys()
if invented:
    logger.warning("draft cites source numbers that do not exist: %s", sorted(invented))
used = [f"[{n}] {sources[n]}" for n in sorted(cited & sources.keys())]
```

That `invented` check is a **cheap verification layer**: we know exactly which
numbers we handed out, so a citation outside that set is provably made up. It
costs one regex and no tokens. Phase 2's Fact-Checker does the expensive
version (does the cited source actually *support* the claim?).

A pattern worth keeping: whenever an LLM produces a reference to something you
control, check the reference against the real thing.

**The trade-off:** the kept numbers aren't renumbered, so a real report's list
reads `[2] [3] [4] [5] [7] ...` with gaps. Renumbering would mean rewriting the
citations inside the model's prose, and string surgery on generated text breaks
in ways a gap in numbering never will. The numbers identify evidence items, not
list positions.

## 4. Revisions: the previous draft must be in the prompt

```python
if previous_draft and feedback:
    request += ["", "Your previous draft:", previous_draft, "", "Reviewer feedback to address:", feedback]
```

Your prototype passed the feedback but not the draft, so "section 2 is vague"
was unactionable and the model wrote a fresh report each time. With both, the
model edits.

**Measured on the live run** (fake critic rejecting draft 1): draft 1 was 460
words, draft 2 was 462, and a diff shows **only the conclusion paragraph
changed**. The rest was byte-identical. The revision *was* an edit, not a rewrite.
The design works.

### The uncomfortable part

The fake critic's feedback was *"Add a conclusion section."* — and draft 1
**already had a Conclusion**. The model didn't push back. It reworded the
conclusion to look responsive and cost us a full paid LLM call for no
improvement.

That's a real property of these systems: **models comply with feedback, whether
or not the feedback is right.** Consequences:

- The Critic's quality sets the ceiling on the whole loop. A sloppy critic
  doesn't just fail to help, it actively burns money and can make drafts worse.
- "Did revision improve the report?" is a question for measurement, not faith.
  Step 8 will score draft 1 against the final draft across the eval set. If
  revisions don't raise the score, the loop is decoration.

This is why Step 5 gets the most care of any node.

## 5. Token budget, measured

From a real run (9 notes, 9 unique sources):

| | chars | ~tokens |
|---|---|---|
| evidence block | 8,682 | 2,170 |
| first-draft prompt | 9,657 | 2,414 |
| revision prompt (+ previous draft) | 10,890 | 2,722 |
| **worst case, 3 drafts** | | **~7,900 input tokens** |

Two things follow:

1. **The evidence block dominates**, which is why `MAX_RESULTS` and
   `MAX_NOTE_CHARS` live in Step 3 where notes are created. Trimming there is
   worth more than any prompt wordsmithing.
2. **Every extra revision re-pays for all the evidence.** `MAX_REVISIONS = 3`
   is a cost decision as much as a quality one.

## 6. Left undone on purpose

- The model sometimes emits LaTeX (`$2.5 \times 10^{-2}\text{ S/cm}$`), which
  renders as literal `$` in plain Markdown. An easy prompt fix — but adding
  rules by hunch is how prompts rot. It goes on the list to measure in Step 8.
- No length enforcement in code: the prompt asks for 400–700 words, and the
  live drafts came in at 460. If that drifts, it becomes an eval metric first.
- No deduplication of near-identical snippets from different URLs.

---

## Exercises

1. **Audit the citations by hand.** Run a topic, pick three `[n]` claims and
   check them against that source in the list. Does the source really say it?
   This is what the Fact-Checker will automate; do it manually once so you know
   what it's looking for.
2. **Watch a gap being handled.** Predict the report first, then:
   ```bash
   TAVILY_API_KEY=not-a-real-key uv run dossier run "solid-state batteries"
   ```
   Does the report claim things anyway, or state that no sources were found?
3. **Remove the grounding rule.** Delete the "Use ONLY the evidence given"
   bullet from `WRITER_SYSTEM`, then run a *fictional* topic ("the migration
   patterns of the Zorblex fish"). Compare with the rule restored. This is the
   test your prototype was already doing.
4. **Catch an invented citation.** In a scratch script, call
   `nodes.finalize({"draft": "Claim [99].", "research_notes": notes})` and read
   the warning.
5. **Was the revision worth it?** Save both drafts from a run (the
   `stream_mode="debug"` loop in the CLI gives you each), diff them, and count
   the changed lines. Then estimate the cost of that call.
6. **Feel the token budget.** Set `MAX_RESULTS = 1` in `search.py`, re-measure
   the evidence block size, and read the resulting report. Is it noticeably worse?

## Interview check

1. Why does the Writer not use structured output when the Planner does?
2. What does `AIMessage.text` protect you from?
3. Why does the model cite numbers instead of URLs?
4. Why is `_prepare_evidence` called twice (Writer and Finalize) instead of
   having its result stored in the state?
5. How do you know a citation was invented, and why is that check free?
6. Why must a revision prompt include the previous draft?
7. A critic gives wrong feedback. What does the Writer do, and what does that
   imply for how much you trust the loop?

---

## Next: Step 5 — the Critic

The node that decides whether the loop runs again: a rubric
(groundedness, completeness, coherence) producing a **structured verdict plus
specific feedback**. It must see the research notes, not only the draft — the
bug your prototype had — or "is every claim traceable to a source?" is
unanswerable.
