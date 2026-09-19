/**
 * Server-side access to the FastAPI backend.
 *
 * The API key never reaches the browser: it lives in an httpOnly cookie, is
 * read here on the server, and is attached as a bearer token upstream. That is
 * why every call from the client goes through /api/proxy rather than straight
 * to port 8500 — a key in localStorage is readable by any script that gets
 * onto the page.
 */
import { cookies } from "next/headers";

export const BACKEND_URL = process.env.DOSSIER_API_URL ?? "http://127.0.0.1:8500";
export const KEY_COOKIE = "dossier_key";

export async function apiKey(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(KEY_COOKIE)?.value;
}

/** Call the backend with the stored key. Returns the raw Response so callers
 *  can stream it (SSE) or read JSON. */
export async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const key = await apiKey();
  const headers = new Headers(init.headers);
  if (key) headers.set("Authorization", `Bearer ${key}`);
  return fetch(`${BACKEND_URL}${path}`, { ...init, headers, cache: "no-store" });
}

export type Run = {
  id: string;
  topic: string;
  status: "running" | "done" | "failed";
  report?: string;
  error?: string | null;
  drafts?: number;
  grounded?: boolean | null;
  passed_review?: boolean | null;
  tokens?: number;
  sub_questions?: string[];
  critique_scores?: Record<string, number>;
  created_at?: string;
};

export type Me = {
  email: string;
  tokens_used_today: number;
  daily_token_limit: number;
  tokens_remaining: number;
};
