import Link from "next/link";

import Connect from "@/components/Connect";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated, type Run } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function History() {
  if (!(await isAuthenticated())) return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;

  let runs: Run[] = [];
  try {
    const response = await backendFetch("/api/runs");
    if (response.ok) runs = ((await response.json()) as { runs: Run[] }).runs;
  } catch {
    return <p className="text-warn">The research API is not responding.</p>;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">History</h1>

      {runs.length === 0 ? (
        <p className="text-muted">
          Nothing yet.{" "}
          <Link href="/" className="text-accent">
            Research something
          </Link>
          .
        </p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-panel">
          {runs.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-panel-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-[15px]">{run.topic}</p>
                  <p className="mt-1 font-mono text-[11.5px] text-muted">
                    {new Date(run.created_at ?? "").toLocaleString()} · {run.drafts ?? 0} drafts ·{" "}
                    {(run.tokens ?? 0).toLocaleString()} tokens
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full border px-2.5 py-1 font-mono text-[11px] ${
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
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
