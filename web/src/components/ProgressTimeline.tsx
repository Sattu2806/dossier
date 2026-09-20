"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, FileSearch, Globe, ListChecks, PenLine, ScanSearch, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

export type Progress = { step: number; node: string; label: string };

const ICONS: Record<string, React.ReactNode> = {
  validate: <ListChecks size={14} />,
  planner: <Sparkles size={14} />,
  researcher: <Globe size={14} />,
  writer: <PenLine size={14} />,
  fact_checker: <ScanSearch size={14} />,
  critic: <ShieldCheck size={14} />,
  finalize: <FileSearch size={14} />,
};

type Group = { step: number; node: string; label: string; count: number };

/** Several researchers report the same step number. Collapsing them into one
 *  row with a count is also the clearest way to show the fan-out. */
function group(steps: Progress[]): Group[] {
  const groups: Group[] = [];
  for (const step of steps) {
    const last = groups.at(-1);
    if (last && last.step === step.step && last.node === step.node) last.count += 1;
    else groups.push({ ...step, count: 1 });
  }
  return groups;
}

export default function ProgressTimeline({ steps, running }: { steps: Progress[]; running: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  const groups = group(steps);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <span className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-widest text-muted">
          {running && <span className="h-1.5 w-1.5 rounded-full bg-accent pulse" />}
          {running ? "Researching" : "Finished"}
        </span>
        <span className="font-mono text-[11px] text-muted">
          {elapsed > 0 && `${elapsed}s`}
          {!running && steps.length > 0 && " · done"}
        </span>
      </header>

      <ol className="relative px-5 py-4">
        {/* The rail behind the markers; it stops short of the last one so it
            never dangles past the final step. */}
        {groups.length > 1 && <span className="absolute left-[27px] top-7 bottom-7 w-px bg-line" aria-hidden />}

        <AnimatePresence initial={false}>
          {groups.map((entry, index) => {
            const active = running && index === groups.length - 1;
            return (
              <motion.li
                key={`${entry.step}-${entry.node}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
                className="relative flex items-center gap-3 py-1.5"
              >
                <span
                  className={`relative z-10 grid h-5 w-5 shrink-0 place-items-center rounded-full border transition-colors ${
                    active
                      ? "border-accent bg-accent/15 text-accent"
                      : "border-line bg-panel-2 text-muted"
                  }`}
                >
                  {active ? (
                    <motion.span
                      animate={{ scale: [1, 0.82, 1] }}
                      transition={{ repeat: Infinity, duration: 1.2, ease: "easeInOut" }}
                    >
                      {ICONS[entry.node] ?? <Globe size={14} />}
                    </motion.span>
                  ) : (
                    <Check size={12} className="text-accent/70" />
                  )}
                </span>

                <span className="text-[14px] text-text">{entry.label}</span>

                {entry.count > 1 && (
                  <motion.span
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="rounded-full border border-line bg-panel-2 px-2 py-0.5 font-mono text-[10.5px] text-muted"
                  >
                    ×{entry.count} in parallel
                  </motion.span>
                )}
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
    </section>
  );
}
