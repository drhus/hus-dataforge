import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

export default async function RecordsPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; stage: string; source: string }>;
  searchParams: Promise<{ offset?: string; q?: string }>;
}) {
  const { slug, stage, source } = await params;
  const sp = await searchParams;
  const offset = Number(sp.offset ?? "0") || 0;
  const q = (sp.q as string | undefined)?.trim() || undefined;

  let page: Awaited<ReturnType<typeof api.listRecords>> | null = null;
  let error: string | null = null;
  try {
    page = await api.listRecords(slug, stage, source, { offset, limit: PAGE_SIZE, q });
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const prev = Math.max(0, offset - PAGE_SIZE);
  const hasNext = (page?.total ?? 0) > offset + PAGE_SIZE;
  const next = offset + PAGE_SIZE;

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
          {page?.total.toLocaleString()} {q ? `matches for "${q}"` : "records"}
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

      <ol className="space-y-3" start={offset + 1}>
        {(page?.records ?? []).map((r, i) => (
          <li
            key={`${offset + i}`}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4"
          >
            <RecordCard r={r} />
          </li>
        ))}
      </ol>

      <div className="flex items-center justify-between text-sm">
        {offset > 0 ? (
          <Link
            href={`/projects/${slug}/data/${stage}/${source}?offset=${prev}${q ? `&q=${encodeURIComponent(q)}` : ""}`}
            className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            ← Previous
          </Link>
        ) : (
          <span />
        )}
        <span className="text-zinc-500">
          {offset + 1}–{Math.min(offset + PAGE_SIZE, page?.total ?? 0)} of{" "}
          {page?.total.toLocaleString() ?? "0"}
        </span>
        {hasNext ? (
          <Link
            href={`/projects/${slug}/data/${stage}/${source}?offset=${next}${q ? `&q=${encodeURIComponent(q)}` : ""}`}
            className="text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            Next →
          </Link>
        ) : (
          <span />
        )}
      </div>
    </div>
  );
}

function RecordCard({ r }: { r: Record<string, unknown> }) {
  const title = (r.title as string | null) || null;
  const text = (r.text as string | null) || (r.verses as string | null) || (r.body as string | null) || "";
  const poet = r.poet as string | undefined;
  const url = (r.source_url as string | undefined) || (r._source_url as string | undefined);
  const meta = r.meta as Record<string, unknown> | undefined;

  return (
    <article className="space-y-2" dir="auto">
      <header className="flex items-baseline justify-between gap-3">
        <div className="space-y-0.5">
          {title && <h2 className="font-semibold">{title}</h2>}
          {poet && (
            <div className="text-xs font-mono text-zinc-500">{poet}</div>
          )}
        </div>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 shrink-0"
          >
            source ↗
          </a>
        )}
      </header>
      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
        {text.length > 1200 ? text.slice(0, 1200) + "…" : text}
      </pre>
      {(meta || r.lang || r.word_count != null) && (
        <footer className="flex flex-wrap gap-3 text-xs text-zinc-500 pt-1 border-t border-zinc-100 dark:border-zinc-800">
          {r.lang ? <span>lang: {String(r.lang)}</span> : null}
          {r.word_count != null ? <span>{String(r.word_count)} words</span> : null}
          {r.line_count != null ? <span>{String(r.line_count)} lines</span> : null}
          {meta?.published_at ? (
            <span>posted: {new Date(String(meta.published_at)).toLocaleDateString()}</span>
          ) : null}
          {meta?.views ? <span>{String(meta.views)} views</span> : null}
        </footer>
      )}
    </article>
  );
}
