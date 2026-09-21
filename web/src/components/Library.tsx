"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, BookOpen, FileUp, Loader2, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import ProgressTimeline, { type Progress } from "./ProgressTimeline";
import { useToast } from "./ui/Toast";

export type Document = { id: string; title: string; filename: string; pages: number; chunks: number };
export type GuideSummary = { id: string; document_id: string; title: string; status: string };

export default function Library({
  documents: initial,
  guides,
}: {
  documents: Document[];
  guides: GuideSummary[];
}) {
  const router = useRouter();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);

  const [documents, setDocuments] = useState(initial);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState<string | null>(null);
  const [steps, setSteps] = useState<Progress[]>([]);

  async function upload(file: File) {
    setUploading(true);
    setError(null);

    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/proxy/api/documents", { method: "POST", body });
    const result = await response.json();
    setUploading(false);

    if (!response.ok) {
      setError(result.detail ?? "That upload was refused.");
      return;
    }
    setDocuments((current) => [result as Document, ...current]);
    toast(`${result.title} is ready — ${result.pages} pages`);
  }

  async function buildGuide(documentId: string) {
    setBuilding(documentId);
    setSteps([]);
    setError(null);

    const response = await fetch("/api/proxy/api/guides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId }),
    });
    const result = await response.json();

    if (!response.ok) {
      setError(result.detail ?? "Could not start.");
      setBuilding(null);
      return;
    }

    const stream = new EventSource(`/api/proxy/api/guides/${result.guide_id}/stream`);
    stream.addEventListener("progress", (event) => {
      setSteps((previous) => [...previous, JSON.parse((event as MessageEvent).data) as Progress]);
    });
    stream.addEventListener("done", () => {
      stream.close();
      router.push(`/guides/${result.guide_id}`);
    });
    stream.addEventListener("error", (event) => {
      const raw = (event as MessageEvent).data;
      setError(raw ? (JSON.parse(raw).error as string) : "The connection dropped.");
      setBuilding(null);
      stream.close();
    });
  }

  return (
    <div className="space-y-8">
      <section>
        <p className="eyebrow mb-4">Learn a book</p>
        <h1 className="display text-[clamp(30px,4.6vw,46px)]">
          Upload a PDF.<span className="text-accent"> Get taught it.</span>
        </h1>
        <p className="mt-4 max-w-xl text-[15.5px] leading-relaxed text-muted">
          The book is split into lessons in the order the ideas have to be learned. Each one is explained as if
          you were five, then properly — with a diagram, a worked example and the passages it came from.
        </p>
      </section>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file) upload(file);
        }}
        onClick={() => input.current?.click()}
        className={`cursor-pointer rounded-2xl border border-dashed p-10 text-center transition-colors ${
          dragging ? "border-accent bg-accent/[0.06]" : "border-line bg-panel/60 hover:border-accent/40"
        }`}
      >
        <input
          ref={input}
          type="file"
          accept=".pdf,.txt,.md"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) upload(file);
            event.target.value = "";
          }}
        />
        {uploading ? (
          <>
            <Loader2 size={22} className="mx-auto mb-3 animate-spin text-accent" />
            <p className="text-[15px]">Reading and indexing…</p>
            <p className="mt-1 text-[13px] text-muted">Every page is embedded so lessons can quote it</p>
          </>
        ) : (
          <>
            <FileUp size={22} className="mx-auto mb-3 text-muted" />
            <p className="text-[15px]">Drop a PDF here, or click to choose</p>
            <p className="mt-1 font-mono text-[11.5px] text-muted">PDF, text or Markdown · up to 12 MB · 400 pages</p>
          </>
        )}
      </div>

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

      {building && steps.length > 0 && <ProgressTimeline steps={steps} running />}

      {documents.length > 0 && (
        <section>
          <p className="eyebrow mb-3">Your books</p>
          <ul className="space-y-2">
            {documents.map((document) => {
              const existing = guides.find(
                (guide) => guide.document_id === document.id && guide.status === "done",
              );
              return (
                <li key={document.id} className="card flex flex-wrap items-center gap-4 px-5 py-4">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-bg text-muted">
                    <BookOpen size={16} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px]">{document.title}</span>
                    <span className="mt-0.5 block font-mono text-[11px] text-muted">
                      {document.pages} pages · {document.chunks} passages indexed
                    </span>
                  </span>

                  {existing ? (
                    <a
                      href={`/guides/${existing.id}`}
                      className="rounded-lg border border-line px-3.5 py-2 text-[13.5px] text-muted transition-colors hover:border-accent/40 hover:text-text"
                    >
                      Open guide
                    </a>
                  ) : (
                    <button
                      onClick={() => buildGuide(document.id)}
                      disabled={building !== null}
                      className="flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-[13.5px] font-medium text-[#04211a] transition-opacity hover:opacity-90 disabled:opacity-40"
                    >
                      {building === document.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Sparkles size={14} />
                      )}
                      Teach me this
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
