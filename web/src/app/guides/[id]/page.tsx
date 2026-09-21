import Link from "next/link";
import { notFound } from "next/navigation";

import Connect from "@/components/Connect";
import GuideReader, { type Guide } from "@/components/GuideReader";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function GuidePage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await isAuthenticated())) return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;

  const { id } = await params;
  const response = await backendFetch(`/api/guides/${id}`);
  if (response.status === 404) notFound();
  const record = (await response.json()) as { title: string; status: string; error?: string; guide?: Guide };

  return (
    <div className="space-y-6">
      <Link href="/learn" className="font-mono text-[12px] text-muted hover:text-text print:hidden">
        ← your books
      </Link>

      <div>
        <p className="eyebrow mb-2">Study guide</p>
        <h1 className="display text-[clamp(28px,4vw,40px)]">{record.title}</h1>
      </div>

      {record.status === "failed" || !record.guide ? (
        <p className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad">
          {record.error ?? "This guide could not be built."}
        </p>
      ) : (
        <GuideReader guide={record.guide} guideId={id} />
      )}
    </div>
  );
}
