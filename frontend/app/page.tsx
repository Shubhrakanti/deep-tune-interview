"use client";

import { api } from "@/lib/api";
import { usePolling } from "@/lib/polling";
import { JobsTable } from "@/components/JobsTable";

export default function JobsListPage() {
  const { data, error } = usePolling(
    () => api.listJobs(),
    3000,
    (jobs) => jobs.every((j) => j.status === "done"),
  );
  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="text-xs text-neutral-500">
          Auto-refreshes while any job is running
        </p>
      </div>
      {error ? (
        <div className="rounded-md border border-rose-300 bg-rose-50 dark:bg-rose-950/30 p-3 text-sm text-rose-800 dark:text-rose-200 mb-4">
          Couldn&apos;t reach API at{" "}
          {process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}. Is
          uvicorn running? ({String(error)})
        </div>
      ) : null}
      {data ? (
        <JobsTable jobs={data} />
      ) : (
        <div className="text-sm text-neutral-500">Loading…</div>
      )}
    </div>
  );
}
