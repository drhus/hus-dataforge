"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Rule = { text_contains_any: string[]; set_category: string };

export function RulesEditor({
  project,
  source,
  sourceType,
  poet,
}: {
  project: string;
  source: string;
  sourceType: string;
  poet: string | null;
}) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [primary, setPrimary] = useState("poetry");
  const [fallback, setFallback] = useState<string>("commentary");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<null | "saving" | "saved">(null);
  const [recleanStatus, setRecleanStatus] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const c = await api.getCategorize(project, source);
      setRules(c.rules || []);
      setPrimary(c.primary_category || "poetry");
      setFallback(c.fallback_category || "commentary");
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoaded(true);
    }
  }, [project, source]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function save() {
    setSaved("saving");
    setError(null);
    try {
      await api.putCategorize(project, source, {
        rules,
        primary_category: primary,
        fallback_category: fallback,
      });
      setSaved("saved");
      setTimeout(() => setSaved(null), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaved(null);
    }
  }

  async function reclean() {
    setRecleanStatus("queued…");
    try {
      const j = await api.enqueueJob(project, "clean");
      setRecleanStatus(`Clean job #${j.id} queued — watch Jobs panel on the project page`);
    } catch (e) {
      setRecleanStatus(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function updateRule(idx: number, patch: Partial<Rule>) {
    setRules((rs) => rs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  function removeRule(idx: number) {
    setRules((rs) => rs.filter((_, i) => i !== idx));
  }

  function addRule() {
    setRules((rs) => [...rs, { text_contains_any: [], set_category: "poetry" }]);
  }

  if (!loaded)
    return (
      <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 text-sm text-zinc-500">
        Loading {source}…
      </div>
    );

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-4">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <div className="font-mono text-sm font-semibold">{source}</div>
          <div className="text-xs text-zinc-500 mt-0.5">
            <span className="font-mono">{sourceType}</span>
            {poet && (
              <>
                {" · "}poet: <span className="font-mono">{poet}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {saved === "saved" && <span className="text-emerald-600">✓ saved</span>}
          <button
            onClick={save}
            disabled={saved === "saving"}
            className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1.5 font-medium disabled:opacity-50"
          >
            {saved === "saving" ? "Saving…" : "Save rules"}
          </button>
          <button
            onClick={reclean}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Re-run cleaning
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}
      {recleanStatus && (
        <div className="rounded-md border border-amber-300 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/50 p-2 text-xs text-amber-800 dark:text-amber-200">
          {recleanStatus}
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-3 text-xs">
        <label className="space-y-1">
          <span className="text-zinc-500">Primary category (→ main file)</span>
          <input
            value={primary}
            onChange={(e) => setPrimary(e.target.value)}
            className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2.5 py-1.5 font-mono"
          />
        </label>
        <label className="space-y-1">
          <span className="text-zinc-500">Fallback category (records matching no rule)</span>
          <input
            value={fallback}
            onChange={(e) => setFallback(e.target.value)}
            className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2.5 py-1.5 font-mono"
          />
        </label>
      </div>

      <div className="space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Rules ({rules.length})
        </div>
        {rules.length === 0 && (
          <div className="text-xs text-zinc-500 italic">
            No rules → all records get category &quot;{primary}&quot;.
          </div>
        )}
        {rules.map((r, idx) => (
          <RuleRow
            key={idx}
            rule={r}
            onChange={(p) => updateRule(idx, p)}
            onRemove={() => removeRule(idx)}
          />
        ))}
        <button
          onClick={addRule}
          className="text-xs text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 underline"
        >
          + Add rule
        </button>
      </div>
    </div>
  );
}

function RuleRow({
  rule,
  onChange,
  onRemove,
}: {
  rule: Rule;
  onChange: (patch: Partial<Rule>) => void;
  onRemove: () => void;
}) {
  const text = rule.text_contains_any.join("\n");
  return (
    <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-3 space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-xs text-zinc-500">If text contains any of</span>
        <span className="text-xs text-zinc-400">(one per line)</span>
        <button
          onClick={onRemove}
          className="ml-auto text-xs text-red-600 hover:text-red-800"
        >
          remove
        </button>
      </div>
      <textarea
        value={text}
        onChange={(e) =>
          onChange({
            text_contains_any: e.target.value
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          })
        }
        dir="auto"
        rows={Math.max(2, rule.text_contains_any.length + 1)}
        className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2.5 py-1.5 text-sm font-mono"
        placeholder="#حذيفة_العرجي"
      />
      <label className="flex items-center gap-2 text-xs">
        <span className="text-zinc-500">→ set category</span>
        <input
          value={rule.set_category}
          onChange={(e) => onChange({ set_category: e.target.value })}
          className="rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
        />
      </label>
    </div>
  );
}
