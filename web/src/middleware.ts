import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * Attaches Clerk's auth context so `auth()` works in server components and
 * route handlers — but only when Clerk is actually configured.
 *
 * `clerkMiddleware()` throws without a publishable key, and middleware runs on
 * every request, so an unconditional call takes the whole app down when
 * self-hosting on API keys alone. Guarding the provider in the layout is not
 * enough; this runs first.
 *
 * It deliberately does not protect routes: the pages decide what to show when
 * nobody is signed in, and the API is the real boundary anyway — it verifies
 * the token itself rather than trusting that middleware ran.
 */
const configured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export default configured ? clerkMiddleware() : () => NextResponse.next();

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)"],
};
