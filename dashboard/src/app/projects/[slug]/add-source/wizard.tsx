"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

type Mode = "by-url" | "by-name";

type Candidate = {
  site: string;
  confidence: string;
  url: string;
  source_template: Record<string, unknown>;
  notes: string;
};

type PreviewResult = {
  source: string;
  type: string;
  samples: Record<string, unknown>[];
  sample_count: number;
  errors: string[];
};

export function AddSourceWizard({ project }: { project: string }) {
  const [mode, setMode] = useState<Mode>("by-url");
  return (
    <div className="space-y-5">
      <div className="inline-flex rounded-md border border-zinc-300 dark:border-zinc-700 p-0.5 text-sm">
        {(["by-url", "by-name"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 rounded ${
              mode === m
                ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 font-medium"
                : "text-zinc-600 dark:text-zinc-400"
            }`}
          >
            {m === "by-url" ? "By URL" : "By poet / topic name"}
          </button>
        ))}
      </div>
      {mode === "by-url" ? (
        <ByUrlFlow project={project} />
      ) : (
        <ByNameFlow project={project} />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
//  By-URL flow
// ─────────────────────────────────────────────────────────────────────

function ByUrlFlow({ project }: { project: string }) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [subjectSlug, setSubjectSlug] = useState("");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function detect() {
    setBusy(true);
    setError(null);
    try {
      const det = await api.detectSourceType(url);
      const sourceName = (det.channel || det.handle || subjectSlug || "new-source") + "-" + det.type;
      setDraft({ ...det, name: sourceName });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runPreview() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await api.previewSource(project, draft, 5));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const src = { ...draft };
      if (subjectSlug) src.subject = subjectSlug;
      const subject = subjectSlug
        ? {
            slug: subjectSlug,
            type: "poet",
            name_ar: name || subjectSlug,
            sources: { [src.type as string]: src.name as string },
          }
        : null;
      await api.addSource(project, src, subject);
      router.push(`/projects/${project}/rules`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="block text-sm">
          <span className="text-zinc-500">Paste a URL</span>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://t.me/s/<channel>  or  https://www.aldiwan.net/cat-poet-<slug>"
            className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 font-mono text-sm"
          />
        </label>
        <button
          onClick={detect}
          disabled={busy || !url}
          className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "Detecting…" : "Detect type"}
        </button>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}

      {draft && (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3 text-sm">
          <div>
            <span className="text-zinc-500">Detected: </span>
            <code>{draft.type as string}</code>
            <span className="ml-2 text-xs text-zinc-500">
              confidence: {draft.confidence as string}
            </span>
            {draft.hint ? (
              <div className="text-xs text-zinc-500 mt-1">{draft.hint as string}</div>
            ) : null}
          </div>
          <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 p-2 rounded border border-zinc-200 dark:border-zinc-800 overflow-x-auto max-h-48">
            {JSON.stringify(draft, null, 2)}
          </pre>
          <SubjectFields
            name={name}
            slug={subjectSlug}
            onName={setName}
            onSlug={setSubjectSlug}
          />
          <div className="flex gap-2">
            <button
              onClick={runPreview}
              disabled={busy}
              className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              {busy ? "Running…" : "Run dry-run (5 records)"}
            </button>
            <button
              onClick={save}
              disabled={busy || !subjectSlug}
              className="rounded-md bg-emerald-600 text-white px-3 py-1.5 font-medium disabled:opacity-50"
            >
              Save source
            </button>
          </div>
        </div>
      )}

      {preview && <PreviewPanel preview={preview} project={project} draft={draft} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
//  By-name flow (discovery)
// ─────────────────────────────────────────────────────────────────────

function ByNameFlow({ project }: { project: string }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [subjectType, setSubjectType] = useState<"poet" | "topic" | "person" | "site">("poet");
  const [subjectSlug, setSubjectSlug] = useState("");
  const [candidates, setCandidates] = useState<
    Awaited<ReturnType<typeof api.discoverSources>>["candidates"] | null
  >(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function discover() {
    setBusy(true);
    setError(null);
    setCandidates(null);
    setPicked(new Set());
    try {
      const aliasList = aliases.split(/\s+|,/).map((s) => s.trim()).filter(Boolean);
      const res = await api.discoverSources(name, aliasList, subjectType);
      setCandidates(res.candidates);
      // pre-pick high + medium confidence (skip low + reference)
      const initialPicked = new Set<number>();
      res.candidates.forEach((c, i) => {
        if (c.confidence === "high" || c.confidence === "medium") initialPicked.add(i);
      });
      setPicked(initialPicked);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveAll() {
    if (!candidates || !subjectSlug) return;
    setBusy(true);
    setError(null);
    try {
      const aliasList = aliases.split(/\s+|,/).map((s) => s.trim()).filter(Boolean);
      const subjectManifest = {
        slug: subjectSlug,
        type: subjectType,
        name_ar: name,
        aliases: aliasList,
        sources: {} as Record<string, unknown>,
      };
      let i = 0;
      for (const idx of Array.from(picked).sort()) {
        const c = candidates[idx];
        if (!c.source_template) continue; // skip reference-only candidates
        const baseName = `${c.site.replace(/\./g, "-")}-${subjectSlug}`;
        const tmpl = { ...c.source_template, name: baseName, subject: subjectSlug };
        subjectManifest.sources[c.site] = tmpl.name as string;
        await api.addSource(project, tmpl, i === 0 ? subjectManifest : null);
        i++;
      }
      router.push(`/projects/${project}/rules`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function toggle(i: number) {
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="block text-sm">
          <span className="text-zinc-500">Subject type</span>
          <select
            value={subjectType}
            onChange={(e) =>
              setSubjectType(e.target.value as "poet" | "topic" | "person" | "site")
            }
            className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 text-sm"
          >
            <option value="poet">Poet</option>
            <option value="topic">Topic</option>
            <option value="person">Person</option>
            <option value="site">Site</option>
          </select>
        </label>
        <label className="block text-sm sm:col-span-1">
          <span className="text-zinc-500">Name (Arabic preferred)</span>
          <input
            dir="auto"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={
              subjectType === "topic" ? "زجل" : subjectType === "site" ? "qafiyah.com" : "حذيفة العرجي"
            }
            className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-sm sm:col-span-1">
          <span className="text-zinc-500">Aliases (optional)</span>
          <input
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            placeholder="alarje, el_arje, al_arje"
            className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 font-mono text-sm"
          />
        </label>
      </div>
      <button
        onClick={discover}
        disabled={busy || !name}
        className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
      >
        {busy ? "Searching the web…" : "Discover sources"}
      </button>
      <p className="text-xs text-zinc-500">
        Probes known poetry sites (aldiwan / poetspedia / telegram / X) AND runs a
        DuckDuckGo search (4 query variants) to surface sources we don&apos;t
        already know about. Topics use different queries from poets.
      </p>

      {error && <ErrorBox>{error}</ErrorBox>}

      {candidates && candidates.length === 0 && (
        <div className="text-sm text-zinc-500">
          No matches. Try adding aliases (latin slug, social handle).
        </div>
      )}

      {candidates && candidates.length > 0 && (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 space-y-2">
          <div className="text-sm font-medium">
            Found {candidates.length} candidate sources — check the ones to keep
          </div>
          <ul className="space-y-2">
            {candidates.map((c, i) => {
              const isReference = c.confidence === "reference";
              return (
                <li
                  key={`${c.site}-${i}`}
                  className="flex items-start gap-2 p-2 rounded border border-zinc-100 dark:border-zinc-800"
                >
                  <input
                    type="checkbox"
                    checked={picked.has(i)}
                    onChange={() => toggle(i)}
                    disabled={isReference}
                    className="mt-1"
                  />
                  <div className="flex-1 text-sm space-y-1">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="font-mono font-semibold">{c.site}</span>
                      <ConfidenceChip confidence={c.confidence} />
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 ml-auto"
                      >
                        open ↗
                      </a>
                    </div>
                    <div className="text-xs text-zinc-500">{c.notes}</div>
                    <code className="text-[11px] text-zinc-500 break-all">{c.url}</code>
                    {c._evidence && c._evidence.length > 0 && (
                      <details className="text-[11px] text-zinc-500">
                        <summary className="cursor-pointer hover:text-zinc-700 dark:hover:text-zinc-300">
                          {c._evidence.length} search hit{c._evidence.length === 1 ? "" : "s"}
                        </summary>
                        <ul className="mt-1 ml-4 space-y-0.5 list-disc">
                          {c._evidence.slice(0, 5).map((e, j) => (
                            <li key={j}>
                              <span dir="auto" className="font-medium text-zinc-700 dark:text-zinc-300">
                                {e.title.slice(0, 100)}
                              </span>{" "}
                              <span className="text-zinc-400">— query: {e.query}</span>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="border-t border-zinc-100 dark:border-zinc-800 pt-3 mt-3 space-y-3">
            <SubjectFields
              name={name}
              slug={subjectSlug}
              onName={setName}
              onSlug={setSubjectSlug}
            />
            <button
              onClick={saveAll}
              disabled={busy || !subjectSlug || picked.size === 0}
              className="rounded-md bg-emerald-600 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              Save subject + {picked.size} source{picked.size === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
//  Shared bits
// ─────────────────────────────────────────────────────────────────────

function SubjectFields({
  name,
  slug,
  onName,
  onSlug,
}: {
  name: string;
  slug: string;
  onName: (v: string) => void;
  onSlug: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
      <label className="block">
        <span className="text-zinc-500">Subject slug</span>
        <input
          value={slug}
          onChange={(e) => onSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))}
          placeholder="hudhayfah-alarje"
          className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
        />
      </label>
      <label className="block">
        <span className="text-zinc-500">Display name</span>
        <input
          dir="auto"
          value={name}
          onChange={(e) => onName(e.target.value)}
          placeholder="حذيفة العرجي"
          className="block w-full mt-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1"
        />
      </label>
    </div>
  );
}

function PreviewPanel({
  preview,
  project,
  draft,
}: {
  preview: PreviewResult;
  project: string;
  draft: Record<string, unknown> | null;
}) {
  const [suggestion, setSuggestion] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function autoSuggest() {
    setBusy(true);
    try {
      setSuggestion(await api.suggestCleanup(preview.samples));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3 text-sm">
      <div className="flex items-baseline justify-between">
        <div className="font-medium">
          Dry-run · {preview.sample_count} records
        </div>
        <button
          onClick={autoSuggest}
          disabled={busy || preview.samples.length === 0}
          className="text-xs rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          {busy ? "Analyzing…" : "Suggest cleanup rules"}
        </button>
      </div>
      {preview.errors.length > 0 && (
        <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          {preview.errors.join("\n")}
        </div>
      )}
      <ol className="space-y-2 max-h-96 overflow-y-auto">
        {preview.samples.map((r, i) => {
          const text =
            (r.text as string) || (r.verses as string) || (r.body as string) || "";
          const title = (r.title as string) || null;
          return (
            <li
              key={i}
              className="rounded border border-zinc-100 dark:border-zinc-800 p-2 space-y-1"
              dir="auto"
            >
              {title && <div className="font-semibold text-xs">{title}</div>}
              <pre className="whitespace-pre-wrap text-xs font-sans">
                {text.slice(0, 400)}
                {text.length > 400 ? "…" : ""}
              </pre>
            </li>
          );
        })}
      </ol>
      {suggestion && (
        <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 p-2 rounded border border-zinc-200 dark:border-zinc-800 overflow-x-auto">
          {JSON.stringify(suggestion, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
      {children}
    </div>
  );
}

function ConfidenceChip({ confidence }: { confidence: string }) {
  const styles: Record<string, string> = {
    high: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    low: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    reference: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200",
  };
  return (
    <span className={`text-[10px] px-1.5 rounded ${styles[confidence] || styles.low}`}>
      {confidence}
    </span>
  );
}
