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

type Preset = {
  name: string;
  id: string;
  kind: string;
  cron: string;
  enabled: boolean;
  description: string;
};

type PipelineState = Awaited<ReturnType<typeof api.getPipeline>>;

export function SchedulesEditor({ project }: { project: string }) {
  const [items, setItems] = useState<Sched[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
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
      const [r, ps, p] = await Promise.all([
        api.listSchedules(project),
        api.listSchedulePresets(),
        api.getPipeline(project),
      ]);
      setItems(r.schedules);
      setPresets(ps.presets);
      setPipeline(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function applyPreset(name: string) {
    setBusy(true);
    setError(null);
    try {
      await api.applySchedulePreset(project, name);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function togglePipeline() {
    if (!pipeline) return;
    const next = pipeline.auto_pipeline === false ? true : false;
    setBusy(true);
    try {
      await api.putPipeline(project, next);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

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

  const chainOn = pipeline?.auto_pipeline !== false;
  const lastRun = pipeline?.last_run ?? {
    scrape: null,
    clean: null,
    export: null,
  };

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <div className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
              Auto-pipeline
            </div>
            <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-1">
              When ON, a successful scrape auto-runs clean; clean auto-runs
              export. De-duped — if a stage is already queued/running, the chain
              skips. Toggle OFF to control each stage manually.
            </p>
          </div>
          <button
            onClick={togglePipeline}
            disabled={busy || !pipeline}
            className={
              "shrink-0 rounded-full px-3 py-1 text-xs font-medium transition " +
              (chainOn
                ? "bg-emerald-600 text-white hover:bg-emerald-700"
                : "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 hover:bg-zinc-300 dark:hover:bg-zinc-700")
            }
          >
            {chainOn ? "ON" : "OFF"}
          </button>
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          {(["scrape", "clean", "export"] as const).map((stage) => {
            const r = lastRun[stage];
            const cls =
              r?.status === "succeeded"
                ? "border-emerald-300 dark:border-emerald-900 bg-emerald-50/40 dark:bg-emerald-950/30"
                : r?.status === "failed"
                  ? "border-red-300 dark:border-red-900 bg-red-50/40 dark:bg-red-950/30"
                  : r?.status === "running" || r?.status === "queued"
                    ? "border-amber-300 dark:border-amber-900 bg-amber-50/40 dark:bg-amber-950/30"
                    : "border-zinc-200 dark:border-zinc-800";
            return (
              <div
                key={stage}
                className={`rounded-md border ${cls} p-2`}
                title={r ? `job #${r.id} (${r.status})` : "never run"}
              >
                <div className="text-zinc-500 uppercase tracking-wider text-[10px]">
                  {stage}
                </div>
                <div className="text-zinc-700 dark:text-zinc-300 text-xs">
                  {r ? (
                    <>
                      <div>{r.status}</div>
                      <div className="text-zinc-500">
                        {new Date(r.updated_at).toLocaleString()}
                      </div>
                      {r.chained && (
                        <div className="text-emerald-700 dark:text-emerald-400 text-[10px]">
                          ↳ chained
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-zinc-500">never</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {presets.length > 0 && items.length === 0 && (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-2">
          <div className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
            Quick presets
          </div>
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <button
                key={p.name}
                onClick={() => applyPreset(p.name)}
                disabled={busy}
                className="text-xs rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
                title={p.description}
              >
                + {p.description}
              </button>
            ))}
          </div>
        </div>
      )}

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
