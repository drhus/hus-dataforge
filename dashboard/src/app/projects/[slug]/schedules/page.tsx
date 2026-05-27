import Link from "next/link";
import { SchedulesEditor } from "./schedules-editor";

export const dynamic = "force-dynamic";

export default async function SchedulesPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return (
    <div className="space-y-5">
      <div>
        <Link
          href={`/projects/${slug}`}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          ← {slug}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight mt-1">Schedules</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Cron-style recurring runs. The scheduler ticks once a minute (via
          systemd timer). Use standard 5-field cron expressions:{" "}
          <code>0 4 * * *</code> = daily at 04:00 UTC.
        </p>
      </div>
      <SchedulesEditor project={slug} />
    </div>
  );
}
