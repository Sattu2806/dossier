"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Connect({ message }: { message?: string }) {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(message ?? null);
  const [busy, setBusy] = useState(false);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const response = await fetch("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key.trim() }),
    });

    if (response.ok) {
      router.refresh();
      return;
    }
    setError(((await response.json()) as { error: string }).error);
    setBusy(false);
  }

  return (
    <div className="mx-auto max-w-md space-y-6 pt-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Connect to your API</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">
          Create a key on the machine running the API, then paste it here. It is kept in an httpOnly cookie,
          so it never becomes readable by scripts on this page.
        </p>
      </div>

      <pre className="overflow-x-auto rounded-lg border border-line bg-panel-2 px-4 py-3 font-mono text-[12.5px] text-muted">
        uv run dossier user you@example.com
      </pre>

      <form onSubmit={connect} className="space-y-3">
        <input
          value={key}
          onChange={(event) => setKey(event.target.value)}
          placeholder="dsr_…"
          className="w-full rounded-lg border border-line bg-panel px-4 py-3 font-mono text-[14px] outline-none transition-colors placeholder:text-muted/60 focus:border-accent/50"
        />
        <button
          type="submit"
          disabled={busy || !key.trim()}
          className="w-full rounded-lg bg-accent px-5 py-3 text-[15px] font-medium text-[#04211a] transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Checking…" : "Connect"}
        </button>
        {error && <p className="text-[14px] text-bad">{error}</p>}
      </form>
    </div>
  );
}
