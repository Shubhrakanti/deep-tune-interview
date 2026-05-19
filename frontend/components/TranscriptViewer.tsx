"use client";

import { useState } from "react";
import { api, type TrajectoryEvent } from "@/lib/api";

function timeFromIso(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso.slice(11, 19);
  }
}

function formatArgs(args: Record<string, unknown>): string {
  // Compact arg rendering: keep it short but readable. Truncate `text` for
  // type_text_at, leave coords / direction as-is.
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    let s: string;
    if (typeof v === "string") {
      s = v.length > 40 ? JSON.stringify(v.slice(0, 40) + "…") : JSON.stringify(v);
    } else {
      s = JSON.stringify(v);
    }
    parts.push(`${k}=${s}`);
  }
  return parts.join(", ");
}

export function TranscriptViewer({
  attemptId,
  events,
}: {
  attemptId: string;
  events: TrajectoryEvent[];
}) {
  const [lightboxN, setLightboxN] = useState<number | null>(null);
  if (events.length === 0) {
    return (
      <div className="text-sm text-neutral-500 py-12 text-center border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg">
        Trajectory empty — attempt hasn&apos;t produced any events yet.
      </div>
    );
  }
  return (
    <>
      <ol className="space-y-1.5">
        {events.map((e) => (
          <EventRow
            key={e.seq}
            event={e}
            attemptId={attemptId}
            onShotClick={setLightboxN}
          />
        ))}
      </ol>
      {lightboxN !== null && (
        // Click anywhere to dismiss.
        <div
          className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-6 cursor-zoom-out"
          onClick={() => setLightboxN(null)}
        >
          <img
            src={api.screenshotUrl(attemptId, lightboxN)}
            alt={`step ${lightboxN}`}
            className="max-w-full max-h-full rounded-lg shadow-2xl"
          />
        </div>
      )}
    </>
  );
}

function EventRow({
  event,
  attemptId,
  onShotClick,
}: {
  event: TrajectoryEvent;
  attemptId: string;
  onShotClick: (n: number) => void;
}) {
  const ts = timeFromIso(event.ts);
  switch (event.kind) {
    case "task_start": {
      const data = event.data as { prompt?: string; base_url?: string };
      return (
        <li className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-900 p-3">
          <div className="text-xs text-neutral-500 mb-1">
            {ts} · task start · {data.base_url ?? ""}
          </div>
          <pre className="mono text-xs whitespace-pre-wrap text-neutral-700 dark:text-neutral-300 max-h-40 overflow-auto">
{data.prompt ?? ""}
          </pre>
        </li>
      );
    }
    case "action": {
      const data = event.data as { name: string; args: Record<string, unknown> };
      return (
        <li className="flex items-baseline gap-3 text-sm font-mono px-3 py-1.5 rounded-md bg-violet-50 dark:bg-violet-950/30 text-violet-900 dark:text-violet-200 border border-violet-200/60 dark:border-violet-900/40">
          <span className="text-violet-400 text-xs shrink-0">{ts}</span>
          <span className="font-semibold">{data.name}</span>
          <span className="text-violet-700 dark:text-violet-300 truncate">
            ({formatArgs(data.args ?? {})})
          </span>
        </li>
      );
    }
    case "observation": {
      const data = event.data as {
        screenshot: string;
        url: string;
        step: number;
      };
      return (
        <li className="flex items-start gap-3 px-3 py-2 rounded-md bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800">
          <span className="text-neutral-400 text-xs font-mono mt-1 shrink-0">
            {ts}
          </span>
          <button
            type="button"
            onClick={() => onShotClick(data.step)}
            className="shrink-0"
          >
            <img
              src={api.screenshotUrl(attemptId, data.step)}
              alt={`step ${data.step}`}
              className="w-32 h-20 object-cover object-top rounded border border-neutral-200 dark:border-neutral-800 hover:border-sky-400 cursor-zoom-in"
              loading="lazy"
            />
          </button>
          <div className="text-xs text-neutral-500 mono break-all">
            step {data.step}
            <br />
            <span className="text-neutral-400">{data.url}</span>
          </div>
        </li>
      );
    }
    case "final_answer": {
      const data = event.data as { text?: string };
      return (
        <li className="rounded-md border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 p-3">
          <div className="text-xs text-emerald-700 dark:text-emerald-300 mb-1 uppercase tracking-wider font-semibold">
            {ts} · final answer
          </div>
          <pre className="mono text-xs whitespace-pre-wrap text-emerald-900 dark:text-emerald-100 max-h-72 overflow-auto">
{data.text ?? ""}
          </pre>
        </li>
      );
    }
    case "grade": {
      const data = event.data as { passed?: boolean; message?: string };
      const ok = !!data.passed;
      return (
        <li
          className={`rounded-md border p-3 ${
            ok
              ? "border-emerald-400 dark:border-emerald-700 bg-emerald-100 dark:bg-emerald-950/50"
              : "border-rose-400 dark:border-rose-700 bg-rose-100 dark:bg-rose-950/50"
          }`}
        >
          <div className="text-xs uppercase tracking-wider font-semibold">
            {ts} · grade · {ok ? "PASS" : "FAIL"}
          </div>
          <div className="text-sm mt-0.5">{data.message}</div>
        </li>
      );
    }
    default: {
      return (
        <li className="text-xs text-neutral-500 mono px-3 py-1.5">
          {ts} · {event.kind} · {JSON.stringify(event.data)}
        </li>
      );
    }
  }
}
