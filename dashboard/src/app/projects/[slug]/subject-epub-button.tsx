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
  const [busy, setBusy] = useState<null | "bundle" | "epub">(null);
  const [error, setError] = useState<string | null>(null);

  async function buildAndOpen(kind: "bundle" | "epub") {
    setBusy(kind);
    setError(null);
    try {
      const r =
        kind === "bundle"
          ? await api.buildSubjectBundle(project, subject)
          : await api.buildSubjectEpub(project, subject);
      window.open(`${API_BASE}${r.url}`, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => buildAndOpen("bundle")}
          disabled={busy !== null}
          className="text-[11px] rounded border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
          title="Build a zip with .epub + .md + .csv"
        >
          {busy === "bundle" ? "building…" : "📦 .zip (epub+md+csv)"}
        </button>
        <button
          onClick={() => buildAndOpen("epub")}
          disabled={busy !== null}
          className="text-[11px] rounded border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
          title="Build EPUB only"
        >
          {busy === "epub" ? "…" : "📖"}
        </button>
      </div>
      {error && (
        <div className="text-[10px] text-red-600 dark:text-red-400">{error}</div>
      )}
    </div>
  );
}
