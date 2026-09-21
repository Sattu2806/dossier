import { ClerkProvider, Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import Link from "next/link";

import Ambient from "@/components/Ambient";
import CommandPalette from "@/components/CommandPalette";
import { ToastProvider } from "@/components/ui/Toast";
import { backendFetch, clerkIsConfigured, isAuthenticated, type Run } from "@/lib/backend";

import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
// One editorial serif for display type. It does what a second weight of the
// same grotesk cannot: it makes a report look written rather than generated.
const display = Instrument_Serif({ variable: "--font-display", weight: "400", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dossier — researched reports, with citations",
  description:
    "Plans sub-questions, searches the web and your documents in parallel, drafts a report and fact-checks every claim against its sources.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const withClerk = clerkIsConfigured();

  // The palette searches your own reports, so it needs them — fetched once
  // here for the whole app rather than by each page.
  let recent: Run[] = [];
  if (await isAuthenticated()) {
    try {
      const response = await backendFetch("/api/runs?limit=20");
      if (response.ok) recent = ((await response.json()) as { runs: Run[] }).runs;
    } catch {
      recent = [];
    }
  }

  const shell = (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} ${display.variable} min-h-screen antialiased`}>
        <ToastProvider>
          <Ambient />

          <header className="sticky top-0 z-30 border-b border-line/70 bg-bg/70 backdrop-blur-xl">
            <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
              <Link href="/" className="group flex items-center gap-2.5">
                <span className="relative grid h-7 w-7 place-items-center overflow-hidden rounded-lg border border-line bg-panel-2 font-display text-[15px] text-accent">
                  D
                  <span className="absolute inset-0 bg-gradient-to-br from-accent/20 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
                </span>
                <span className="text-[15px] font-medium tracking-tight">Dossier</span>
              </Link>

              <nav className="flex items-center gap-1 text-[13.5px]">
                <Link
                  href="/"
                  className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text"
                >
                  Research
                </Link>
                <Link
                  href="/learn"
                  className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text"
                >
                  Learn a book
                </Link>
                <Link
                  href="/history"
                  className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text"
                >
                  History
                </Link>

                <kbd className="ml-1 hidden items-center rounded-md border border-line bg-panel px-1.5 py-1 font-mono text-[10px] text-muted sm:flex">
                  ⌘K
                </kbd>

                {withClerk && (
                  <div className="ml-2 flex items-center gap-2 border-l border-line pl-3">
                    <Show when="signed-out">
                      <SignInButton mode="modal">
                        <button className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-panel-2 hover:text-text">
                          Sign in
                        </button>
                      </SignInButton>
                      <SignUpButton mode="modal">
                        <button className="rounded-lg bg-accent px-3 py-1.5 font-medium text-[#04211a] transition-opacity hover:opacity-90">
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

          <main className="relative z-10 mx-auto max-w-5xl px-6 py-12">{children}</main>

          <footer className="relative z-10 mx-auto max-w-5xl px-6 pb-10 pt-4">
            <div className="hairline mb-4" />
            <p className="font-mono text-[11px] text-muted">
              Every claim cited · fact-checked against its sources · built with LangGraph
            </p>
          </footer>

          <CommandPalette recent={recent} />
        </ToastProvider>
      </body>
    </html>
  );

  // Without Clerk keys the app runs on API keys alone, which is what
  // self-hosting and local development use. Rendering the provider anyway
  // would take the whole app down for want of a publishable key.
  return withClerk ? <ClerkProvider>{shell}</ClerkProvider> : shell;
}
