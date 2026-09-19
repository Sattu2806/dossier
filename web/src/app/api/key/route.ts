import { NextResponse } from "next/server";

import { BACKEND_URL, KEY_COOKIE } from "@/lib/backend";

/** Store an API key, but only after proving it works — a cookie holding a bad
 *  key would fail on every later request with no obvious cause. */
export async function POST(request: Request) {
  const { key } = (await request.json()) as { key?: string };
  if (!key) return NextResponse.json({ error: "No key supplied" }, { status: 400 });

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/api/me`, {
      headers: { Authorization: `Bearer ${key}` },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: `Cannot reach the API at ${BACKEND_URL}` }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json({ error: "That key was rejected by the API" }, { status: 401 });
  }

  const response = NextResponse.json(await upstream.json());
  response.cookies.set(KEY_COOKIE, key, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(KEY_COOKIE);
  return response;
}
