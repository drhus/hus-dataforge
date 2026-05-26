import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { JobsPanel } from "./jobs-panel";

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
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Config
        </h2>
        <pre className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 text-xs font-mono overflow-x-auto">
          {JSON.stringify(project.config, null, 2)}
        </pre>
      </section>

      <JobsPanel slug={project.slug} />
    </div>
  );
}
