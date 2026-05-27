import Link from "next/link";
import { api } from "@/lib/api";
import { RecordsList } from "./records-list";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

export default async function RecordsPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; stage: string; source: string }>;
  searchParams: Promise<{ offset?: string; q?: string; run_id?: string }>;
}) {
  const { slug, stage, source } = await params;
  const sp = await searchParams;
  const offset = Number(sp.offset ?? "0") || 0;
  const q = (sp.q as string | undefined)?.trim() || undefined;
  const runId = sp.run_id ? Number(sp.run_id) : undefined;

  let page: Awaited<ReturnType<typeof api.listRecords>> | null = null;
  let error: string | null = null;
  try {
    page = await api.listRecords(slug, stage, source, {
      offset,
      limit: PAGE_SIZE,
      q,
      run_id: runId,
    });
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-5">
      <div>
        <Link
          href={`/projects/${slug}/data?stage=${stage}`}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          ← {slug} / data / {stage}
        </Link>
        <h1 className="text-xl font-semibold tracking-tight mt-1 font-mono">{source}</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {page?.total.toLocaleString()}{" "}
          {q ? `matches for "${q}"` : runId ? `records from run #${runId}` : "records"}
        </p>
      </div>

      <form className="flex gap-2" action={`/projects/${slug}/data/${stage}/${source}`}>
        <input
          type="text"
          name="q"
          defaultValue={q ?? ""}
          placeholder="Search text…"
          className="flex-1 rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm"
        />
        {runId != null && (
          <input
            type="hidden"
            name="run_id"
            defaultValue={String(runId)}
          />
        )}
        <button
          type="submit"
          className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-2 text-sm font-medium"
        >
          Search
        </button>
      </form>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {page && (
        <RecordsList
          project={slug}
          stage={stage}
          source={source}
          q={q}
          initialPage={{
            records: page.records as Record<string, unknown>[],
            total: page.total,
            offset: page.offset,
          }}
        />
      )}
    </div>
  );
}
