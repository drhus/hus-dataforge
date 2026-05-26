"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

const TEMPLATE_DEFAULTS: Record<string, string> = {
  generic: `template: generic
sources: []
cleaning: {}
export:
  format: jsonl
`,
  poetry: `template: poetry
sources:
  - name: qafiyah
    type: paginated
    base_url: https://qafiyah.com
cleaning:
  preserve_line_breaks: true
  language: ar
export:
  format: jsonl
`,
};

export default function NewProjectPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [template, setTemplate] = useState<keyof typeof TEMPLATE_DEFAULTS>("generic");
  const [yamlText, setYamlText] = useState(TEMPLATE_DEFAULTS.generic);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function onTemplateChange(t: keyof typeof TEMPLATE_DEFAULTS) {
    setTemplate(t);
    setYamlText(TEMPLATE_DEFAULTS[t]);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // very light parse: ship YAML as a string field for now; backend will parse later.
      // For Milestone 1 we send a minimal config object — the YAML editor is wired,
      // round-trip parsing lands when the scraping engine reads configs.
      const config = { _yaml: yamlText, template };
      await api.createProject(slug, config);
      router.push(`/projects/${slug}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New project</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Slug becomes the directory under <code>projects/</code> and the dataset name.
        </p>
      </div>

      <label className="block space-y-1">
        <span className="text-sm font-medium">Slug</span>
        <input
          required
          pattern="^[a-z0-9][a-z0-9-]{0,62}$"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="arabic-poetry"
          className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm font-mono"
        />
      </label>

      <label className="block space-y-1">
        <span className="text-sm font-medium">Template</span>
        <select
          value={template}
          onChange={(e) => onTemplateChange(e.target.value as keyof typeof TEMPLATE_DEFAULTS)}
          className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm"
        >
          <option value="generic">generic</option>
          <option value="poetry">poetry</option>
        </select>
      </label>

      <label className="block space-y-1">
        <span className="text-sm font-medium">config.yaml</span>
        <textarea
          value={yamlText}
          onChange={(e) => setYamlText(e.target.value)}
          rows={14}
          className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm font-mono"
        />
      </label>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create project"}
        </button>
      </div>
    </form>
  );
}
