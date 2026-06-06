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
  aliases?: string[];
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
  enqueueJob: (
    project: string,
    kind: Job["kind"],
    opts: { duration_sec?: number; force?: boolean } = {},
  ) =>
    req<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({
        project,
        kind,
        duration_sec: opts.duration_sec ?? 5,
        force: opts.force ?? false,
      }),
    }),
  getJob: (id: number) => req<Job>(`/jobs/${id}`),
  listSources: (project: string, stage: "raw" | "clean" | "export") =>
    req<{ sources: DataSource[] }>(`/data/${project}/sources?stage=${stage}`),
  listRecords: (
    project: string,
    stage: string,
    source: string,
    opts: {
      offset?: number;
      limit?: number;
      q?: string;
      run_id?: number;
      topic?: string;
      meter?: string;
      category?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (opts.offset) qs.set("offset", String(opts.offset));
    if (opts.limit) qs.set("limit", String(opts.limit));
    if (opts.q) qs.set("q", opts.q);
    if (opts.run_id != null) qs.set("run_id", String(opts.run_id));
    if (opts.topic) qs.set("topic", opts.topic);
    if (opts.meter) qs.set("meter", opts.meter);
    if (opts.category) qs.set("category", opts.category);
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return req<DataPage>(`/data/${project}/${stage}/${source}${tail}`);
  },
  listFacets: (project: string, stage: string, source: string) =>
    req<{
      topics: [string, number][];
      meters: [string, number][];
      categories: [string, number][];
    }>(`/data/${project}/${stage}/${source}/facets`),
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
  listSubjects: (project: string) =>
    req<{ subjects: (PoetManifest & { type: string })[] }>(`/data/${project}/subjects`),
  listSubjectsWithStats: (project: string) =>
    req<{
      subjects: (PoetManifest & {
        type: string;
        _stats?: {
          totals: { raw: number; clean: number; export: number };
          primary_raw_source: string | null;
          raw_source_count: number;
        };
      })[];
    }>(`/data/${project}/subjects-with-stats`),
  subjectStats: (project: string, subject: string) =>
    req<{
      project: string;
      subject: string;
      totals: { raw: number; clean: number; export: number };
      sources: {
        raw: { source: string; count: number; stage: string }[];
        clean: { source: string; count: number; stage: string }[];
        export: { source: string; count: number; stage: string }[];
      };
      primary_raw_source: string | null;
    }>(`/data/${project}/subjects/${subject}/stats`),
  detectSourceType: (url: string) =>
    req<{ type: string; confidence: string; hint: string; [k: string]: unknown }>(
      "/preview/detect",
      { method: "POST", body: JSON.stringify({ url }) },
    ),
  previewSource: (project: string, source: Record<string, unknown>, sample_size = 5) =>
    req<{
      source: string;
      type: string;
      samples: Record<string, unknown>[];
      sample_count: number;
      errors: string[];
    }>("/preview/source", {
      method: "POST",
      body: JSON.stringify({ project, source, sample_size }),
    }),
  suggestCleanup: (samples: Record<string, unknown>[]) =>
    req<{
      title_ops: { op: string; [k: string]: unknown }[];
      text_ops: { op: string; [k: string]: unknown }[];
      filter_min_chars: number;
      filter_min_arabic_ratio: number;
      _stats: Record<string, unknown>;
    }>("/preview/suggest-cleanup", { method: "POST", body: JSON.stringify({ samples }) }),
  youtubeSearch: (query: string, max_results = 25) =>
    req<{
      query: string;
      count: number;
      results: {
        video_id: string;
        title: string;
        duration: number | null;
        channel: string | null;
        channel_url: string | null;
        view_count: number | null;
        thumbnail: string | null;
        url: string;
      }[];
    }>("/preview/youtube-search", {
      method: "POST",
      body: JSON.stringify({ query, max_results }),
    }),
  discoverSources: (
    name: string,
    aliases: string[] = [],
    subject_type: "poet" | "topic" | "person" | "site" = "poet",
  ) =>
    req<{
      candidates: {
        site: string;
        confidence: "high" | "medium" | "low" | "reference";
        url: string;
        source_template: Record<string, unknown> | null;
        notes: string;
        _evidence?: { title: string; url: string; query: string }[];
      }[];
    }>("/preview/discover", {
      method: "POST",
      body: JSON.stringify({ name, aliases, subject_type }),
    }),
  addSource: (
    project: string,
    source: Record<string, unknown>,
    subject: Record<string, unknown> | null = null,
  ) =>
    req<{ ok: boolean; source: Record<string, unknown>; subject: string | null }>(
      `/projects/${project}/sources`,
      { method: "POST", body: JSON.stringify({ source, subject }) },
    ),
  listSchedules: (project: string) =>
    req<{
      schedules: {
        id: string;
        kind: string;
        cron: string;
        enabled: boolean;
        last_run_at?: string;
        next_run_at?: string;
        last_status?: string;
      }[];
    }>(`/projects/${project}/schedules`),
  upsertSchedule: (
    project: string,
    body: { id: string; kind: string; cron: string; enabled: boolean },
  ) =>
    req<{ ok: boolean }>(`/projects/${project}/schedules`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteSchedule: (project: string, schedule_id: string) =>
    req<void>(`/projects/${project}/schedules/${schedule_id}`, { method: "DELETE" }),
  listSchedulePresets: () =>
    req<{
      presets: {
        name: string;
        id: string;
        kind: string;
        cron: string;
        enabled: boolean;
        description: string;
      }[];
    }>(`/schedule-presets`),
  applySchedulePreset: (project: string, preset: string) =>
    req<{ id: string; kind: string; cron: string }>(
      `/projects/${project}/schedules/preset/${preset}`,
      { method: "POST" },
    ),
  getPipeline: (project: string) =>
    req<{
      project: string;
      auto_pipeline: boolean | string[];
      last_run: Record<
        "scrape" | "clean" | "export",
        { id: number; status: string; created_at: string; updated_at: string; chained: boolean } | null
      >;
      last_full_pipeline_at: string | null;
    }>(`/projects/${project}/pipeline`),
  putPipeline: (project: string, auto_pipeline: boolean | string[]) =>
    req<{ project: string; auto_pipeline: boolean | string[] }>(
      `/projects/${project}/pipeline`,
      { method: "PUT", body: JSON.stringify({ auto_pipeline }) },
    ),
  postCuration: (
    project: string,
    actions: { id: string; action: string; category?: string; subject?: string }[],
  ) =>
    req<{ ok: boolean; written: number }>(`/projects/${project}/curation`, {
      method: "POST",
      body: JSON.stringify({ actions }),
    }),
  buildSubjectEpub: (project: string, subject: string) =>
    req<{ project: string; subject: string; out: string; url: string; size: number }>(
      `/data/${project}/subjects/${subject}/epub`,
      { method: "POST" },
    ),
  buildSubjectBundle: (project: string, subject: string) =>
    req<{ project: string; subject: string; out: string; url: string; size: number }>(
      `/data/${project}/subjects/${subject}/bundle`,
      { method: "POST" },
    ),
};
