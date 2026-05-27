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

export type DataSource = { name: string; count: number; bytes: number };
export type DataPage = {
  project: string;
  stage: string;
  source: string;
  total: number;
  offset: number;
  limit: number;
  records: Record<string, unknown>[];
};
export type PoetManifest = {
  slug: string;
  name_ar?: string;
  name_en?: string;
  country?: string;
  born?: number | string;
  died?: number | string;
  sources?: Record<string, unknown>;
  notes?: string;
};

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
  listSources: (project: string, stage: "raw" | "clean" | "export") =>
    req<{ sources: DataSource[] }>(`/data/${project}/sources?stage=${stage}`),
  listRecords: (
    project: string,
    stage: string,
    source: string,
    opts: { offset?: number; limit?: number; q?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (opts.offset) qs.set("offset", String(opts.offset));
    if (opts.limit) qs.set("limit", String(opts.limit));
    if (opts.q) qs.set("q", opts.q);
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return req<DataPage>(`/data/${project}/${stage}/${source}${tail}`);
  },
  listPoets: (project: string) =>
    req<{ poets: PoetManifest[] }>(`/data/${project}/poets`),
  getCategorize: (project: string, source: string) =>
    req<{
      source: string;
      rules: { text_contains_any: string[]; set_category: string }[];
      primary_category: string;
      fallback_category: string | null;
    }>(`/projects/${project}/sources/${source}/categorize`),
  putCategorize: (
    project: string,
    source: string,
    body: {
      rules: { text_contains_any: string[]; set_category: string }[];
      primary_category?: string | null;
      fallback_category?: string | null;
    },
  ) =>
    req<{ ok: boolean }>(`/projects/${project}/sources/${source}/categorize`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getCleanupRules: (project: string, source: string) =>
    req<{
      source: string;
      source_type: string;
      is_overridden: boolean;
      rules: {
        title_ops: { op: string; [k: string]: unknown }[];
        text_ops: { op: string; [k: string]: unknown }[];
        filter_min_chars: number;
        filter_min_lines: number;
        filter_min_arabic_ratio: number;
        drop_if_url_dominated: boolean;
      };
    }>(`/projects/${project}/sources/${source}/cleanup`),
  putCleanupRules: (
    project: string,
    source: string,
    body: {
      title_ops?: { op: string; [k: string]: unknown }[];
      text_ops?: { op: string; [k: string]: unknown }[];
      filter_min_chars?: number;
      filter_min_lines?: number;
      filter_min_arabic_ratio?: number;
      drop_if_url_dominated?: boolean;
    },
  ) =>
    req<{ ok: boolean }>(`/projects/${project}/sources/${source}/cleanup`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  resetCleanupRules: (project: string, source: string) =>
    req<void>(`/projects/${project}/sources/${source}/cleanup`, { method: "DELETE" }),
};
