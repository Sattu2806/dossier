import Connect from "@/components/Connect";
import Research from "@/components/Research";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated, type Me } from "@/lib/backend";

export default async function Home() {
  // Signed out: invite them to make an account when Clerk is set up, or ask
  // for an API key when it is not (self-hosted and local development).
  if (!(await isAuthenticated())) {
    return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;
  }

  let me: Me | null = null;
  let unreachable = false;
  try {
    const response = await backendFetch("/api/me");
    if (response.ok) me = (await response.json()) as Me;
    else if (!clerkIsConfigured()) return <Connect message="That key is no longer accepted. Paste a current one." />;
  } catch {
    unreachable = true;
  }

  return (
    <>
      {unreachable && (
        <div className="mb-6 rounded-lg border border-warn/40 bg-warn/10 px-4 py-3 text-[14px] text-warn">
          The research API is not responding. Start it with <code className="font-mono">uv run dossier serve</code>.
        </div>
      )}
      <Research initialMe={me} />
    </>
  );
}
