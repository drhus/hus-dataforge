import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ProjectDataPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ stage?: string }>;
}) {
  const { slug } = await params;
  const sp = await searchParams;
  const stage = (sp.stage as "raw" | "clean" | "export") || "raw";

  let sources: Awaited<ReturnType<typeof api.listSources>>["sources"] = [];
  let error: string | null = null;
  try {
    sources = (await api.listSources(slug, stage)).sources;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const totalRecords = sources.reduce((s, x) => s + x.count, 0);
  const totalBytes = sources.reduce((s, x) => s + x.bytes, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link
            href={`/projects/${slug}`}
            className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            ← {slug}
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight mt-1">Data</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {totalRecords.toLocaleString()} records · {(totalBytes / 1024 / 1024).toFixed(1)} MB
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-zinc-300 dark:border-zinc-700 p-0.5 text-xs">
          {(["raw", "clean", "export"] as const).map((s) => (
            <Link
              key={s}
              href={`/projects/${slug}/data?stage=${s}`}
              className={`px-2.5 py-1 rounded ${
                stage === s
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-medium"
                  : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
              }`}
            >
              {s}
            </Link>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {!error && sources.length === 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No <code>{stage}</code> data yet for this project.
        </div>
      )}

      <ul className="grid gap-2 sm:grid-cols-2">
        {sources.map((s) => (
          <li key={s.name}>
            <Link
              href={`/projects/${slug}/data/${stage}/${s.name}`}
              className="flex items-center justify-between rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
            >
              <div className="font-mono text-sm">{s.name}</div>
              <div className="text-xs text-zinc-500">
                {s.count.toLocaleString()} · {(s.bytes / 1024).toFixed(0)} KB
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
