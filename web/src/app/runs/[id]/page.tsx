import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import Connect from "@/components/Connect";
import { apiKey, backendFetch, type Run } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await apiKey())) return <Connect />;

  const { id } = await params;
  const response = await backendFetch(`/api/runs/${id}`);
  if (response.status === 404) notFound();
  const run = (await response.json()) as Run;

  return (
    <article className="space-y-5">
      <Link href="/history" className="font-mono text-[12px] text-muted hover:text-text">
        ← history
      </Link>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{run.topic}</h1>
        {run.sub_questions && run.sub_questions.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {run.sub_questions.map((question) => (
              <li key={question} className="flex gap-2.5 text-[14px] text-muted">
                <span className="text-accent/60">·</span>
                {question}
              </li>
            ))}
          </ul>
        )}
      </div>

      {run.status === "failed" ? (
        <p className="rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad">{run.error}</p>
      ) : (
        <div className="report rounded-xl border border-line bg-panel p-7">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{run.report ?? ""}</ReactMarkdown>
        </div>
      )}
    </article>
  );
}
