"use client";

import { AnimatePresence, motion } from "motion/react";
import { Clock, FileText, Search, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import type { Run } from "@/lib/backend";
import Segmented from "./ui/Segmented";

type Filter = "all" | "done" | "failed";

/** "3 minutes ago" beats a timestamp for recent things, which is most of a
 *  history page; anything older falls back to a date. */
function when(iso?: string): string {
  if (!iso) return "";
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function HistoryList({ runs }: { runs: Run[] }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter(
      (run) =>
        (filter === "all" || run.status === filter) && (!needle || run.topic.toLowerCase().includes(needle)),
    );
  }, [runs, query, filter]);

  const counts = useMemo(
    () => ({
      all: runs.length,
      done: runs.filter((run) => run.status === "done").length,
      failed: runs.filter((run) => run.status === "failed").length,
    }),
    [runs],
  );

  const totalTokens = runs.reduce((sum, run) => sum + (run.tokens ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">History</h1>
          <p className="mt-1 font-mono text-[11.5px] text-muted">
            {runs.length} {runs.length === 1 ? "report" : "reports"} · {totalTokens.toLocaleString()} tokens
          </p>
        </div>
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All", count: counts.all },
            { value: "done", label: "Done", count: counts.done },
            { value: "failed", label: "Failed", count: counts.failed },
          ]}
        />
      </div>

      <div className="relative">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by topic"
          className="w-full rounded-xl border border-line bg-panel py-2.5 pl-10 pr-4 text-[14px] outline-none transition-colors placeholder:text-muted/60 focus:border-accent/50"
        />
      </div>

      {shown.length === 0 ? (
        <p className="rounded-xl border border-line bg-panel px-5 py-12 text-center text-[14px] text-muted">
          {runs.length === 0 ? (
            <>
              Nothing yet.{" "}
              <Link href="/" className="text-accent">
                Research something
              </Link>
              .
            </>
          ) : (
            "No reports match that."
          )}
        </p>
      ) : (
        <ul className="space-y-2">
          <AnimatePresence initial={false}>
            {shown.map((run, index) => (
              <motion.li
                key={run.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.18, delay: Math.min(index * 0.02, 0.15) }}
              >
                <Link
                  href={`/runs/${run.id}`}
                  className="group flex items-center gap-4 rounded-xl border border-line bg-panel px-5 py-4 transition-all hover:border-accent/35 hover:bg-panel-2"
                >
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-bg text-muted transition-colors group-hover:text-accent">
                    {run.status === "failed" ? <XCircle size={16} /> : <FileText size={16} />}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px]">{run.topic}</span>
                    <span className="mt-1 flex items-center gap-3 font-mono text-[11px] text-muted">
                      <span className="flex items-center gap-1">
                        <Clock size={11} />
                        {when(run.created_at)}
                      </span>
                      <span>{run.drafts === 1 ? "1 draft" : `${run.drafts ?? 0} drafts`}</span>
                      <span>{(run.tokens ?? 0).toLocaleString()} tokens</span>
                    </span>
                  </span>

                  <span
                    className={`shrink-0 rounded-full border px-2.5 py-1 font-mono text-[10.5px] ${
                      run.status === "done"
                        ? "border-accent/35 text-accent"
                        : run.status === "failed"
                          ? "border-bad/40 text-bad"
                          : "border-warn/40 text-warn"
                    }`}
                  >
                    {run.status}
                  </span>
                </Link>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}
