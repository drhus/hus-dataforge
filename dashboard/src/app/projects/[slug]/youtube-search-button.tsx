"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";

type Result = Awaited<ReturnType<typeof api.youtubeSearch>>["results"][number];

function fmtDuration(s: number | null): string {
  if (!s) return "?";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60).toString().padStart(2, "0");
  return `${m}:${sec}`;
}

function fmtViews(n: number | null): string {
  if (n == null) return "";
  if (n > 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n > 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

export function YouTubeSearchButton({ project }: { project: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(25);
  const [minDuration, setMinDuration] = useState(60);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Result[] | null>(null);
  const [adding, setAdding] = useState<"idle" | "adding" | "added" | "error">("idle");
  const [addedSource, setAddedSource] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    setResults(null);
    setSelected(new Set());
    setAdding("idle");
    setAddError(null);
    setAddedSource(null);
    try {
      const r = await api.youtubeSearch(q, maxResults);
      setResults(r.results);
      // Pre-select results that pass the min-duration filter (most useful default)
      setSelected(
        new Set(r.results.filter((v) => (v.duration || 0) >= minDuration).map((v) => v.video_id)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [query, maxResults, minDuration]);

  const toggleSelected = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    if (!results) return;
    setSelected(new Set(results.map((v) => v.video_id)));
  }, [results]);

  const selectNone = useCallback(() => setSelected(new Set()), []);

  const selectFilter = useCallback(() => {
    if (!results) return;
    setSelected(
      new Set(results.filter((v) => (v.duration || 0) >= minDuration).map((v) => v.video_id)),
    );
  }, [results, minDuration]);

  const addAsSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setAdding("adding");
    setAddError(null);
    const sourceName =
      "yt-search-" +
      q.toLowerCase().replace(/[^a-z0-9؀-ۿ]+/g, "-").replace(/-+/g, "-").slice(0, 50) +
      "-" + Date.now().toString(36).slice(-4);
    try {
      await api.addSource(project, {
        name: sourceName,
        type: "youtube_transcripts",
        search_query: q,
        rate_limit_sec: 4.0,
        max_records: maxResults,
        min_duration_sec: minDuration,
        max_duration_sec: 14400,
      });
      setAdding("added");
      setAddedSource(sourceName);
    } catch (e) {
      setAdding("error");
      setAddError(e instanceof Error ? e.message : String(e));
    }
  }, [project, query, maxResults, minDuration]);

  const addSelected = useCallback(async () => {
    if (selected.size === 0) return;
    const q = query.trim() || "manual";
    setAdding("adding");
    setAddError(null);
    const sourceName =
      "yt-pick-" +
      q.toLowerCase().replace(/[^a-z0-9؀-ۿ]+/g, "-").replace(/-+/g, "-").slice(0, 40) +
      "-" + Date.now().toString(36).slice(-4);
    try {
      await api.addSource(project, {
        name: sourceName,
        type: "youtube_transcripts",
        video_ids: Array.from(selected),
        rate_limit_sec: 4.0,
      });
      setAdding("added");
      setAddedSource(sourceName);
    } catch (e) {
      setAdding("error");
      setAddError(e instanceof Error ? e.message : String(e));
    }
  }, [project, query, selected]);

  const totalDuration = results?.reduce((acc, r) => acc + (r.duration || 0), 0) || 0;
  const withinFilter = results?.filter((r) => (r.duration || 0) >= minDuration).length || 0;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-rose-300 text-rose-700 px-3 py-2 text-sm font-medium hover:bg-rose-50 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-900/30"
        title="Search YouTube and add results as a transcript source"
      >
        🎬 Search YouTube
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-zinc-900/60 flex items-start justify-center p-6 overflow-y-auto"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-white dark:bg-zinc-900 rounded-lg shadow-xl max-w-4xl w-full p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
            dir="auto"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold">Search YouTube + add as transcript source</h3>
                <p className="text-xs text-zinc-500 mt-1">
                  Saves the query as a recurring source. Re-runs the search every scrape so new uploads land automatically.
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

            <div className="space-y-3">
              <div className="flex gap-2 items-end">
                <div className="flex-1">
                  <label className="block text-xs uppercase tracking-wider text-zinc-500 mb-1">
                    Search query
                  </label>
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runSearch()}
                    placeholder="e.g. تحدي زجل لبناني سميح خليل"
                    className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-500"
                  />
                </div>
                <div className="w-24">
                  <label className="block text-xs uppercase tracking-wider text-zinc-500 mb-1">
                    Top N
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={maxResults}
                    onChange={(e) => setMaxResults(Math.max(1, Math.min(100, parseInt(e.target.value) || 25)))}
                    className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-sm"
                  />
                </div>
                <div className="w-32">
                  <label className="block text-xs uppercase tracking-wider text-zinc-500 mb-1">
                    Min sec
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={minDuration}
                    onChange={(e) => setMinDuration(Math.max(0, parseInt(e.target.value) || 0))}
                    className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-sm"
                  />
                </div>
                <button
                  type="button"
                  onClick={runSearch}
                  disabled={loading || !query.trim()}
                  className="rounded-md bg-zinc-900 text-white px-4 py-2 text-sm font-medium hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                >
                  {loading ? "Searching…" : "Search"}
                </button>
              </div>
            </div>

            {error && (
              <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 rounded px-3 py-2 border border-red-200 dark:border-red-800 break-words">
                {error}
              </div>
            )}

            {results && (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-sm flex-wrap gap-2">
                  <div className="text-zinc-600 dark:text-zinc-400 flex flex-wrap gap-3 items-center">
                    <span>
                      {results.length} results · {selected.size} selected · total{" "}
                      {Math.round(totalDuration / 60)} min · {withinFilter} pass min-duration
                    </span>
                    <span className="flex gap-1">
                      <button
                        type="button"
                        onClick={selectAll}
                        className="text-xs px-2 py-0.5 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      >
                        all
                      </button>
                      <button
                        type="button"
                        onClick={selectFilter}
                        className="text-xs px-2 py-0.5 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      >
                        pass filter
                      </button>
                      <button
                        type="button"
                        onClick={selectNone}
                        className="text-xs px-2 py-0.5 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      >
                        none
                      </button>
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={addSelected}
                      disabled={adding === "adding" || adding === "added" || selected.size === 0}
                      className={`text-sm px-3 py-2 rounded font-medium ${
                        adding === "added"
                          ? "bg-emerald-600 text-white"
                          : adding === "error"
                            ? "bg-red-600 text-white hover:bg-red-700"
                            : "bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300 disabled:opacity-50"
                      }`}
                      title="Save just the videos you ticked as a fixed-list transcript source (one-shot, will not re-fetch)"
                    >
                      {adding === "added"
                        ? "✓ Added"
                        : adding === "adding"
                          ? "Adding…"
                          : selected.size > 0
                            ? `+ Add ${selected.size} selected`
                            : "+ Add selected"}
                    </button>
                    <button
                      type="button"
                      onClick={addAsSearch}
                      disabled={adding === "adding" || adding === "added"}
                      className="text-sm px-3 py-2 rounded font-medium bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
                      title="Save the search query — every future scrape re-runs the search and ingests fresh top-N results"
                    >
                      + Add all as recurring search
                    </button>
                  </div>
                </div>
                {addError && (
                  <div className="text-xs text-red-700 dark:text-red-300 break-words">
                    {addError}
                  </div>
                )}
                {addedSource && adding === "added" && (
                  <div className="text-xs text-emerald-700 dark:text-emerald-300">
                    Source: <span className="font-mono">{addedSource}</span> — start a scrape job to transcribe.
                  </div>
                )}
                <ul className="grid gap-2 sm:grid-cols-2">
                  {results.map((r) => {
                    const tooShort = (r.duration || 0) < minDuration;
                    const isSelected = selected.has(r.video_id);
                    return (
                      <li
                        key={r.video_id}
                        className={`flex gap-2 rounded border p-2 transition-colors ${
                          isSelected
                            ? "border-rose-400 bg-rose-50 dark:border-rose-700 dark:bg-rose-900/20"
                            : tooShort
                              ? "border-zinc-200 opacity-60 dark:border-zinc-800"
                              : "border-zinc-200 dark:border-zinc-800"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelected(r.video_id)}
                          className="mt-1 shrink-0 accent-rose-600"
                          aria-label={`Select ${r.title}`}
                        />
                        {r.thumbnail && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={r.thumbnail}
                            alt=""
                            width={120}
                            height={68}
                            className="rounded shrink-0 object-cover w-[120px] h-[68px] cursor-pointer"
                            onClick={() => toggleSelected(r.video_id)}
                          />
                        )}
                        <div className="min-w-0 flex-1 text-xs">
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium line-clamp-2 hover:underline"
                            title={r.title}
                          >
                            {r.title}
                          </a>
                          <div className="text-zinc-500 mt-1 flex gap-2 flex-wrap">
                            <span>{fmtDuration(r.duration)}</span>
                            {r.channel && <span>· {r.channel}</span>}
                            {r.view_count != null && <span>· {fmtViews(r.view_count)} views</span>}
                            {tooShort && <span className="text-amber-600">· too short</span>}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
