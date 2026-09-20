/**
 * Server-side access to the FastAPI backend.
 *
 * Two credentials, one backend:
 *
 * - **Signed in with Clerk** → forward that session token. The API verifies it
 *   against Clerk's JWKS and creates the account on first sight, so each
 *   person gets their own history and their own budget.
 * - **No Clerk configured** (self-hosting, local development) → fall back to
 *   an API key held in an httpOnly cookie.
 *
 * Either way the credential is attached here, on the server. It never reaches
 * the browser, which is also why every client call goes through /api/proxy
 * rather than straight to the API.
 */
import { auth } from "@clerk/nextjs/server";
import { cookies } from "next/headers";

export const BACKEND_URL = process.env.DOSSIER_API_URL ?? "http://127.0.0.1:8500";
export const KEY_COOKIE = "dossier_key";

export function clerkIsConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);
}

export async function apiKey(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(KEY_COOKIE)?.value;
}

/** The bearer token for this request: a Clerk session if there is one, else
 *  the stored API key. */
export async function credential(): Promise<string | undefined> {
  if (clerkIsConfigured()) {
    const { getToken } = await auth();
    const token = await getToken();
    if (token) return token;
  }
  return apiKey();
}

export async function isAuthenticated(): Promise<boolean> {
  return Boolean(await credential());
}

/** Call the backend with whichever credential applies. Returns the raw
 *  Response so callers can stream it (SSE) or read JSON. */
export async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await credential();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
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
  auth: "clerk" | "api_key";
};
