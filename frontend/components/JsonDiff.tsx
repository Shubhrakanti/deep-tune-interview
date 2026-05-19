"use client";

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function JsonDiff({
  expected,
  actual,
  passed,
}: {
  expected: unknown;
  actual: unknown;
  passed: boolean | null;
}) {
  const ok = passed === true;
  const bad = passed === false;
  const tone = ok
    ? "border-emerald-300 dark:border-emerald-700"
    : bad
      ? "border-rose-300 dark:border-rose-700"
      : "border-neutral-300 dark:border-neutral-700";
  return (
    <div className={`grid grid-cols-2 gap-3 rounded-md border ${tone} p-3 bg-white dark:bg-neutral-900`}>
      <div>
        <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">
          Expected
        </div>
        <pre className="mono text-xs whitespace-pre-wrap break-words bg-neutral-50 dark:bg-neutral-950 rounded p-2 overflow-auto max-h-72">
{pretty(expected)}
        </pre>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">
          Actual
        </div>
        <pre
          className={`mono text-xs whitespace-pre-wrap break-words rounded p-2 overflow-auto max-h-72 ${
            ok
              ? "bg-emerald-50 dark:bg-emerald-950/40"
              : bad
                ? "bg-rose-50 dark:bg-rose-950/40"
                : "bg-neutral-50 dark:bg-neutral-950"
          }`}
        >
{actual === undefined ? "(no answer extracted)" : pretty(actual)}
        </pre>
      </div>
    </div>
  );
}
