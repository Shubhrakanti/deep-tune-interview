import type { AttemptStatus } from "@/lib/api";

const PILL_STYLES: Record<AttemptStatus, string> = {
  passed:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-300/60",
  failed:
    "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300 border-rose-300/60",
  error:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-300/60",
  running:
    "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300 border-sky-300/60 animate-pulse",
  queued:
    "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-400 border-neutral-300/60",
};

const SHORT: Record<AttemptStatus, string> = {
  passed: "PASS",
  failed: "FAIL",
  error: "ERR",
  running: "RUN",
  queued: "QUE",
};

export function AttemptPill({
  status,
  label,
  href,
  className = "",
}: {
  status: AttemptStatus;
  label?: string;
  href?: string;
  className?: string;
}) {
  const content = (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-mono ${PILL_STYLES[status]} ${className}`}
    >
      {label ?? SHORT[status]}
    </span>
  );
  return href ? (
    <a href={href} className="hover:opacity-80">
      {content}
    </a>
  ) : (
    content
  );
}

export function StatusBadge({ status }: { status: string }) {
  const s = (status as AttemptStatus) ?? "queued";
  const style = PILL_STYLES[s] ?? PILL_STYLES.queued;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${style}`}
    >
      {status}
    </span>
  );
}
