import Connect from "@/components/Connect";
import HistoryList from "@/components/HistoryList";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated, type Run } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function History() {
  if (!(await isAuthenticated())) return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;

  let runs: Run[] = [];
  try {
    const response = await backendFetch("/api/runs");
    if (response.ok) runs = ((await response.json()) as { runs: Run[] }).runs;
  } catch {
    return <p className="text-warn">The research API is not responding.</p>;
  }

  return <HistoryList runs={runs} />;
}
