import Link from "next/link";
import { api } from "@/lib/api";
import { RulesEditor } from "./rules-editor";

export const dynamic = "force-dynamic";

export default async function RulesPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const project = await api.getProject(slug);
  const sources = (project.config as Record<string, unknown>).sources as
    | Array<Record<string, unknown>>
    | undefined;

  const categorizableSources = (sources ?? []).filter((s) => {
    const t = (s.type as string) || "";
    return t.startsWith("telegram") || t === "x_syndication";
  });

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/projects/${slug}`}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          ← {slug}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight mt-1">Cleaning rules</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Per-source categorize rules. Records matching a rule&apos;s{" "}
          <code>text_contains_any</code> get that category. Primary-category records
          go to <code>clean/&lt;poet&gt;.jsonl</code>; everything else to{" "}
          <code>clean/&lt;poet&gt;__&lt;category&gt;.jsonl</code>.
        </p>
      </div>

      {categorizableSources.length === 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No social sources to categorize. Aldiwan-style sources are uniformly
          poetry — they all flow into the primary file by default.
        </div>
      )}

      <div className="space-y-4">
        {categorizableSources.map((s) => (
          <RulesEditor
            key={s.name as string}
            project={slug}
            source={s.name as string}
            sourceType={s.type as string}
            poet={(s.poet as string) || null}
          />
        ))}
      </div>
    </div>
  );
}
