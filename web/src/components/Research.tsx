"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Me, Run } from "@/lib/backend";
import Pipeline from "./Pipeline";
import ProgressTimeline, { type Progress } from "./ProgressTimeline";
import Proof from "./Proof";
import ReportView from "./ReportView";

type Phase = "idle" | "running" | "done" | "error";

const EXAMPLES = [
  "solid-state batteries",
  "HNSW vs IVF indexing in vector databases",
  "the effectiveness of rent control",
  "carbon border adjustment mechanisms",
];

export default function Research({ initialMe }: { initialMe: Me | null }) {
  const [me, setMe] = useState<Me | null>(initialMe);
  const [topic, setTopic] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<Progress[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);
  const parameters = useSearchParams();

  useEffect(() => () => source.current?.close(), []);

  // ⌘K can hand a topic over through the URL.
  useEffect(() => {
    const handed = parameters.get("topic");
    if (handed) setTopic(handed);
  }, [parameters]);

  const watch = useCallback((runId: string) => {
    // EventSource rather than fetch: the browser reconnects it on its own, and
    // the credential never travels with the request because the same-origin
    // proxy attaches it server-side.
    const stream = new EventSource(`/api/proxy/api/runs/${runId}/stream`);
    source.current = stream;

    stream.addEventListener("progress", (event) => {
      setSteps((previous) => [...previous, JSON.parse((event as MessageEvent).data) as Progress]);
    });
    stream.addEventListener("done", (event) => {
      setRun(JSON.parse((event as MessageEvent).data) as Run);
      setPhase("done");
      stream.close();
      fetch("/api/proxy/api/me")
        .then((response) => response.json())
        .then(setMe)
        .catch(() => {});
    });
    stream.addEventListener("error", (event) => {
      const raw = (event as MessageEvent).data;
      setError(raw ? (JSON.parse(raw).error as string) : "The connection to the server dropped.");
      setPhase("error");
      stream.close();
    });
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim() || phase === "running") return;

    setPhase("running");
    setSteps([]);
    setRun(null);
    setError(null);

    const response = await fetch("/api/proxy/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });
    const body = await response.json();

    if (!response.ok) {
      setError(body.detail ?? "The request was refused.");
      setPhase("error");
      return;
    }
    watch(body.run_id as string);
  }

  const busy = phase === "running";

  return (
    <div className="space-y-8">
      <AnimatePresence initial={false}>{phase === "idle" && <Hero />}</AnimatePresence>

      <form onSubmit={submit} className="space-y-3 print:hidden">
        <div className="group relative">
          {/* The focus glow sits behind the field rather than on it, so the
              border stays crisp while the surround lights up. */}
          <div className="pointer-events-none absolute -inset-px rounded-2xl bg-gradient-to-r from-accent/0 via-accent/25 to-violet/20 opacity-0 blur transition-opacity duration-300 group-focus-within:opacity-100" />
          <div className="relative flex gap-2 rounded-2xl border border-line bg-panel/90 p-2 backdrop-blur transition-colors group-focus-within:border-accent/40">
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="A topic, in plain words"
              disabled={busy}
              className="flex-1 bg-transparent px-3.5 py-3 text-[16px] outline-none placeholder:text-muted/60 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={busy || !topic.trim()}
              className="flex items-center gap-2 rounded-xl bg-accent px-5 py-3 text-[14.5px] font-medium text-[#04211a] transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <ArrowRight size={15} />}
              {busy ? "Researching" : "Research"}
            </button>
          </div>
        </div>

        {phase === "idle" && (
          <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <span>Try:</span>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setTopic(example)}
                className="rounded-full border border-line bg-panel px-3 py-1 transition-colors hover:border-accent/40 hover:text-text"
              >
                {example}
              </button>
            ))}
          </div>
        )}
      </form>

      {me && (
        <UsageBar used={me.tokens_used_today} limit={me.daily_token_limit} email={me.email} />
      )}

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-start gap-2.5 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad"
          >
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {steps.length > 0 && <ProgressTimeline steps={steps} running={busy} />}

      {busy && !run && <Skeleton />}

      <AnimatePresence>
        {run?.report && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
            <ReportView run={run} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Only while nothing is running: once there is a report, the report is
          the page. */}
      {phase === "idle" && (
        <>
          <div className="hairline" />
          <Pipeline />
          <Proof />
        </>
      )}
    </div>
  );
}

function UsageBar({ used, limit, email }: { used: number; limit: number; email: string }) {
  const percent = Math.min(100, Math.round((used / Math.max(1, limit)) * 100));
  const tight = percent > 80;
  return (
    <div className="print:hidden">
      <div className="mb-1.5 flex justify-between font-mono text-[11px] text-muted">
        <span>{email}</span>
        <span className={tight ? "text-warn" : undefined}>
          {used.toLocaleString()} / {limit.toLocaleString()} tokens today
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-panel">
        <motion.div
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className={`h-full rounded-full ${tight ? "bg-warn" : "bg-accent/60"}`}
        />
      </div>
    </div>
  );
}

/** Shown while the first draft is written: a report-shaped placeholder reads
 *  as progress, where a spinner reads as a stall. */
function Skeleton() {
  return (
    <div className="card relative overflow-hidden p-7">
      <div className="space-y-3.5">
        <div className="mb-6 h-6 w-2/3 rounded bg-panel-3" />
        {[96, 100, 88, 94, 70].map((width, index) => (
          <div key={index} className="h-3 rounded bg-panel-2" style={{ width: `${width}%` }} />
        ))}
      </div>
      {/* One sweeping highlight, rather than five separately pulsing bars:
          it reads as a single object being filled in. */}
      <div className="sweep pointer-events-none absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/[0.045] to-transparent" />
    </div>
  );
}

const HEADLINE = ["Research", "anything,", "with", "citations"];

function Hero() {
  return (
    <motion.section
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
      transition={{ duration: 0.3 }}
      className="pb-2"
    >
      <motion.p
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="eyebrow mb-5"
      >
        Planner · Researchers · Writer · Fact-checker
      </motion.p>

      {/* Word-by-word rather than letter-by-letter: letters look like a demo,
          words look like typesetting. */}
      <h1 className="display max-w-3xl text-[clamp(38px,6.2vw,64px)]">
        {HEADLINE.map((word, index) => (
          <motion.span
            key={word}
            initial={{ opacity: 0, y: 18, filter: "blur(6px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ delay: 0.08 + index * 0.07, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className={`mr-[0.28em] inline-block ${index >= 2 ? "text-accent" : ""}`}
          >
            {word}
          </motion.span>
        ))}
      </h1>

      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.34, duration: 0.5 }}
        className="mt-5 max-w-xl text-[15.5px] leading-relaxed text-muted"
      >
        Sub-questions are planned, searched in parallel across the web and your documents, drafted, then
        fact-checked against the sources before you ever see them.
      </motion.p>
    </motion.section>
  );
}
