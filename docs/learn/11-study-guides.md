# Lesson 11 — Teaching a book

**Goal:** upload a PDF and get taught it — lessons in the order the ideas have
to be learned, each explained as if to a five-year-old and then properly, with
a diagram, a worked example and the passages it came from.

```
outline → lesson × N (in parallel) → assemble
```

A second graph rather than a prompt on the first one. The research graph
answers a question from many sources; this one teaches one source. Different
state, different failure modes, different output.

## 1. Why not just prompt the writer differently?

Because almost nothing is shared. The research pipeline plans sub-questions,
fans out to the *web*, drafts one document, and reviews it against its
evidence. A course needs an order of ideas, retrieval scoped to a single book,
one output per lesson, and no review loop at all — a lesson that cites its
passages is either grounded or not.

Forcing both through one graph would mean a state object where half the fields
are always empty, and a prompt with "if this is a book…" in it. Two graphs
sharing `docstore`, `llm` and the SSE plumbing is less code than one graph
with a mode flag.

## 2. Citations need pages, so ingestion changed

`read_pages()` replaced `read_document()`: text per page, with the page number
carried onto every chunk.

```python
{"title": …, "source": …, "chunk": 7, "page": 148,
 "document_id": "3fa0a983", "user_id": 12}
```

`document_id` and `user_id` are what make `scoped_search` possible — retrieval
inside *one book* belonging to *one person*. Without them a study guide would
happily quote somebody else's upload, which is a privacy bug rather than a
quality one.

## 3. An outline cannot be found by similarity

The first instinct is to search the book for "what is this book about". That
returns nothing useful: it matches no passage in particular.

So `document_overview()` reads the **opening chunks in order** instead — the
title page, the preface, the table of contents. That is where a book states
its own shape, and it is the one place plain retrieval is the wrong tool.

## 4. Written twice, on purpose

Each lesson contains both an `eli5` and a `detail`. The simple version is not
a summary of the technical one — it is the **test** of whether the thing was
understood. So the prompt bans jargon outright rather than asking for "simple
language":

> If you cannot say it without a technical term, you have not understood it
> well enough yet.

From a real run, on acknowledgements:

> When a worker takes a job from the line, the helper does not erase it right
> away. It waits to hear back from the worker. If the worker stops working
> before sending the note, the helper gives the job to someone else so it is
> not lost.

No "broker", no "consumer", no "at-least-once". Those words appear in the
`detail` version and in the glossary, where they are defined.

## 5. The diagram bug worth remembering

Lessons ask for Mermaid. The model reliably produced this:

```
flowchart TD
"Producer" --> "Message Queue"
```

Which reads perfectly and renders as **nothing** — Mermaid needs an identifier
before each label: `A["Producer"] --> B["Queue"]`. The first version of the
prompt caused it, by saying "node labels must be plain words in double quotes".

Two fixes, because one was not enough:

1. **Show the syntax in the prompt** instead of describing it, including the
   line "`\"Producer\" --> \"Queue\"` is not valid Mermaid and will not render".
2. **Repair it in code anyway.** `repair_flowchart()` gives quoted nodes
   identifiers, because a prompt makes an outcome likelier, never certain.

The repair itself had a bug the tests caught: the first pattern matched
`"] --> B["` as a label and corrupted diagrams that were already correct. A
node label cannot contain brackets or arrows, and saying so in the pattern
fixed it. **A repair that damages valid input is worse than no repair.**

## 6. Examples are parsed, never run

Every Python example goes through `ast.parse`. The UI shows "syntax checked"
when it passes.

What it deliberately does *not* do is execute it. Running code that a model
wrote, on the server, on behalf of whoever uploaded a PDF, is remote code
execution with a friendly name. `ast.parse` reads the code without running a
line of it, and a test proves it: it parses a snippet that would create a file
and then asserts the file does not exist.

`check_example` returns `None` for languages it cannot check — which is not
the same as `True`, and the UI shows no badge rather than a false one.

## 7. What a real run looks like

A 7-page PDF on message queues, generated for the test:

| | |
|---|---|
| ingest | 7 pages → 7 passages, 1.9s |
| guide | 6 lessons, 8.4s |
| produced | 6 diagrams, 18 questions, 19 glossary terms |
| invented citations | 0 |

Six lessons in parallel is why it is seconds rather than a minute — the same
`Send` fan-out the researchers use.

## 8. Limits, and why each one exists

| limit | default | what it protects |
|---|---|---|
| upload size | 12 MB | memory and bandwidth |
| pages | 400 | embedding calls per upload |
| documents per user | 20 | storage |
| daily tokens | per user | the operator's provider bill |

A scanned PDF extracts as empty strings rather than failing, so it is caught
explicitly and answered with "run it through OCR first" — the most common
"why doesn't this work" upload there is, and useless to answer with a 500.

---

## Exercises

1. **Upload something you are actually trying to learn.** Read lesson 1 in
   "Explain simply", then in "The real thing". Which one told you more?
2. **Check a claim.** Open "Straight from the book" on any lesson and compare a
   sentence in the detail view with the passage it cites.
3. **Break the diagram repair.** Change `repair_flowchart` to match any quoted
   string, then run the tests. Which test catches it?
4. **Try a bad upload**: a scanned PDF, a 500-page book, a `.docx`. Each should
   fail differently and tell you why.
5. **Add a lesson field.** Give `WrittenLesson` a `common_mistakes: list[str]`
   and render it. How much of the pipeline did you have to touch?

## Interview check

1. Why a second graph rather than a flag on the first?
2. Why can't the outline be produced by similarity search?
3. What does `document_id` on a chunk prevent?
4. Why is the ELI5 version not a summary of the detailed one?
5. Why parse the generated code instead of running it?
6. A prompt keeps producing invalid Mermaid. Do you fix the prompt or the code?
