"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronRight,
  CircleDot,
  Lightbulb,
  Quote,
  Terminal,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import Diagram from "./Diagram";
import Segmented from "./ui/Segmented";

export type Lesson = {
  number: number;
  title: string;
  covers?: string;
  status: string;
  eli5?: string;
  analogy?: string;
  detail?: string;
  diagram?: string;
  example?: string;
  example_language?: string;
  example_valid?: boolean | null;
  example_walkthrough?: string;
  key_terms?: { term: string; plain: string }[];
  questions?: { question: string; answer: string }[];
  passages?: { number: number; page: number; quote: string }[];
};

export type Guide = {
  title: string;
  lessons: Lesson[];
  glossary: { term: string; plain: string }[];
  stats: { lessons: number; written: number; diagrams: number; questions: number; terms: number };
};

type Depth = "simple" | "full";

export default function GuideReader({ guide, guideId }: { guide: Guide; guideId: string }) {
  const [current, setCurrent] = useState(0);
  const [depth, setDepth] = useState<Depth>("simple");
  const [done, setDone] = useState<Set<number>>(new Set());

  // Progress is per-reader and worth nothing to anyone else, so it stays in
  // the browser rather than becoming a table and an endpoint.
  useEffect(() => {
    const saved = localStorage.getItem(`guide-progress-${guideId}`);
    if (saved) setDone(new Set(JSON.parse(saved) as number[]));
  }, [guideId]);

  function toggleDone(number: number) {
    setDone((previous) => {
      const next = new Set(previous);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      localStorage.setItem(`guide-progress-${guideId}`, JSON.stringify([...next]));
      return next;
    });
  }

  const lesson = guide.lessons[current];
  const progress = Math.round((done.size / Math.max(1, guide.lessons.length)) * 100);

  return (
    <div className="lg:flex lg:gap-8">
      <aside className="mb-6 lg:sticky lg:top-24 lg:mb-0 lg:h-fit lg:w-64 lg:shrink-0 print:hidden">
        <p className="eyebrow mb-3">{guide.stats.lessons} lessons</p>

        <div className="mb-4">
          <div className="mb-1.5 flex justify-between font-mono text-[10.5px] text-muted">
            <span>{done.size} done</span>
            <span>{progress}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-panel">
            <motion.div
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.4 }}
              className="h-full rounded-full bg-accent"
            />
          </div>
        </div>

        <ol className="space-y-1">
          {guide.lessons.map((entry, index) => (
            <li key={entry.number}>
              <button
                onClick={() => setCurrent(index)}
                className={`flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left text-[13.5px] transition-colors ${
                  index === current ? "bg-panel-2 text-text" : "text-muted hover:bg-panel/60 hover:text-text"
                }`}
              >
                <span className="mt-0.5 shrink-0">
                  {done.has(entry.number) ? (
                    <Check size={13} className="text-accent" />
                  ) : (
                    <CircleDot size={13} className={index === current ? "text-accent" : "text-muted/60"} />
                  )}
                </span>
                <span className="leading-snug">{entry.title}</span>
              </button>
            </li>
          ))}
        </ol>
      </aside>

      <div className="min-w-0 flex-1">
        <AnimatePresence mode="wait">
          <motion.article
            key={lesson.number}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22 }}
            className="space-y-6"
          >
            <header>
              <p className="eyebrow mb-2">Lesson {lesson.number}</p>
              <h2 className="display text-[clamp(26px,3.4vw,34px)]">{lesson.title}</h2>
              {lesson.covers && <p className="mt-2 text-[15px] text-muted">{lesson.covers}</p>}
            </header>

            {lesson.status !== "ok" ? (
              <p className="flex items-start gap-2.5 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-[14px] text-warn">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                This lesson could not be written from the uploaded text.
              </p>
            ) : (
              <>
                <div className="flex items-center justify-between gap-3">
                  <Segmented
                    value={depth}
                    onChange={setDepth}
                    options={[
                      { value: "simple", label: "Explain simply" },
                      { value: "full", label: "The real thing" },
                    ]}
                  />
                  <button
                    onClick={() => toggleDone(lesson.number)}
                    className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] transition-colors ${
                      done.has(lesson.number)
                        ? "border-accent/40 text-accent"
                        : "border-line text-muted hover:text-text"
                    }`}
                  >
                    <Check size={13} />
                    {done.has(lesson.number) ? "Done" : "Mark done"}
                  </button>
                </div>

                <AnimatePresence mode="wait">
                  <motion.div
                    key={depth}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.16 }}
                    className="space-y-5"
                  >
                    {depth === "simple" ? (
                      <>
                        <div className="report card p-6 sm:p-7">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{lesson.eli5 ?? ""}</ReactMarkdown>
                        </div>
                        {lesson.analogy && (
                          <div className="flex gap-3 rounded-xl border border-violet/25 bg-violet/[0.06] p-5">
                            <Lightbulb size={16} className="mt-0.5 shrink-0 text-violet" />
                            <p className="text-[15px] leading-relaxed text-text-dim">{lesson.analogy}</p>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="report card p-6 sm:p-7">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{lesson.detail ?? ""}</ReactMarkdown>
                      </div>
                    )}
                  </motion.div>
                </AnimatePresence>

                {lesson.diagram && (
                  <section>
                    <p className="eyebrow mb-3">How it fits together</p>
                    <Diagram source={lesson.diagram} />
                  </section>
                )}

                {lesson.example && (
                  <section>
                    <div className="mb-3 flex items-center justify-between">
                      <p className="eyebrow flex items-center gap-2">
                        <Terminal size={12} /> Worked example
                      </p>
                      <span className="flex items-center gap-2 font-mono text-[10.5px] text-muted">
                        {lesson.example_language}
                        {lesson.example_valid === true && (
                          <span className="rounded-full border border-accent/35 px-2 py-0.5 text-accent">
                            syntax checked
                          </span>
                        )}
                        {lesson.example_valid === false && (
                          <span className="rounded-full border border-warn/40 px-2 py-0.5 text-warn">
                            does not parse
                          </span>
                        )}
                      </span>
                    </div>
                    <pre className="overflow-x-auto rounded-xl border border-line bg-panel-2 p-5 font-mono text-[12.5px] leading-relaxed text-text-dim">
                      {lesson.example}
                    </pre>
                    {lesson.example_walkthrough && (
                      <p className="mt-3 text-[14px] leading-relaxed text-muted">{lesson.example_walkthrough}</p>
                    )}
                  </section>
                )}

                {lesson.key_terms && lesson.key_terms.length > 0 && (
                  <section>
                    <p className="eyebrow mb-3">Words this lesson used</p>
                    <dl className="card divide-y divide-line">
                      {lesson.key_terms.map((term) => (
                        <div key={term.term} className="px-5 py-3">
                          <dt className="font-mono text-[12.5px] text-accent">{term.term}</dt>
                          <dd className="mt-1 text-[14px] text-text-dim">{term.plain}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                )}

                {lesson.questions && lesson.questions.length > 0 && (
                  <section>
                    <p className="eyebrow mb-3">Check yourself</p>
                    <div className="space-y-2">
                      {lesson.questions.map((item, index) => (
                        <Question key={index} question={item.question} answer={item.answer} />
                      ))}
                    </div>
                  </section>
                )}

                {lesson.passages && lesson.passages.length > 0 && (
                  <details className="card p-5">
                    <summary className="flex cursor-pointer items-center gap-2 text-[13.5px] text-muted">
                      <Quote size={13} />
                      Straight from the book ({lesson.passages.length} passages)
                    </summary>
                    <ul className="mt-4 space-y-3">
                      {lesson.passages.map((passage) => (
                        <li key={passage.number} className="border-l-2 border-line pl-3">
                          <p className="font-mono text-[10.5px] text-muted">
                            [{passage.number}] page {passage.page}
                          </p>
                          <p className="mt-1 text-[13.5px] italic leading-relaxed text-text-dim">
                            {passage.quote}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}

            <nav className="flex items-center justify-between border-t border-line pt-5">
              <button
                onClick={() => setCurrent((index) => Math.max(0, index - 1))}
                disabled={current === 0}
                className="text-[14px] text-muted transition-colors hover:text-text disabled:opacity-30"
              >
                ← Previous
              </button>
              <button
                onClick={() => {
                  toggleDone(lesson.number);
                  setCurrent((index) => Math.min(guide.lessons.length - 1, index + 1));
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                disabled={current === guide.lessons.length - 1}
                className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-[14px] font-medium text-[#04211a] transition-opacity hover:opacity-90 disabled:opacity-30"
              >
                Next lesson <ChevronRight size={15} />
              </button>
            </nav>
          </motion.article>
        </AnimatePresence>

        {guide.glossary.length > 0 && (
          <section className="mt-10">
            <p className="eyebrow mb-3 flex items-center gap-2">
              <BookOpen size={12} /> Glossary for the whole book
            </p>
            <dl className="card grid gap-x-6 gap-y-3 p-5 sm:grid-cols-2">
              {guide.glossary.map((entry) => (
                <div key={entry.term}>
                  <dt className="font-mono text-[12px] capitalize text-accent">{entry.term}</dt>
                  <dd className="mt-0.5 text-[13.5px] text-muted">{entry.plain}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>
    </div>
  );
}

function Question({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((previous) => !previous)}
        className="flex w-full items-start gap-3 px-5 py-3.5 text-left text-[14.5px] transition-colors hover:bg-panel-2"
      >
        <ChevronRight
          size={15}
          className={`mt-0.5 shrink-0 text-muted transition-transform ${open ? "rotate-90" : ""}`}
        />
        {question}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <p className="border-t border-line px-5 py-3.5 text-[14px] leading-relaxed text-text-dim">
              {answer}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
