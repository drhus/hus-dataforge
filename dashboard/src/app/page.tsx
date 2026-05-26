import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let projects = [] as Awaited<ReturnType<typeof api.listProjects>>;
  let error: string | null = null;
  try {
    projects = await api.listProjects();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Each project scrapes one subject into a HuggingFace-ready dataset.
          </p>
        </div>
        <Link
          href="/projects/new"
          className="rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-2 text-sm font-medium hover:opacity-90"
        >
          New project
        </Link>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
          Could not reach API at <code>{process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}</code>:{" "}
          {error}
        </div>
      )}

      {!error && projects.length === 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-8 text-center text-sm text-zinc-600 dark:text-zinc-400">
          No projects yet. Create one to get started.
        </div>
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {projects.map((p) => (
          <li key={p.slug}>
            <Link
              href={`/projects/${p.slug}`}
              className="block rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
            >
              <div className="font-medium">{p.slug}</div>
              <div className="text-xs text-zinc-500 mt-1">
                updated {new Date(p.updated_at).toLocaleString()}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
