export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Project = {
  slug: string;
  config: Record<string, unknown>;
  updated_at: string;
};

export type Job = {
  id: number;
  project: string;
  kind: "scrape" | "clean" | "export";
  status: "queued" | "running" | "succeeded" | "failed";
  rq_job_id: string | null;
  message: string | null;
  created_at: string;
  updated_at: string;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`API ${r.status}: ${text || r.statusText}`);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export const api = {
  listProjects: () => req<Project[]>("/projects"),
  getProject: (slug: string) => req<Project>(`/projects/${slug}`),
  createProject: (slug: string, config: Record<string, unknown>) =>
    req<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ slug, config }),
    }),
  updateProject: (slug: string, config: Record<string, unknown>) =>
    req<Project>(`/projects/${slug}`, {
      method: "PUT",
      body: JSON.stringify({ config }),
    }),
  deleteProject: (slug: string) =>
    req<void>(`/projects/${slug}`, { method: "DELETE" }),
  listJobs: (project?: string) =>
    req<Job[]>(`/jobs${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  enqueueJob: (project: string, kind: Job["kind"], duration_sec = 5) =>
    req<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({ project, kind, duration_sec }),
    }),
  getJob: (id: number) => req<Job>(`/jobs/${id}`),
};
