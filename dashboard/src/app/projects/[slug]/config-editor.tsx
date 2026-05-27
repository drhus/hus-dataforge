"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export function ConfigEditor({
  slug,
  initialConfig,
}: {
  slug: string;
  initialConfig: Record<string, unknown>;
}) {
  const [text, setText] = useState(JSON.stringify(initialConfig, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);

  function tryParse(s: string): unknown | null {
    try {
      const parsed = JSON.parse(s);
      setParseError(null);
      return parsed;
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }

  async function save() {
    const parsed = tryParse(text);
    if (!parsed || typeof parsed !== "object") return;
    setBusy(true);
    setSaveError(null);
    try {
      await api.updateProject(slug, parsed as Record<string, unknown>);
      setSavedAt(new Date());
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function revert() {
    setText(JSON.stringify(initialConfig, null, 2));
    setParseError(null);
    setSaveError(null);
  }

  function format() {
    const parsed = tryParse(text);
    if (parsed) setText(JSON.stringify(parsed, null, 2));
  }

  const dirty = text !== JSON.stringify(initialConfig, null, 2);

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Config
        </h2>
        <div className="flex gap-2 items-center text-xs">
          {savedAt && !dirty && (
            <span className="text-emerald-600">
              ✓ saved {savedAt.toLocaleTimeString()}
            </span>
          )}
          {dirty && <span className="text-amber-600">unsaved changes</span>}
          <button
            type="button"
            onClick={format}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Format
          </button>
          <button
            type="button"
            onClick={revert}
            disabled={!dirty}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
          >
            Revert
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy || !dirty || parseError !== null}
            className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-0.5 font-medium disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save config"}
          </button>
        </div>
      </div>

      {parseError && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          Invalid JSON: {parseError}
        </div>
      )}
      {saveError && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          Save failed: {saveError}
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          tryParse(e.target.value);
        }}
        spellCheck={false}
        rows={20}
        className={`block w-full rounded-lg border bg-white dark:bg-zinc-900 p-4 text-xs font-mono leading-relaxed resize-y ${
          parseError
            ? "border-red-300 dark:border-red-900"
            : "border-zinc-200 dark:border-zinc-800"
        }`}
      />
      <p className="text-xs text-zinc-500">
        Edits go to <code>projects/{slug}/config.yaml</code> via{" "}
        <code>PUT /projects/{slug}</code>. Saving replaces the entire config —
        keep all the existing keys you want to retain. For surgical edits use{" "}
        <a className="underline" href={`/projects/${slug}/rules`}>
          Rules
        </a>{" "}
        or{" "}
        <a className="underline" href={`/projects/${slug}/schedules`}>
          Schedules
        </a>{" "}
        pages — they only touch their slice.
      </p>
    </section>
  );
}
