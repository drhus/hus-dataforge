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
  searchParams: Promise<{
    offset?: string;
    q?: string;
    run_id?: string;
    topic?: string;
    meter?: string;
    category?: string;
  }>;
}) {
  const { slug, stage, source } = await params;
  const sp = await searchParams;
  const offset = Number(sp.offset ?? "0") || 0;
  const q = sp.q?.trim() || undefined;
  const runId = sp.run_id ? Number(sp.run_id) : undefined;
  const topic = sp.topic?.trim() || undefined;
  const meter = sp.meter?.trim() || undefined;
  const category = sp.category?.trim() || undefined;

  const [pageRes, facetsRes] = await Promise.allSettled([
    api.listRecords(slug, stage, source, {
      offset,
      limit: PAGE_SIZE,
      q,
      run_id: runId,
      topic,
      meter,
      category,
    }),
    api.listFacets(slug, stage, source),
  ]);

  const page = pageRes.status === "fulfilled" ? pageRes.value : null;
  const error =
    pageRes.status === "rejected"
      ? pageRes.reason instanceof Error
        ? pageRes.reason.message
        : String(pageRes.reason)
      : null;
  const facets = facetsRes.status === "fulfilled" ? facetsRes.value : null;

  const activeFilters: { label: string; key: string; value: string }[] = [];
  if (q) activeFilters.push({ label: "search", key: "q", value: q });
  if (topic) activeFilters.push({ label: "topic", key: "topic", value: topic });
  if (meter) activeFilters.push({ label: "meter", key: "meter", value: meter });
  if (category) activeFilters.push({ label: "category", key: "category", value: category });
  if (runId != null)
    activeFilters.push({ label: "run", key: "run_id", value: `#${runId}` });

  function withParam(extra: Record<string, string | undefined>): string {
    const u = new URLSearchParams();
    if (q) u.set("q", q);
    if (runId != null) u.set("run_id", String(runId));
    if (topic) u.set("topic", topic);
    if (meter) u.set("meter", meter);
    if (category) u.set("category", category);
    for (const [k, v] of Object.entries(extra)) {
      if (v === undefined) u.delete(k);
      else u.set(k, v);
    }
    const s = u.toString();
    return `/projects/${slug}/data/${stage}/${source}${s ? `?${s}` : ""}`;
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
          {activeFilters.length
            ? `matches`
            : "records"}
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
        {runId != null && <input type="hidden" name="run_id" defaultValue={String(runId)} />}
        {topic && <input type="hidden" name="topic" defaultValue={topic} />}
        {meter && <input type="hidden" name="meter" defaultValue={meter} />}
        {category && <input type="hidden" name="category" defaultValue={category} />}
        <button
          type="submit"
          className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-2 text-sm font-medium"
        >
          Search
        </button>
      </form>

      {activeFilters.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-zinc-500">filters:</span>
          {activeFilters.map((f) => (
            <Link
              key={`${f.key}-${f.value}`}
              href={withParam({ [f.key]: undefined, offset: undefined })}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-300 dark:hover:bg-zinc-700"
              title="Remove this filter"
            >
              <span className="opacity-60">{f.label}:</span>
              <span>{f.value}</span>
              <span className="opacity-50">×</span>
            </Link>
          ))}
          <Link
            href={`/projects/${slug}/data/${stage}/${source}`}
            className="text-zinc-500 underline decoration-dotted hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            clear all
          </Link>
        </div>
      )}

      {facets && (facets.topics.length > 0 || facets.meters.length > 0) && (
        <details className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <summary className="cursor-pointer px-3 py-2 text-sm text-zinc-700 dark:text-zinc-300 font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
            Filter by metadata
          </summary>
          <div className="px-3 pb-3 pt-1 space-y-3">
            {facets.topics.length > 0 && (
              <FacetGroup
                title="Topics"
                items={facets.topics}
                activeValue={topic}
                makeHref={(v) =>
                  withParam({ topic: v === topic ? undefined : v, offset: undefined })
                }
              />
            )}
            {facets.meters.length > 0 && (
              <FacetGroup
                title="Meter"
                items={facets.meters}
                activeValue={meter}
                makeHref={(v) =>
                  withParam({ meter: v === meter ? undefined : v, offset: undefined })
                }
              />
            )}
            {facets.categories.length > 1 && (
              <FacetGroup
                title="Category"
                items={facets.categories}
                activeValue={category}
                makeHref={(v) =>
                  withParam({ category: v === category ? undefined : v, offset: undefined })
                }
              />
            )}
          </div>
        </details>
      )}

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

function FacetGroup({
  title,
  items,
  activeValue,
  makeHref,
}: {
  title: string;
  items: [string, number][];
  activeValue?: string;
  makeHref: (v: string) => string;
}) {
  return (
    <div>
      <div className="text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">{title}</div>
      <div className="flex flex-wrap gap-1.5" dir="auto">
        {items.map(([value, count]) => {
          const active = value === activeValue;
          return (
            <Link
              key={value}
              href={makeHref(value)}
              className={
                "text-xs px-2 py-0.5 rounded-full border transition " +
                (active
                  ? "bg-emerald-600 border-emerald-600 text-white"
                  : "bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800")
              }
              title={`${count.toLocaleString()} records`}
            >
              {value}{" "}
              <span className={active ? "opacity-80" : "opacity-50"}>{count}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
