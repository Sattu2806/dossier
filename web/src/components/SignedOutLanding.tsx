import { SignInButton, SignUpButton } from "@clerk/nextjs";

/** What a visitor sees before signing in. Each account gets its own history
 *  and its own daily budget, so nobody shares a key with a stranger. */
export default function SignedOutLanding() {
  return (
    <div className="mx-auto max-w-lg space-y-7 pt-10 text-center">
      <div>
        <h1 className="text-[30px] font-semibold tracking-tight">Research anything, with citations</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">
          Sub-questions are planned, searched in parallel across the web and your own documents, drafted,
          then fact-checked against the sources before you see them.
        </p>
      </div>

      <div className="flex justify-center gap-3">
        <SignUpButton mode="modal">
          <button className="rounded-lg bg-accent px-6 py-3 text-[15px] font-medium text-[#04211a] transition-opacity hover:opacity-90">
            Create an account
          </button>
        </SignUpButton>
        <SignInButton mode="modal">
          <button className="rounded-lg border border-line bg-panel px-6 py-3 text-[15px] transition-colors hover:border-accent/40">
            Sign in
          </button>
        </SignInButton>
      </div>

      <p className="text-[13px] text-muted">
        Free accounts get a daily research allowance. Your reports are private to you.
      </p>
    </div>
  );
}
