"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Op = { op: string; [k: string]: unknown };
type Rules = {
  title_ops: Op[];
  text_ops: Op[];
  filter_min_chars: number;
  filter_min_lines: number;
  filter_min_arabic_ratio: number;
  drop_if_url_dominated: boolean;
};

export function CleanupEditor({
  project,
  source,
  sourceType,
}: {
  project: string;
  source: string;
  sourceType: string;
}) {
  const [rules, setRules] = useState<Rules | null>(null);
  const [overridden, setOverridden] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<null | "saving" | "saved">(null);

  const reload = useCallback(async () => {
    try {
      const c = await api.getCleanupRules(project, source);
      setRules(c.rules);
      setOverridden(c.is_overridden);
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
    if (!rules) return;
    setSaved("saving");
    setError(null);
    try {
      await api.putCleanupRules(project, source, rules);
      setSaved("saved");
      setOverridden(true);
      setTimeout(() => setSaved(null), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaved(null);
    }
  }

  async function reset() {
    if (!confirm(`Reset cleanup rules for ${source} to defaults?`)) return;
    try {
      await api.resetCleanupRules(project, source);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!loaded) {
    return (
      <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 text-xs text-zinc-500">
        Loading cleanup rules for {source}…
      </div>
    );
  }
  if (!rules) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2 text-xs">
        <span className="font-semibold uppercase tracking-wider text-zinc-500">
          Cleanup rules
        </span>
        <span className="text-zinc-400">
          {overridden ? "(overridden)" : `(${sourceType} defaults)`}
        </span>
        <div className="ml-auto flex gap-2">
          {saved === "saved" && <span className="text-emerald-600">✓ saved</span>}
          <button
            onClick={save}
            disabled={saved === "saving"}
            className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-2 py-0.5 disabled:opacity-50"
          >
            {saved === "saving" ? "Saving…" : "Save"}
          </button>
          {overridden && (
            <button
              onClick={reset}
              className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              Reset to defaults
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-2 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <OpListEditor
        label="Title ops"
        kind="title"
        ops={rules.title_ops}
        onChange={(ops) => setRules({ ...rules, title_ops: ops })}
      />

      <OpListEditor
        label="Text ops"
        kind="text"
        ops={rules.text_ops}
        onChange={(ops) => setRules({ ...rules, text_ops: ops })}
      />

      <div className="grid grid-cols-2 gap-3 text-xs">
        <NumberInput
          label="Min chars"
          value={rules.filter_min_chars}
          onChange={(v) => setRules({ ...rules, filter_min_chars: v })}
        />
        <NumberInput
          label="Min lines"
          value={rules.filter_min_lines}
          onChange={(v) => setRules({ ...rules, filter_min_lines: v })}
        />
        <NumberInput
          label="Min Arabic ratio (0–1)"
          step={0.05}
          value={rules.filter_min_arabic_ratio}
          onChange={(v) => setRules({ ...rules, filter_min_arabic_ratio: v })}
        />
        <label className="flex items-center gap-2 mt-5">
          <input
            type="checkbox"
            checked={rules.drop_if_url_dominated}
            onChange={(e) =>
              setRules({ ...rules, drop_if_url_dominated: e.target.checked })
            }
          />
          <span className="text-zinc-600 dark:text-zinc-400">Drop URL-only records</span>
        </label>
      </div>
    </div>
  );
}

function NumberInput({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
}) {
  return (
    <label className="space-y-1">
      <span className="text-zinc-500">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
      />
    </label>
  );
}

function OpListEditor({
  label,
  kind,
  ops,
  onChange,
}: {
  label: string;
  kind: "title" | "text";
  ops: Op[];
  onChange: (ops: Op[]) => void;
}) {
  function update(i: number, patch: Op) {
    onChange(ops.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));
  }
  function remove(i: number) {
    onChange(ops.filter((_, idx) => idx !== i));
  }
  function add(kindOp: string) {
    const empty: Record<string, Op> = {
      split_last: { op: "split_last", separator: "»", if_starts_with: "" },
      truncate_before_first_of: { op: "truncate_before_first_of", markers: [] },
      strip_lines_matching: { op: "strip_lines_matching", pattern: "" },
      regex_replace: { op: "regex_replace", pattern: "", replacement: "" },
    };
    onChange([...ops, empty[kindOp]]);
  }

  const availableOps =
    kind === "title"
      ? ["split_last", "regex_replace"]
      : ["truncate_before_first_of", "strip_lines_matching", "regex_replace"];

  return (
    <div className="space-y-2 text-xs">
      <div className="text-zinc-500">{label}</div>
      {ops.length === 0 && (
        <div className="text-zinc-400 italic">No ops — title/text passes through.</div>
      )}
      <div className="space-y-2">
        {ops.map((op, i) => (
          <OpRow key={i} op={op} onChange={(p) => update(i, p)} onRemove={() => remove(i)} />
        ))}
      </div>
      <div className="flex gap-1">
        {availableOps.map((o) => (
          <button
            key={o}
            onClick={() => add(o)}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-2 py-0.5 text-[11px] hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            + {o}
          </button>
        ))}
      </div>
    </div>
  );
}

function OpRow({
  op,
  onChange,
  onRemove,
}: {
  op: Op;
  onChange: (p: Op) => void;
  onRemove: () => void;
}) {
  return (
    <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-2 space-y-1">
      <div className="flex items-center gap-2">
        <code className="text-zinc-700 dark:text-zinc-300">{op.op}</code>
        <button
          onClick={onRemove}
          className="ml-auto text-red-600 hover:text-red-800"
        >
          remove
        </button>
      </div>
      {op.op === "split_last" && (
        <div className="grid grid-cols-2 gap-2">
          <Field
            label="separator"
            value={(op.separator as string) || ""}
            onChange={(v) => onChange({ ...op, separator: v })}
          />
          <Field
            label="if_starts_with"
            value={(op.if_starts_with as string) || ""}
            onChange={(v) => onChange({ ...op, if_starts_with: v })}
          />
        </div>
      )}
      {op.op === "truncate_before_first_of" && (
        <Field
          label="markers (one per line)"
          textarea
          value={((op.markers as string[]) || []).join("\n")}
          onChange={(v) =>
            onChange({
              ...op,
              markers: v.split("\n").map((s) => s.trim()).filter(Boolean),
            })
          }
        />
      )}
      {op.op === "strip_lines_matching" && (
        <Field
          label="regex pattern"
          value={(op.pattern as string) || ""}
          onChange={(v) => onChange({ ...op, pattern: v })}
        />
      )}
      {op.op === "regex_replace" && (
        <div className="grid grid-cols-2 gap-2">
          <Field
            label="pattern"
            value={(op.pattern as string) || ""}
            onChange={(v) => onChange({ ...op, pattern: v })}
          />
          <Field
            label="replacement"
            value={(op.replacement as string) || ""}
            onChange={(v) => onChange({ ...op, replacement: v })}
          />
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  textarea,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  textarea?: boolean;
}) {
  return (
    <label className="space-y-0.5 text-[11px]">
      <span className="text-zinc-500 block">{label}</span>
      {textarea ? (
        <textarea
          dir="auto"
          rows={Math.max(2, value.split("\n").length)}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
        />
      ) : (
        <input
          dir="auto"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="block w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2 py-1 font-mono"
        />
      )}
    </label>
  );
}
