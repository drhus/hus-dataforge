import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AllJobsPage() {
  let jobs: Awaited<ReturnType<typeof api.listJobs>> = [];
  let error: string | null = null;
  try {
    jobs = await api.listJobs();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Most recent 200 jobs across all projects.
        </p>
      </div>
      {error && (
        <div className="rounded-md border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/50 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}
      {!error && jobs.length === 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 dark:border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No jobs yet.
        </div>
      )}
      {jobs.length > 0 && (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 dark:bg-zinc-900/80 text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">ID</th>
                <th className="text-left px-3 py-2 font-medium">Project</th>
                <th className="text-left px-3 py-2 font-medium">Kind</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="px-3 py-2 font-mono text-xs">{j.id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{j.project}</td>
                  <td className="px-3 py-2">{j.kind}</td>
                  <td className="px-3 py-2">{j.status}</td>
                  <td className="px-3 py-2 text-xs text-zinc-500">
                    {new Date(j.updated_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
