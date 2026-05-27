import Link from "next/link";
import { AddSourceWizard } from "./wizard";

export const dynamic = "force-dynamic";

export default async function AddSourcePage({
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
        <h1 className="text-2xl font-semibold tracking-tight mt-1">Add source</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Paste a URL or search for a poet/person name. The wizard auto-detects
          the spider type, runs a small dry-run, suggests cleanup rules, and
          saves everything to the project on confirm.
        </p>
      </div>
      <AddSourceWizard project={slug} />
    </div>
  );
}
