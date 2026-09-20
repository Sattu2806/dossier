import Link from "next/link";
import { notFound } from "next/navigation";

import Connect from "@/components/Connect";
import ReportView from "@/components/ReportView";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated, type Run } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await isAuthenticated())) return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;

  const { id } = await params;
  const response = await backendFetch(`/api/runs/${id}`);
  if (response.status === 404) notFound();
  const run = (await response.json()) as Run;

  return (
    <div className="space-y-5">
      <Link href="/history" className="font-mono text-[12px] text-muted hover:text-text print:hidden">
        ← history
      </Link>

      <h1 className="text-2xl font-semibold tracking-tight">{run.topic}</h1>

      {run.status === "failed" ? (
        <p className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad">{run.error}</p>
      ) : (
        <ReportView run={run} />
      )}
    </div>
  );
}
