import { NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: Request, context: Context, method: "GET" | "POST") {
  const { path } = await context.params;
  const target = `/${path.join("/")}${new URL(request.url).search}`;

  let upstream: Response;
  try {
    upstream = await backendFetch(target, {
      method,
      body: method === "POST" ? await request.text() : undefined,
      headers: method === "POST" ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    return NextResponse.json({ detail: "The research API is not reachable." }, { status: 502 });
  }

  // Server-Sent Events are passed through as a stream rather than awaited:
  // buffering the body here would hold every progress event until the run
  // finished, which defeats the point of streaming.
  if (upstream.headers.get("content-type")?.includes("text/event-stream")) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  }

  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = (request: Request, context: Context) => forward(request, context, "GET");
export const POST = (request: Request, context: Context) => forward(request, context, "POST");
