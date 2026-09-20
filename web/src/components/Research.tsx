"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Me, Run } from "@/lib/backend";
import ProgressTimeline, { type Progress } from "./ProgressTimeline";
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

  useEffect(() => () => source.current?.close(), []);

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
      <AnimatePresence initial={false}>
        {phase === "idle" && (
          <motion.section
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.25 }}
          >
            <h1 className="text-[30px] font-semibold leading-tight tracking-tight">
              Research anything,
              <span className="text-accent"> with citations</span>
            </h1>
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">
              Sub-questions are planned, searched in parallel across the web and your documents, drafted, then
              fact-checked against the sources before you see them.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <form onSubmit={submit} className="space-y-3 print:hidden">
        <div className="group relative flex gap-2">
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="A topic, in plain words"
            disabled={busy}
            className="flex-1 rounded-xl border border-line bg-panel px-4 py-3.5 text-[15px] outline-none transition-colors placeholder:text-muted/60 focus:border-accent/50 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || !topic.trim()}
            className="flex items-center gap-2 rounded-xl bg-accent px-5 py-3.5 text-[15px] font-medium text-[#04211a] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            {busy ? "Researching" : "Research"}
          </button>
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

/** Shown while the first draft is being written: something with the shape of a
 *  report reads as progress, where a spinner reads as a stall. */
function Skeleton() {
  return (
    <div className="space-y-3 rounded-xl border border-line bg-panel p-7">
      {[80, 100, 95, 60, 100, 88].map((width, index) => (
        <motion.div
          key={index}
          className="h-3 rounded bg-panel-2"
          style={{ width: `${width}%` }}
          animate={{ opacity: [0.35, 0.75, 0.35] }}
          transition={{ repeat: Infinity, duration: 1.6, delay: index * 0.12 }}
        />
      ))}
    </div>
  );
}
