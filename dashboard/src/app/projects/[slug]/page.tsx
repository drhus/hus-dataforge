import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { ConfigEditor } from "./config-editor";
import { ExpandSearchButton } from "./expand-search-button";
import { JobsPanel } from "./jobs-panel";
import { SubjectEpubButton } from "./subject-epub-button";

export const dynamic = "force-dynamic";

export default async function ProjectDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  let project: Awaited<ReturnType<typeof api.getProject>>;
  try {
    project = await api.getProject(slug);
  } catch {
    notFound();
  }

  let poets: Awaited<ReturnType<typeof api.listSubjectsWithStats>>["subjects"] = [];
  try {
    poets = (await api.listSubjectsWithStats(slug)).subjects;
  } catch {
    poets = [];
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
            ← Projects
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight mt-1 font-mono">
            {project.slug}
          </h1>
          <div className="text-xs text-zinc-500 mt-1">
            updated {new Date(project.updated_at).toLocaleString()}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Link
            href={`/projects/${project.slug}/add-source`}
            className="rounded-md bg-emerald-600 text-white px-3 py-2 text-sm font-medium hover:opacity-90"
          >
            + Add source
          </Link>
          <Link
            href={`/projects/${project.slug}/rules`}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Rules
          </Link>
          <Link
            href={`/projects/${project.slug}/schedules`}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Schedules
          </Link>
          <Link
            href={`/projects/${project.slug}/data`}
            className="rounded-md border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Browse data →
          </Link>
        </div>
      </div>

      {poets.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
            Subjects ({poets.length})
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {poets.map((p) => {
              const type = (p as { type?: string }).type || "poet";
              const typeStyle: Record<string, string> = {
                poet: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
                person: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
                topic: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
                site: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
              };
              const stats = p._stats;
              const totalRecords =
                stats != null ? stats.totals.raw + stats.totals.clean + stats.totals.export : 0;
              // Prefer clean stage for the records link if data exists there; fall back to raw.
              const dataLinkTarget =
                stats?.totals.clean && stats.totals.clean > 0
                  ? `/projects/${slug}/data/clean/${p.slug}`
                  : stats?.primary_raw_source
                    ? `/projects/${slug}/data/raw/${stats.primary_raw_source}`
                    : null;
              return (
                <li
                  key={p.slug}
                  className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-2"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="space-y-0.5" dir="auto">
                      {p.name_ar && (
                        <div className="text-lg font-semibold">{p.name_ar}</div>
                      )}
                      <div className="text-xs font-mono text-zinc-500">{p.slug}</div>
                    </div>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${typeStyle[type] || typeStyle.poet}`}>
                      {type}
                    </span>
                  </div>
                  <div className="text-xs text-zinc-600 dark:text-zinc-400 space-y-0.5">
                    {p.name_en && <div>{p.name_en}</div>}
                    {p.country && (
                      <div>
                        {p.country}
                        {p.born ? ` · b. ${p.born}` : ""}
                        {p.died ? ` · d. ${p.died}` : ""}
                      </div>
                    )}
                  </div>
                  {p.sources && Object.keys(p.sources).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1 border-t border-zinc-100 dark:border-zinc-800">
                      {Object.keys(p.sources).map((k) => (
                        <span
                          key={k}
                          className="text-[10px] rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 text-zinc-600 dark:text-zinc-400"
                        >
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                  {stats && totalRecords > 0 && (
                    <div className="flex items-center gap-3 text-xs pt-1 border-t border-zinc-100 dark:border-zinc-800">
                      {dataLinkTarget ? (
                        <Link
                          href={dataLinkTarget}
                          className="font-medium text-emerald-700 dark:text-emerald-300 hover:underline"
                          title={`raw: ${stats.totals.raw} · clean: ${stats.totals.clean} · export: ${stats.totals.export}`}
                        >
                          📚 {stats.totals.clean || stats.totals.raw} poems
                        </Link>
                      ) : (
                        <span className="text-zinc-400">no data yet</span>
                      )}
                      {stats.raw_source_count > 1 && (
                        <span className="text-zinc-500" title="number of raw sources contributing">
                          from {stats.raw_source_count} sources
                        </span>
                      )}
                    </div>
                  )}
                  <div className="pt-1 flex items-center justify-between gap-2">
                    <ExpandSearchButton
                      project={slug}
                      subject={p.slug}
                      nameAr={p.name_ar}
                      nameEn={p.name_en}
                      aliases={p.aliases}
                    />
                    <SubjectEpubButton project={slug} subject={p.slug} />
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <ConfigEditor
        slug={project.slug}
        initialConfig={project.config as Record<string, unknown>}
      />

      <JobsPanel slug={project.slug} />
    </div>
  );
}
