"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  BadgeCheck,
  Braces,
  Check,
  ClipboardCopy,
  Download,
  ExternalLink,
  FileCode,
  FileText,
  Link2,
  Printer,
  ShieldAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Run } from "@/lib/backend";
import {
  asJSON,
  asMarkdown,
  asText,
  domainOf,
  download,
  filenameFor,
  headings,
  linkifyCitations,
  parseReport,
  slugify,
  statsFor,
} from "@/lib/report";
import Menu from "./ui/Menu";
import { useToast } from "./ui/Toast";
import Segmented from "./ui/Segmented";

type View = "report" | "sources" | "markdown" | "details";

export default function ReportView({ run }: { run: Run }) {
  const [view, setView] = useState<View>("report");
  const [copied, setCopied] = useState(false);

  const { body, sources } = useMemo(() => parseReport(run.report ?? ""), [run.report]);
  const linked = useMemo(() => linkifyCitations(body, sources), [body, sources]);
  const outline = useMemo(() => headings(body), [body]);
  const stats = useMemo(() => statsFor(body), [body]);

  const toast = useToast();

  async function copy() {
    await navigator.clipboard.writeText(run.report ?? "");
    setCopied(true);
    toast("Report copied to clipboard");
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <article className="space-y-5">
      <Toolbar run={run} stats={stats} copied={copied} onCopy={copy} />

      <div className="flex items-center justify-between gap-3 print:hidden">
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: "report", label: "Report" },
            { value: "sources", label: "Sources", count: sources.length },
            { value: "markdown", label: "Markdown" },
            { value: "details", label: "Details" },
          ]}
        />
        <span className="font-mono text-[11px] text-muted">
          {stats.words.toLocaleString()} words · {stats.minutes} min read · {stats.citations} cited
        </span>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={view}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
        >
          {view === "report" && <Report body={linked} outline={outline} sources={sources} />}
          {view === "sources" && <Sources sources={sources} />}
          {view === "markdown" && <Raw markdown={run.report ?? ""} />}
          {view === "details" && <Details run={run} />}
        </motion.div>
      </AnimatePresence>
    </article>
  );
}

