"use client";

import { use } from "react";
import { api, type Attempt, type JobWithAttempts } from "@/lib/api";
import { usePolling } from "@/lib/polling";
import { AttemptPill, StatusBadge } from "@/components/AttemptPill";

export default function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data, error } = usePolling(
    () => api.getJob(id),
    3000,
    (job) => job.status === "done",
  );
  if (error) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-8 text-sm text-rose-700">
        Failed to load job: {String(error)}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-8 text-sm text-neutral-500">
        Loading…
      </div>
    );
  }
  return <JobDetail data={data} />;
}

function JobDetail({ data }: { data: JobWithAttempts }) {
  const { job, counts, status, attempts } = data;
  // group attempts by problem_id
  const byProblem = new Map<string, Attempt[]>();
  for (const a of attempts) {
    const arr = byProblem.get(a.problem_id) ?? [];
    arr.push(a);
    byProblem.set(a.problem_id, arr);
  }
  // stable order: by first-seen attempt
  const problemIds: string[] = [];
  for (const a of attempts) {
    if (!problemIds.includes(a.problem_id)) problemIds.push(a.problem_id);
  }
  const total =
    counts.queued + counts.running + counts.passed + counts.failed + counts.error;
  const passRate = total > 0 ? Math.round((counts.passed / total) * 100) : 0;
  return (
    <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
      <div>
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            {job.name ?? (
              <span className="text-neutral-400 italic">unnamed</span>
            )}
          </h1>
          <StatusBadge status={status} />
        </div>
        <div className="mono text-xs text-neutral-500 mt-1">{job.id}</div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 text-sm">
        <Stat label="Attempts" value={total} />
        <Stat label="Pass rate" value={`${passRate}%`} tone="emerald" />
        <Stat label="Passed" value={counts.passed} tone="emerald" />
        <Stat label="Failed" value={counts.failed} tone="rose" />
        <Stat label="Error" value={counts.error} tone="amber" />
        <Stat label="Queued / running" value={`${counts.queued} / ${counts.running}`} />
      </div>

      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900">
        <div className="border-b border-neutral-200 dark:border-neutral-800 px-4 py-2 text-xs uppercase tracking-wider text-neutral-500">
          Attempts by problem
        </div>
        <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {problemIds.map((pid) => {
            const arr = byProblem.get(pid) ?? [];
            return (
              <li
                key={pid}
                className="px-4 py-3 flex items-center justify-between gap-6"
              >
                <div className="font-mono text-sm">{pid}</div>
                <div className="flex flex-wrap gap-1.5">
                  {arr
                    .sort((x, y) => x.attempt_num - y.attempt_num)
                    .map((a) => (
                      <AttemptPill
                        key={a.id}
                        status={a.status}
                        label={`#${a.attempt_num}`}
                        href={`/attempts/${a.id}`}
                      />
                    ))}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number | string;
  tone?: "neutral" | "emerald" | "rose" | "amber";
}) {
  const toneClass =
    tone === "emerald"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "rose"
        ? "text-rose-700 dark:text-rose-300"
        : tone === "amber"
          ? "text-amber-700 dark:text-amber-300"
          : "text-neutral-900 dark:text-neutral-100";
  return (
    <div className="rounded-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-3 py-2">
      <div className="text-xs uppercase tracking-wider text-neutral-500">
        {label}
      </div>
      <div className={`mono text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
