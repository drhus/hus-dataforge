"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Sched = {
  id: string;
  kind: string;
  cron: string;
  enabled: boolean;
  last_run_at?: string;
  next_run_at?: string;
  last_status?: string;
};

export function SchedulesEditor({ project }: { project: string }) {
  const [items, setItems] = useState<Sched[]>([]);
  const [draft, setDraft] = useState<Sched>({
    id: "",
    kind: "scrape",
    cron: "0 4 * * *",
    enabled: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const r = await api.listSchedules(project);
      setItems(r.schedules);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.upsertSchedule(project, draft);
      setDraft({ id: "", kind: "scrape", cron: "0 4 * * *", enabled: true });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm(`Delete schedule ${id}?`)) return;
    try {
      await api.deleteSchedule(project, id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3">
        <div className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
          New schedule
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 text-sm">
          <input
            value={draft.id}
            onChange={(e) =>
              setDraft({
                ...draft,
                id: e.target.value.toLowerCase().replace(/\s+/g, "-"),
              })
            }
            placeholder="id (e.g. daily-scrape)"
            className="rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono col-span-2"
          />
          <select
            value={draft.kind}
            onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1"
          >
            <option value="scrape">scrape</option>
            <option value="clean">clean</option>
            <option value="export">export</option>
          </select>
          <input
            value={draft.cron}
            onChange={(e) => setDraft({ ...draft, cron: e.target.value })}
            placeholder="cron"
            className="rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
          />
          <button
            onClick={save}
            disabled={busy || !draft.id || !draft.cron}
            className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1 disabled:opacity-50"
          >
            {busy ? "…" : "Add / update"}
          </button>
        </div>
        <div className="text-xs text-zinc-500 grid grid-cols-2 gap-2">
          <span>
            <code>0 4 * * *</code> daily 04:00 UTC
          </span>
          <span>
            <code>0 */6 * * *</code> every 6 hours
          </span>
          <span>
            <code>0 0 * * 0</code> weekly Sunday midnight
          </span>
          <span>
            <code>*/15 * * * *</code> every 15 minutes
          </span>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-6 text-center text-sm text-zinc-500">
          No schedules yet.
        </div>
      ) : (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 dark:bg-zinc-900/80 text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">ID</th>
                <th className="text-left px-3 py-2 font-medium">Kind</th>
                <th className="text-left px-3 py-2 font-medium">Cron</th>
                <th className="text-left px-3 py-2 font-medium">Next run</th>
                <th className="text-left px-3 py-2 font-medium">Last status</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {items.map((s) => (
                <tr key={s.id}>
                  <td className="px-3 py-2 font-mono text-xs">{s.id}</td>
                  <td className="px-3 py-2">{s.kind}</td>
                  <td className="px-3 py-2 font-mono text-xs">{s.cron}</td>
                  <td className="px-3 py-2 text-xs text-zinc-500">
                    {s.next_run_at
                      ? new Date(s.next_run_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">{s.last_status ?? "—"}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => remove(s.id)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
