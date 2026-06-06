"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";

type Candidate = Awaited<ReturnType<typeof api.discoverSources>>["candidates"][number];

type Props = {
  project: string;
  subject: string;
  nameAr?: string;
  nameEn?: string;
  aliases?: string[];
};

const TONE_BY_CONFIDENCE: Record<Candidate["confidence"], string> = {
  high: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-200 dark:border-emerald-800",
  medium: "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-800",
  low: "bg-zinc-100 text-zinc-700 border-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700",
  reference: "bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-900/30 dark:text-sky-200 dark:border-sky-800",
};

export function ExpandSearchButton({ project, subject, nameAr, nameEn, aliases }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [adding, setAdding] = useState<Record<string, "idle" | "adding" | "added" | "error">>({});

  const searchName = nameAr || nameEn || subject;
  const searchAliases = [
    ...(aliases || []),
    ...(nameEn ? [nameEn] : []),
    subject,
  ].filter(Boolean);

  const run = useCallback(async () => {
    setOpen(true);
    if (candidates) return; // already loaded once
    setLoading(true);
    setError(null);
    try {
      const r = await api.discoverSources(searchName, searchAliases, "poet");
      setCandidates(r.candidates);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [candidates, searchName, searchAliases]);

  const addCandidate = useCallback(
    async (c: Candidate) => {
      if (!c.source_template) return;
      const key = c.url;
      setAdding((a) => ({ ...a, [key]: "adding" }));
      try {
        const sourceName = `${c.site}-${subject}`.toLowerCase().replace(/[^a-z0-9-]+/g, "-");
        const source = {
          ...c.source_template,
          name: sourceName,
          subject,
        };
        await api.addSource(project, source);
        setAdding((a) => ({ ...a, [key]: "added" }));
      } catch (e) {
        setAdding((a) => ({ ...a, [key]: "error" }));
        console.error("add source failed", e);
      }
    },
    [project, subject],
  );

  return (
    <>
      <button
        type="button"
        onClick={run}
        className="text-xs px-2 py-1 rounded border border-indigo-300 text-indigo-700 hover:bg-indigo-50 dark:border-indigo-800 dark:text-indigo-300 dark:hover:bg-indigo-900/30"
        title="Discover more sources for this subject"
      >
        🔍 Expand
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-zinc-900/60 flex items-start justify-center p-6 overflow-y-auto"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-white dark:bg-zinc-900 rounded-lg shadow-xl max-w-3xl w-full p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
            dir="auto"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold">Expand search — {searchName}</h3>
                <p className="text-xs text-zinc-500 mt-1">
                  Probing aldiwan / poetspedia / Telegram / X plus DuckDuckGo for additional sources.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 text-2xl leading-none"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {loading && (
              <div className="text-sm text-zinc-500 py-8 text-center">Searching…</div>
            )}

            {error && (
              <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 rounded px-3 py-2 border border-red-200 dark:border-red-800">
                {error}
              </div>
            )}

            {!loading && candidates && candidates.length === 0 && (
              <div className="text-sm text-zinc-500 py-8 text-center">
                No new candidates found. Try editing the manifest aliases and retrying.
              </div>
            )}

            {!loading && candidates && candidates.length > 0 && (
              <ul className="space-y-2 max-h-[60vh] overflow-y-auto">
                {candidates.map((c) => {
                  const key = c.url;
                  const state = adding[key] || "idle";
                  return (
                    <li
                      key={key}
                      className={`border rounded-md p-3 ${TONE_BY_CONFIDENCE[c.confidence]} space-y-1`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap text-sm">
                            <span className="font-semibold">{c.site}</span>
                            <span className="text-[10px] uppercase tracking-wider opacity-70">
                              {c.confidence}
                            </span>
                          </div>
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs font-mono break-all underline opacity-80 hover:opacity-100"
                          >
                            {c.url}
                          </a>
                          {c.notes && <div className="text-xs opacity-80 mt-1">{c.notes}</div>}
                          {c._evidence && c._evidence.length > 0 && (
                            <details className="text-xs mt-1 opacity-80">
                              <summary className="cursor-pointer">
                                {c._evidence.length} search hit{c._evidence.length === 1 ? "" : "s"}
                              </summary>
                              <ul className="mt-1 pl-4 space-y-0.5">
                                {c._evidence.map((e, i) => (
                                  <li key={i}>
                                    <a
                                      href={e.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="underline"
                                    >
                                      {e.title || e.url}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                        </div>
                        {c.source_template ? (
                          <button
                            type="button"
                            onClick={() => addCandidate(c)}
                            disabled={state !== "idle"}
                            className={`text-xs px-2.5 py-1 rounded font-medium whitespace-nowrap ${
                              state === "added"
                                ? "bg-emerald-600 text-white"
                                : state === "error"
                                  ? "bg-red-600 text-white"
                                  : state === "adding"
                                    ? "bg-zinc-400 text-white"
                                    : "bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                            }`}
                          >
                            {state === "added"
                              ? "✓ Added"
                              : state === "error"
                                ? "Failed"
                                : state === "adding"
                                  ? "Adding…"
                                  : "+ Add source"}
                          </button>
                        ) : (
                          <span className="text-[10px] uppercase opacity-60 whitespace-nowrap">
                            reference only
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </>
  );
}
