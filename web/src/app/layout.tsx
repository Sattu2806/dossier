import { ClerkProvider, Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import { clerkIsConfigured } from "@/lib/backend";

import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dossier",
  description: "Researched reports with citations, fact-checked against their sources.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const withClerk = clerkIsConfigured();

  const shell = (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} min-h-screen antialiased`}>
        <header className="sticky top-0 z-20 border-b border-line bg-bg/80 backdrop-blur">
          <div className="mx-auto flex max-w-4xl items-center justify-between px-5 py-3.5">
            <Link href="/" className="group flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-md border border-line bg-panel-2 font-mono text-[13px] text-accent">
                D
              </span>
              <span className="text-[15px] font-semibold tracking-tight">Dossier</span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              <Link
                href="/"
                className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text"
              >
                Research
              </Link>
              <Link
                href="/history"
                className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text"
              >
                History
              </Link>
              {withClerk && (
                <div className="ml-2 flex items-center gap-2 border-l border-line pl-3">
                  <Show when="signed-out">
                    <SignInButton mode="modal">
                      <button className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text">
                        Sign in
                      </button>
                    </SignInButton>
                    <SignUpButton mode="modal">
                      <button className="rounded-md bg-accent px-3 py-1.5 font-medium text-[#04211a] transition-opacity hover:opacity-90">
                        Sign up
                      </button>
                    </SignUpButton>
                  </Show>
                  <Show when="signed-in">
                    <UserButton />
                  </Show>
                </div>
              )}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-5 py-10">{children}</main>
      </body>
    </html>
  );

  // Without Clerk keys the app still runs on API keys alone, which is what
  // self-hosting and local development use. Rendering the provider anyway
  // would crash the whole app for want of a publishable key.
  return withClerk ? <ClerkProvider>{shell}</ClerkProvider> : shell;
}
