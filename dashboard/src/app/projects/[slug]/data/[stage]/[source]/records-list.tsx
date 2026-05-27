"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type Rec = Record<string, unknown> & { id?: string };

const PAGE_SIZE = 25;

export function RecordsList({
  project,
  stage,
  source,
  initialPage,
  q,
}: {
  project: string;
  stage: string;
  source: string;
  initialPage: { records: Rec[]; total: number; offset: number };
  q?: string;
}) {
  const [page, setPage] = useState(initialPage);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const offset = page.offset;
  const records = page.records;

  function toggle(id: string | undefined) {
    if (!id) return;
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleAll() {
    if (selected.size === records.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(records.map((r) => r.id as string).filter(Boolean)));
    }
  }

  async function refresh() {
    const r = await api.listRecords(project, stage, source, {
      offset,
      limit: PAGE_SIZE,
      q,
    });
    setPage({ records: r.records as Rec[], total: r.total, offset: r.offset });
  }

  async function applyAction(action: string, extra?: Record<string, string>) {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const actions = Array.from(selected).map((id) => ({ id, action, ...extra }));
      await api.postCuration(project, actions);
      setToast(
        `${actions.length} record${actions.length === 1 ? "" : "s"} ` +
          `marked "${action}". Re-run cleaning for it to take effect.`,
      );
      setSelected(new Set());
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reclean() {
    setBusy(true);
    try {
      const j = await api.enqueueJob(project, "clean");
      setToast(`Clean job #${j.id} queued.`);
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const prev = Math.max(0, offset - PAGE_SIZE);
  const next = offset + PAGE_SIZE;
  const hasNext = page.total > next;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm">
        <label className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={selected.size > 0 && selected.size === records.length}
            onChange={toggleAll}
          />
          select all on page ({selected.size}/{records.length})
        </label>
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => applyAction("discard")}
              disabled={busy}
              className="rounded-md border border-red-300 dark:border-red-900 text-red-700 dark:text-red-300 px-2 py-1 text-xs hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-50"
            >
              Discard
            </button>
            <button
              onClick={() => applyAction("undo_discard")}
              disabled={busy}
              className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              Undo discard
            </button>
            <button
              onClick={() => {
                const cat = prompt("Set category to:");
                if (cat) applyAction("set_category", { category: cat });
              }}
              disabled={busy}
              className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              Set category…
            </button>
            <button
              onClick={() => {
                const sub = prompt("Move to subject slug:");
                if (sub) applyAction("set_subject", { subject: sub });
              }}
              disabled={busy}
              className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-1 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              Move to subject…
            </button>
            <button
              onClick={reclean}
              disabled={busy}
              className="rounded-md bg-emerald-600 text-white px-2 py-1 text-xs hover:opacity-90 disabled:opacity-50"
            >
              Re-run cleaning
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}
      {toast && (
        <div className="rounded-md border border-emerald-300 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/50 p-2 text-xs text-emerald-800 dark:text-emerald-200">
          {toast}
        </div>
      )}

      <ol className="space-y-3" start={offset + 1}>
        {records.map((r, i) => {
          const id = r.id as string | undefined;
          const checked = !!id && selected.has(id);
          return (
            <li
              key={id || `${offset + i}`}
              className={`rounded-lg border p-4 flex gap-3 ${
                checked
                  ? "border-emerald-400 bg-emerald-50/30 dark:bg-emerald-950/20"
                  : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(id)}
                className="mt-1 shrink-0"
                disabled={!id}
              />
              <div className="flex-1">
                <RecordCard r={r} />
              </div>
            </li>
          );
        })}
      </ol>

      <div className="flex items-center justify-between text-sm">
        {offset > 0 ? (
          <button
            onClick={async () => {
              const r = await api.listRecords(project, stage, source, {
                offset: prev,
                limit: PAGE_SIZE,
                q,
              });
              setPage({ records: r.records as Rec[], total: r.total, offset: r.offset });
            }}
            className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            ← Previous
          </button>
        ) : (
          <span />
        )}
        <span className="text-zinc-500">
          {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of{" "}
          {page.total.toLocaleString()}
        </span>
        {hasNext ? (
          <button
            onClick={async () => {
              const r = await api.listRecords(project, stage, source, {
                offset: next,
                limit: PAGE_SIZE,
                q,
              });
              setPage({ records: r.records as Rec[], total: r.total, offset: r.offset });
            }}
            className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            Next →
          </button>
        ) : (
          <span />
        )}
      </div>
    </div>
  );
}

function RecordCard({ r }: { r: Record<string, unknown> }) {
  const title = (r.title as string | null) || null;
  const text =
    (r.text as string | null) || (r.verses as string | null) || (r.body as string | null) || "";
  const poet = r.poet as string | undefined;
  const url = (r.source_url as string | undefined) || (r._source_url as string | undefined);
  const runId = (r.run_id as number | string | undefined) ?? (r._run_id as number | undefined);
  const meta = r.meta as Record<string, unknown> | undefined;
  const category = r.category as string | undefined;

  // Aldiwan structured metadata — pipe-joined strings → array of chips
  const metaChips: { label: string; value: string; tone: string }[] = [];
  if (meta) {
    const fromPipe = (s: unknown) =>
      typeof s === "string"
        ? s
            .split("|")
            .map((x) => x.trim())
            .filter((x) => x && !x.startsWith("المزيد") && x !== "متابعة")
        : [];
    for (const t of fromPipe(meta.topics)) {
      metaChips.push({ label: "topic", value: t, tone: "topic" });
    }
    for (const c of fromPipe(meta.categories)) {
      metaChips.push({ label: "category", value: c, tone: "category" });
    }
    for (const m of fromPipe(meta.meter)) {
      metaChips.push({ label: "meter", value: m, tone: "meter" });
    }
    for (const rh of fromPipe(meta.rhyme)) {
      metaChips.push({ label: "rhyme", value: rh, tone: "rhyme" });
    }
  }

  const toneClass: Record<string, string> = {
    topic: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    category: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
    meter: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
    rhyme: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  };

  return (
    <article className="space-y-2" dir="auto">
      <header className="flex items-baseline justify-between gap-3">
        <div className="space-y-0.5">
          {title && <h2 className="font-semibold">{title}</h2>}
          <div className="flex items-baseline gap-2 text-xs">
            {poet && (
              <span className="font-mono text-zinc-500">{poet}</span>
            )}
            {category && category !== "poetry" && (
              <span className="text-[10px] px-1.5 rounded bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                {category}
              </span>
            )}
          </div>
        </div>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 shrink-0"
          >
            source ↗
          </a>
        )}
      </header>

      {metaChips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {metaChips.map((c, i) => (
            <span
              key={`${c.tone}-${i}`}
              className={`text-[11px] px-1.5 py-0.5 rounded ${toneClass[c.tone] || ""}`}
              title={c.label}
            >
              {c.value}
            </span>
          ))}
        </div>
      )}

      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
        {text.length > 1200 ? text.slice(0, 1200) + "…" : text}
      </pre>
      <footer className="flex flex-wrap gap-3 text-xs text-zinc-500 pt-1 border-t border-zinc-100 dark:border-zinc-800">
        {r.lang ? <span>lang: {String(r.lang)}</span> : null}
        {r.word_count != null ? <span>{String(r.word_count)} words</span> : null}
        {r.line_count != null ? <span>{String(r.line_count)} lines</span> : null}
        {runId != null ? <span>run #{String(runId)}</span> : null}
        {meta?.published_at ? (
          <span>posted: {new Date(String(meta.published_at)).toLocaleDateString()}</span>
        ) : null}
        {meta?.views ? <span>{String(meta.views)} views</span> : null}
      </footer>
      <Provenance r={r} />
    </article>
  );
}

function Provenance({ r }: { r: Record<string, unknown> }) {
  const sources = (r.sources as string[] | undefined) || [];
  const urls = (r.source_urls as string[] | undefined) || [];
  if (sources.length <= 1) return null;
  return (
    <div className="pt-1 border-t border-zinc-100 dark:border-zinc-800 text-xs space-y-1">
      <div className="text-zinc-500">
        Also appears in {sources.length - 1} other source
        {sources.length - 1 === 1 ? "" : "s"}:
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1">
        {sources.map((s, i) => {
          const u = urls[i];
          return (
            <li key={`${s}-${i}`} className="font-mono text-[11px]">
              {u ? (
                <a
                  href={u}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 underline decoration-dotted"
                >
                  {s}
                </a>
              ) : (
                <span className="text-zinc-500">{s}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
