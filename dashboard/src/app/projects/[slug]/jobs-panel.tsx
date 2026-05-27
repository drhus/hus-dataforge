"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Job } from "@/lib/api";

const STATUS_STYLE: Record<Job["status"], string> = {
  queued: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  running: "bg-amber-200 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  succeeded: "bg-emerald-200 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
  failed: "bg-red-200 text-red-900 dark:bg-red-900/40 dark:text-red-200",
};

export function JobsPanel({ slug }: { slug: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setJobs(await api.listJobs(slug));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [slug]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  const [force, setForce] = useState(false);

  async function enqueue(kind: Job["kind"]) {
    setBusy(true);
    try {
      await api.enqueueJob(slug, kind, { force: kind === "scrape" ? force : false });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runPipeline() {
    setBusy(true);
    try {
      await api.enqueueJob(slug, "scrape", { force });
      await api.enqueueJob(slug, "clean");
      await api.enqueueJob(slug, "export");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Pipeline
        </h2>
        <div className="flex gap-2 items-center flex-wrap">
          {(["scrape", "clean", "export"] as const).map((k, i) => (
            <div key={k} className="flex items-center gap-2">
              {i > 0 && <span className="text-zinc-400 text-sm">→</span>}
              <button
                onClick={() => enqueue(k)}
                disabled={busy}
                className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
              >
                Run {k}
              </button>
            </div>
          ))}
          <span className="text-zinc-300 dark:text-zinc-700 mx-2">|</span>
          <button
            onClick={runPipeline}
            disabled={busy}
            className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
            title="Enqueue scrape → clean → export back-to-back (worker runs them in order)"
          >
            Run full pipeline
          </button>
        </div>
      </div>

      <label className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
        <input
          type="checkbox"
          checked={force}
          onChange={(e) => setForce(e.target.checked)}
        />
        <span>
          <strong>Force full re-scan</strong> for scrape (default is incremental —
          resume from last checkpoint, only fetch new content)
        </span>
      </label>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-6 text-center text-sm text-zinc-500">
          No jobs yet.
        </div>
      ) : (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 dark:bg-zinc-900/80 text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">ID</th>
                <th className="text-left px-3 py-2 font-medium">Kind</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Progress</th>
                <th className="text-left px-3 py-2 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="px-3 py-2 font-mono text-xs">{j.id}</td>
                  <td className="px-3 py-2">{j.kind}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[j.status]}`}
                    >
                      {j.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <JobProgress message={j.message} />
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-500">
                    {new Date(j.updated_at).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type ProgressBlob = {
  source?: string | null;
  pages?: number;
  records?: number;
  last_url?: string | null;
};

function JobProgress({ message }: { message: string | null }) {
  if (!message) return <span className="text-zinc-400">—</span>;
  let blob: ProgressBlob | null = null;
  try {
    blob = JSON.parse(message);
  } catch {
    return <span className="text-zinc-500">{message}</span>;
  }
  if (!blob) return <span className="text-zinc-400">—</span>;
  return (
    <div className="space-y-0.5">
      <div className="font-mono">
        {blob.records ?? 0} records · {blob.pages ?? 0} pages
      </div>
      {blob.last_url && (
        <div className="text-zinc-500 truncate max-w-[16rem]" title={blob.last_url}>
          {blob.last_url}
        </div>
      )}
    </div>
  );
}
