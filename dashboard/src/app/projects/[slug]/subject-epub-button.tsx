"use client";

import { useState } from "react";
import { api, API_BASE } from "@/lib/api";

export function SubjectEpubButton({
  project,
  subject,
}: {
  project: string;
  subject: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function buildAndOpen() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.buildSubjectEpub(project, subject);
      // Open the download in a new tab so the user can save it.
      window.open(`${API_BASE}${r.url}`, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-1">
      <button
        onClick={buildAndOpen}
        disabled={busy}
        className="text-[11px] rounded border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
        title="Build an Arabic EPUB book from this subject's clean records"
      >
        {busy ? "building…" : "📖 EPUB"}
      </button>
      {error && (
        <div className="text-[10px] text-red-600 dark:text-red-400">{error}</div>
      )}
    </div>
  );
}
