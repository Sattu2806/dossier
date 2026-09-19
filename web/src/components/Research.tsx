"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Me, Run } from "@/lib/backend";

type Progress = { step: number; node: string; label: string };
type Phase = "idle" | "running" | "done" | "error";

const EXAMPLES = [
  "solid-state batteries",
  "HNSW vs IVF indexing in vector databases",
  "the effectiveness of rent control",
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
    // EventSource, not fetch: the browser reconnects it automatically, and the
    // key never has to travel with the request because the same-origin proxy
    // holds it in an httpOnly cookie.
    const stream = new EventSource(`/api/proxy/api/runs/${runId}/stream`);
    source.current = stream;

    stream.addEventListener("progress", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as Progress;
      setSteps((previous) => [...previous, data]);
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

  const grouped = groupSteps(steps);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-[28px] font-semibold tracking-tight">Research anything, with citations</h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted">
          Sub-questions are planned, searched in parallel across the web and your own documents, drafted,
          then fact-checked against the sources before you see them.
        </p>
      </section>

      <form onSubmit={submit} className="space-y-3">
        <div className="flex gap-2">
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="A topic, in plain words"
            disabled={phase === "running"}
            className="flex-1 rounded-lg border border-line bg-panel px-4 py-3 text-[15px] outline-none transition-colors placeholder:text-muted/60 focus:border-accent/50 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={phase === "running" || !topic.trim()}
            className="rounded-lg bg-accent px-5 py-3 text-[15px] font-medium text-[#04211a] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {phase === "running" ? "Researching…" : "Research"}
          </button>
        </div>
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
      </form>

      {me && (
        <p className="font-mono text-xs text-muted">
          {me.email} · {me.tokens_used_today.toLocaleString()} / {me.daily_token_limit.toLocaleString()} tokens
          used today
        </p>
      )}

      {error && (
        <div className="rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad">{error}</div>
      )}

      {steps.length > 0 && (
        <section className="rounded-xl border border-line bg-panel p-5">
          <h2 className="mb-4 font-mono text-[11px] uppercase tracking-widest text-muted">Progress</h2>
          <ol className="space-y-2.5">
            {grouped.map((group) => (
              <li key={group.step} className="flex items-center gap-3 text-[14px]">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    group.active && phase === "running" ? "bg-accent pulse" : "bg-accent/45"
                  }`}
                />
                <span className="text-text">{group.label}</span>
                {group.count > 1 && (
                  <span className="rounded-full border border-line bg-panel-2 px-2 py-0.5 font-mono text-[11px] text-muted">
                    ×{group.count} in parallel
                  </span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {run?.report && (
        <article className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={run.grounded ? "good" : "warn"}>
              {run.grounded ? "Fact-checked" : "Unsupported claims found"}
            </Badge>
            <Badge tone={run.passed_review ? "good" : "warn"}>
              {run.passed_review ? "Passed review" : "Published after review limit"}
            </Badge>
            <Badge tone="plain">{run.drafts === 1 ? "1 draft" : `${run.drafts} drafts`}</Badge>
            <Badge tone="plain">{(run.tokens ?? 0).toLocaleString()} tokens</Badge>
            {run.critique_scores &&
              Object.entries(run.critique_scores).map(([name, score]) => (
                <Badge key={name} tone="plain">
                  {name} {score}/5
                </Badge>
              ))}
          </div>

          <div className="report rounded-xl border border-line bg-panel p-7">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{run.report}</ReactMarkdown>
          </div>
        </article>
      )}
    </div>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "good" | "warn" | "plain" }) {
  const tones = {
    good: "border-accent/35 text-accent",
    warn: "border-warn/40 text-warn",
    plain: "border-line text-muted",
  };
  return (
    <span className={`rounded-full border bg-panel px-2.5 py-1 font-mono text-[11px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** Several researchers report the same step number: show them as one line with
 *  a count, which is also the clearest way to make the fan-out visible. */
function groupSteps(steps: Progress[]) {
  const groups: { step: number; label: string; count: number; active: boolean }[] = [];
  for (const step of steps) {
    const last = groups.at(-1);
    if (last && last.step === step.step) last.count += 1;
    else groups.push({ step: step.step, label: step.label, count: 1, active: false });
  }
  if (groups.length) groups[groups.length - 1].active = true;
  return groups;
}