function Toolbar({
  run,
  stats,
  copied,
  onCopy,
}: {
  run: Run;
  stats: { words: number };
  copied: boolean;
  onCopy: () => void;
}) {
  const toast = useToast();

  function save(contents: string, extension: string, type: string) {
    download(contents, filenameFor(run, extension), type);
    toast(`Saved ${filenameFor(run, extension)}`);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={run.grounded ? "good" : "warn"} icon={run.grounded ? <BadgeCheck size={12} /> : <ShieldAlert size={12} />}>
          {run.grounded ? "Fact-checked" : "Unsupported claims"}
        </Badge>
        <Badge tone={run.passed_review ? "good" : "warn"}>
          {run.passed_review ? "Passed review" : "Published at draft limit"}
        </Badge>
        <Badge tone="plain">{run.drafts === 1 ? "1 draft" : `${run.drafts} drafts`}</Badge>
        {run.tokens ? <Badge tone="plain">{run.tokens.toLocaleString()} tokens</Badge> : null}
      </div>

      <div className="flex items-center gap-2 print:hidden">
        <button
          onClick={onCopy}
          className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-muted transition-colors hover:border-accent/40 hover:text-text"
        >
          {copied ? <Check size={13} className="text-accent" /> : <ClipboardCopy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>

        <Menu
          trigger={
            <>
              <Download size={13} />
              Export
            </>
          }
          items={[
            {
              label: "Markdown",
              hint: ".md",
              icon: <FileCode size={14} />,
              onSelect: () => save(asMarkdown(run), "md", "text/markdown"),
            },
            {
              label: "Plain text",
              hint: ".txt",
              icon: <FileText size={14} />,
              onSelect: () => save(asText(run), "txt", "text/plain"),
            },
            {
              label: "JSON",
              hint: ".json",
              icon: <Braces size={14} />,
              onSelect: () => save(asJSON(run), "json", "application/json"),
            },
            {
              label: "Print or PDF",
              hint: "⌘P",
              icon: <Printer size={14} />,
              // The browser's own print-to-PDF, styled by the print rules in
              // globals.css. A PDF library would add ~300KB to render worse.
              onSelect: () => window.print(),
            },
          ]}
        />
      </div>
    </div>
  );
}

function Report({
  body,
  outline,
  sources,
}: {
  body: string;
  outline: { id: string; text: string }[];
  sources: ReturnType<typeof parseReport>["sources"];
}) {
  return (
    <div className="lg:flex lg:gap-8">
      {outline.length > 1 && (
        <nav className="mb-5 hidden w-52 shrink-0 lg:block print:hidden" aria-label="Contents">
          <p className="mb-3 font-mono text-[10.5px] uppercase tracking-widest text-muted">Contents</p>
          <ul className="space-y-2 border-l border-line">
            {outline.map((heading) => (
              <li key={heading.id}>
                <a
                  href={`#${heading.id}`}
                  className="-ml-px block border-l border-transparent pl-3 text-[13px] leading-snug text-muted transition-colors hover:border-accent hover:text-text"
                >
                  {heading.text}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className="min-w-0 flex-1 space-y-6">
        <div className="report card p-8 sm:p-10 print:border-0 print:bg-white print:p-0">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Anchors for the contents list. Generated from the text, so a
              // renamed section keeps its link working with no extra state.
              h2: ({ children }) => <h2 id={slugify(String(children))}>{children}</h2>,
              a: ({ href, children }) =>
                href?.startsWith("#source-") ? (
                  <a href={href} className="citation">
                    {children}
                  </a>
                ) : (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {children}
                  </a>
                ),
            }}
          >
            {body}
          </ReactMarkdown>
        </div>

        {sources.length > 0 && <SourceList sources={sources} compact />}
      </div>
    </div>
  );
}

function Sources({ sources }: { sources: ReturnType<typeof parseReport>["sources"] }) {
  if (sources.length === 0) {
    return (
      <p className="rounded-xl border border-line bg-panel px-5 py-8 text-center text-[14px] text-muted">
        No sources were cited — the searches found nothing usable for this topic.
      </p>
    );
  }
  return <SourceList sources={sources} />;
}

function SourceList({
  sources,
  compact = false,
}: {
  sources: ReturnType<typeof parseReport>["sources"];
  compact?: boolean;
}) {
  return (
    <section>
      {compact && (
        <h3 className="mb-3 flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-widest text-muted">
          <Link2 size={12} /> Sources
        </h3>
      )}
      <ul className="card divide-y divide-line overflow-hidden">
        {sources.map((source, index) => (
          <motion.li
            key={source.number}
            id={`source-${source.number}`}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(index * 0.02, 0.2), duration: 0.2 }}
            // scroll-mt keeps the sticky header from covering the target when
            // a citation jumps here.
            className="scroll-mt-20 target:bg-panel-2"
          >
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer noopener"
              className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-panel-2"
            >
              <span className="mt-0.5 shrink-0 rounded-md border border-line bg-bg px-1.5 py-0.5 font-mono text-[11px] text-accent">
                {source.number}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] text-text">{source.title}</span>
                <span className="mt-0.5 block truncate font-mono text-[11.5px] text-muted">
                  {domainOf(source.url)}
                </span>
              </span>
              <ExternalLink
                size={13}
                className="mt-1 shrink-0 text-muted opacity-0 transition-opacity group-hover:opacity-100"
              />
            </a>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}

function Raw({ markdown }: { markdown: string }) {
  return (
    <pre className="overflow-x-auto rounded-xl border border-line bg-panel p-5 font-mono text-[12.5px] leading-relaxed text-muted">
      {markdown}
    </pre>
  );
}

function Details({ run }: { run: Run }) {
  const scores = Object.entries(run.critique_scores ?? {});
  return (
    <div className="space-y-5">
      {run.sub_questions && run.sub_questions.length > 0 && (
        <section className="card p-5">
          <h3 className="mb-3 font-mono text-[10.5px] uppercase tracking-widest text-muted">
            Sub-questions researched
          </h3>
          <ol className="space-y-2">
            {run.sub_questions.map((question, index) => (
              <li key={question} className="flex gap-3 text-[14px] text-text">
                <span className="font-mono text-[12px] text-accent/70">{index + 1}</span>
                {question}
              </li>
            ))}
          </ol>
        </section>
      )}

      {scores.length > 0 && (
        <section className="card p-5">
          <h3 className="mb-4 font-mono text-[10.5px] uppercase tracking-widest text-muted">Review scores</h3>
          <div className="space-y-3.5">
            {scores.map(([name, score]) => (
              <div key={name}>
                <div className="mb-1.5 flex justify-between text-[13px]">
                  <span className="capitalize">{name}</span>
                  <span className="font-mono text-muted">{score}/5</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${(score / 5) * 100}%` }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                    className={`h-full rounded-full ${score >= 4 ? "bg-accent" : "bg-warn"}`}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Drafts" value={String(run.drafts ?? 1)} />
        <Stat label="Tokens" value={(run.tokens ?? 0).toLocaleString()} />
        <Stat label="Fact-checked" value={run.grounded ? "yes" : "no"} />
        <Stat label="Passed review" value={run.passed_review ? "yes" : "no"} />
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="font-mono text-[10.5px] uppercase tracking-widest text-muted">{label}</p>
      <p className="mt-1 text-[17px]">{value}</p>
    </div>
  );
}

function Badge({
  children,
  tone,
  icon,
}: {
  children: React.ReactNode;
  tone: "good" | "warn" | "plain";
  icon?: React.ReactNode;
}) {
  const tones = {
    good: "border-accent/35 text-accent",
    warn: "border-warn/40 text-warn",
    plain: "border-line text-muted",
  };
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border bg-panel px-2.5 py-1 font-mono text-[11px] ${tones[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}
