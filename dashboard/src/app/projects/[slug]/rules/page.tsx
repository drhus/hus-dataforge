import Link from "next/link";
import { api } from "@/lib/api";
import { CleanupEditor } from "./cleanup-editor";
import { RulesEditor } from "./rules-editor";

export const dynamic = "force-dynamic";

export default async function RulesPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const project = await api.getProject(slug);
  const sources =
    ((project.config as Record<string, unknown>).sources as
      | Array<Record<string, unknown>>
      | undefined) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/projects/${slug}`}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          ← {slug}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight mt-1">
          Cleanup &amp; categorize rules
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Per-source rules applied during the clean stage. Cleanup runs first
          (title/text transforms + filter); categorize runs second (assigns
          records to primary vs sidecar files).
        </p>
      </div>

      {sources.length === 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No sources configured for this project.
        </div>
      )}

      <div className="space-y-5">
        {sources.map((s) => {
          const name = s.name as string;
          const type = s.type as string;
          const poet = (s.poet as string) || null;
          const isSocial = type.startsWith("telegram") || type === "x_syndication";

          return (
            <div
              key={name}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-5"
            >
              <header className="flex items-baseline justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <div>
                  <div className="font-mono text-sm font-semibold">{name}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">
                    <span className="font-mono">{type}</span>
                    {poet && (
                      <>
                        {" · "}poet: <span className="font-mono">{poet}</span>
                      </>
                    )}
                  </div>
                </div>
              </header>

              <CleanupEditor project={slug} source={name} sourceType={type} />

              {isSocial && (
                <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800">
                  <RulesEditor project={slug} source={name} sourceType={type} poet={poet} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
