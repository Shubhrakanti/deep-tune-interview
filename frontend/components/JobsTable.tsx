"use client";

import type { JobSummary } from "@/lib/api";
import { StatusBadge } from "./AttemptPill";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function JobsTable({ jobs }: { jobs: JobSummary[] }) {
  if (jobs.length === 0) {
    return (
      <div className="text-sm text-neutral-500 py-12 text-center border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg">
        No jobs yet.{" "}
        <a href="/jobs/new" className="underline">
          Submit one
        </a>
        .
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border border-neutral-200 dark:border-neutral-800 rounded-lg bg-white dark:bg-neutral-900">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 dark:bg-neutral-800/50 text-left text-neutral-500 text-xs uppercase tracking-wider">
          <tr>
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Created</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Pass</th>
            <th className="px-4 py-2 font-medium">Fail</th>
            <th className="px-4 py-2 font-medium">Err</th>
            <th className="px-4 py-2 font-medium">Running</th>
            <th className="px-4 py-2 font-medium">Queued</th>
            <th className="px-4 py-2 font-medium">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {jobs.map((s) => {
            const total =
              s.counts.queued +
              s.counts.running +
              s.counts.passed +
              s.counts.failed +
              s.counts.error;
            return (
              <tr
                key={s.job.id}
                className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50"
              >
                <td className="px-4 py-2">
                  <a
                    href={`/jobs/${s.job.id}`}
                    className="font-medium hover:underline"
                  >
                    {s.job.name ?? (
                      <span className="text-neutral-400 italic">unnamed</span>
                    )}
                  </a>
                  <div className="mono text-xs text-neutral-400">
                    {s.job.id.slice(0, 8)}
                  </div>
                </td>
                <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                  {formatDate(s.job.created_at)}
                </td>
                <td className="px-4 py-2">
                  <StatusBadge status={s.status} />
                </td>
                <td className="px-4 py-2 text-emerald-700 dark:text-emerald-400 mono">
                  {s.counts.passed}
                </td>
                <td className="px-4 py-2 text-rose-700 dark:text-rose-400 mono">
                  {s.counts.failed}
                </td>
                <td className="px-4 py-2 text-amber-700 dark:text-amber-400 mono">
                  {s.counts.error}
                </td>
                <td className="px-4 py-2 text-sky-700 dark:text-sky-400 mono">
                  {s.counts.running}
                </td>
                <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400 mono">
                  {s.counts.queued}
                </td>
                <td className="px-4 py-2 text-neutral-500 mono">{total}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
