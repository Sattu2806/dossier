import { parseReport, linkifyCitations, headings, statsFor, asText, asJSON, domainOf } from "../src/lib/report";

const report = `# Vector Indexing

HNSW and IVF differ in structure [3]. Memory use is higher for HNSW [8][3].

## Trade-offs

IVF is cheaper to build [4].

## Sources
[3] How to Choose Between IVF and HNSW — https://milvus.io/blog/ivf-hnsw
[4] HNSW vs IVFFlat — https://www.bigdataboutique.com/hnsw
[8] How hnsw algorithms boost search — https://redis.io/blog/hnsw`;

const run = { id: "x", topic: "HNSW vs IVF indexing", status: "done" as const, report, drafts: 1, tokens: 10997, grounded: true, passed_review: true, sub_questions: ["What differs?"], critique_scores: { groundedness: 5 }, created_at: "2026-09-20T10:00:00Z" };

const { body, sources } = parseReport(report);
console.log("sources parsed:", sources.length, sources.map(s => s.number).join(","));
console.log("body excludes source list:", !body.includes("## Sources"));
console.log("domains:", sources.map(s => domainOf(s.url)).join(", "));
console.log("headings:", JSON.stringify(headings(body)));
console.log("stats:", JSON.stringify(statsFor(body)));

const linked = linkifyCitations(body, sources);
console.log("citation linked:", linked.includes("[\\[3\\]](#source-3)"));
console.log("unknown citation untouched:", linkifyCitations("see [99]", sources) === "see [99]");

const text = asText(run);
console.log("text keeps citations:", text.includes("[3]"), "| strips markdown headers:", !text.includes("# Vector"));
console.log("text lists sources:", text.includes("milvus.io/blog/ivf-hnsw"));

const json = JSON.parse(asJSON(run));
console.log("json keys:", Object.keys(json).join(","));
console.log("json sources:", json.sources.length, "| review:", JSON.stringify(json.review));
