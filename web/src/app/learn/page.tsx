import Connect from "@/components/Connect";
import Library, { type Document, type GuideSummary } from "@/components/Library";
import SignedOutLanding from "@/components/SignedOutLanding";
import { backendFetch, clerkIsConfigured, isAuthenticated } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function Learn() {
  if (!(await isAuthenticated())) return clerkIsConfigured() ? <SignedOutLanding /> : <Connect />;

  let documents: Document[] = [];
  let guides: GuideSummary[] = [];
  try {
    const [documentsResponse, guidesResponse] = await Promise.all([
      backendFetch("/api/documents"),
      backendFetch("/api/guides"),
    ]);
    if (documentsResponse.ok) documents = (await documentsResponse.json()).documents;
    if (guidesResponse.ok) guides = (await guidesResponse.json()).guides;
  } catch {
    return <p className="text-warn">The research API is not responding.</p>;
  }

  return <Library documents={documents} guides={guides} />;
}
