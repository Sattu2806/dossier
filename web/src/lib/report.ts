/**
 * Everything we do to a report before showing it.
 *
 * Kept as pure functions away from the components: parsing a citation or
 * counting words has nothing to do with React, and this way it can be reasoned
 * about (and fixed) without opening a single `.tsx` file.
 */
import type { Run } from "./backend";

export type Source = { number: number; title: string; url: string };

const SOURCES_HEADING = /^##\s+Sources\s*$/m;
/** `[4] Some title — https://example.com/page` */
const SOURCE_LINE = /^\[(\d+)\]\s+(.*?)\s+—\s+(\S+)\s*$/;

/** Split the body from the source list the API appends. */
export function parseReport(markdown: string): { body: string; sources: Source[] } {
  if (!markdown) return { body: "", sources: [] };

  const match = markdown.match(SOURCES_HEADING);
  if (!match || match.index === undefined) return { body: markdown.trim(), sources: [] };

  const body = markdown.slice(0, match.index).trim();
  const sources = markdown
    .slice(match.index + match[0].length)
    .split("\n")
    .map((line) => line.match(SOURCE_LINE))
    .filter((found): found is RegExpMatchArray => found !== null)
    .map((found) => ({ number: Number(found[1]), title: found[2], url: found[3] }));

  return { body, sources };
}

/**
 * Turn `[4]` into a link to that source.
 *
 * Done by rewriting Markdown rather than injecting HTML, so the renderer never
 * needs `rehype-raw` — which would let anything the model wrote become live
 * markup. The escaped brackets keep the citation looking like a citation.
 */
export function linkifyCitations(body: string, sources: Source[]): string {
  const known = new Set(sources.map((source) => source.number));
  return body.replace(/\[(\d+)\]/g, (whole, digits) =>
    known.has(Number(digits)) ? `[\\[${digits}\\]](#source-${digits})` : whole,
  );
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

export function headings(body: string): { id: string; text: string }[] {
  return body
    .split("\n")
    .filter((line) => line.startsWith("## "))
    .map((line) => line.replace(/^##\s+/, "").trim())
    .map((text) => ({ id: slugify(text), text }));
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export type Stats = { words: number; minutes: number; citations: number };

export function statsFor(body: string): Stats {
  const words = body.split(/\s+/).filter(Boolean).length;
  return {
    words,
    minutes: Math.max(1, Math.round(words / 220)), // ~220 wpm, the usual reading estimate
    citations: new Set(Array.from(body.matchAll(/\[(\d+)\]/g), (match) => match[1])).size,
  };
}

// --- exports -----------------------------------------------------------------

export function asMarkdown(run: Run): string {
  const meta = [
    `<!-- dossier report`,
    `topic: ${run.topic}`,
    run.created_at ? `generated: ${new Date(run.created_at).toISOString()}` : "",
    `drafts: ${run.drafts ?? 1}`,
    run.grounded === null || run.grounded === undefined ? "" : `fact-checked: ${run.grounded}`,
    `-->`,
  ]
    .filter(Boolean)
    .join("\n");
  return `${meta}\n\n${run.report ?? ""}\n`;
}

/** Plain text: citations kept (they are part of the claim), Markdown syntax removed. */
export function asText(run: Run): string {
  const { body, sources } = parseReport(run.report ?? "");
  const plain = body
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/`(.*?)`/g, "$1");
  const list = sources.map((source) => `[${source.number}] ${source.title}\n    ${source.url}`).join("\n");
  return `${run.topic.toUpperCase()}\n\n${plain}\n\nSOURCES\n${list}\n`;
}

export function asJSON(run: Run): string {
  const { body, sources } = parseReport(run.report ?? "");
  return JSON.stringify(
    {
      topic: run.topic,
      generated_at: run.created_at,
      sub_questions: run.sub_questions ?? [],
      report_markdown: body,
      sources,
      review: {
        drafts: run.drafts,
        fact_checked: run.grounded,
        passed_review: run.passed_review,
        scores: run.critique_scores ?? {},
      },
      usage: { tokens: run.tokens },
    },
    null,
    2,
  );
}

export function filenameFor(run: Run, extension: string): string {
  const slug = slugify(run.topic).slice(0, 60) || "report";
  return `${slug}.${extension}`;
}

export function download(contents: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
