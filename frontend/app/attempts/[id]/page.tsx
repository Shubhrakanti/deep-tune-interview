"use client";

import { use, useEffect, useState } from "react";
import {
  api,
  type Attempt,
  type GradeResponse,
  type TrajectoryEvent,
} from "@/lib/api";
import { usePolling } from "@/lib/polling";
import { AttemptPill, StatusBadge } from "@/components/AttemptPill";
import { JsonDiff } from "@/components/JsonDiff";
import { TranscriptViewer } from "@/components/TranscriptViewer";
import { VideoPlayer } from "@/components/VideoPlayer";

const TERMINAL = new Set(["passed", "failed", "error"]);

export default function AttemptPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: attempt, error: attErr } = usePolling(
    () => api.getAttempt(id),
    3000,
    (a) => TERMINAL.has(a.status),
  );
  if (attErr) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8 text-sm text-rose-700">
        Failed to load attempt: {String(attErr)}
      </div>
    );
  }
  if (!attempt) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8 text-sm text-neutral-500">
        Loading…
      </div>
    );
  }
  return <AttemptDetail attempt={attempt} />;
}

function AttemptDetail({ attempt }: { attempt: Attempt }) {
  const terminal = TERMINAL.has(attempt.status);
  return (
    <div className="max-w-7xl mx-auto px-6 py-6 space-y-5">
      <Header attempt={attempt} />
      <GradePanel attemptId={attempt.id} terminal={terminal} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wider text-neutral-500">
            Session video
          </div>
          {terminal ? (
            <VideoPlayer src={api.videoUrl(attempt.id)} />
          ) : (
            <Placeholder text="Video appears when the attempt finishes" />
          )}
        </div>
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wider text-neutral-500">
            Transcript
          </div>
          <Transcript attemptId={attempt.id} terminal={terminal} />
        </div>
      </div>
    </div>
  );
}

function Header({ attempt }: { attempt: Attempt }) {
  return (
    <div>
      <div className="flex items-baseline gap-3 mb-1">
        <a
          href={`/jobs/${attempt.job_id}`}
          className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        >
          ← job
        </a>
        <h1 className="text-xl font-semibold tracking-tight font-mono">
          {attempt.problem_id} <span className="text-neutral-400">#{attempt.attempt_num}</span>
        </h1>
        <StatusBadge status={attempt.status} />
      </div>
      <div className="mono text-xs text-neutral-500">{attempt.id}</div>
      <div className="flex gap-4 text-xs text-neutral-500 mt-2">
        {attempt.duration_ms != null && (
          <span>
            duration: <span className="mono text-neutral-700 dark:text-neutral-300">{(attempt.duration_ms / 1000).toFixed(1)}s</span>
          </span>
        )}
        {attempt.step_count != null && (
          <span>
            steps: <span className="mono text-neutral-700 dark:text-neutral-300">{attempt.step_count}</span>
          </span>
        )}
        {attempt.grade_message && (
          <span>
            grade: <span className="mono text-neutral-700 dark:text-neutral-300">{attempt.grade_message}</span>
          </span>
        )}
      </div>
      {attempt.error_message && (
        <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 p-2 text-sm text-amber-900 dark:text-amber-200">
          {attempt.error_message}
        </div>
      )}
    </div>
  );
}

function GradePanel({
  attemptId,
  terminal,
}: {
  attemptId: string;
  terminal: boolean;
}) {
  const [grade, setGrade] = useState<GradeResponse | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    let cancelled = false;
    if (!terminal) return;
    api
      .getGrade(attemptId)
      .then((g) => !cancelled && setGrade(g))
      .catch((e) => !cancelled && setErr(e));
    return () => {
      cancelled = true;
    };
  }, [attemptId, terminal]);
  if (!terminal) {
    return <Placeholder text="Grade appears when the attempt finishes" />;
  }
  if (err) {
    return (
      <div className="rounded-md border border-rose-300 bg-rose-50 dark:bg-rose-950/30 p-3 text-sm text-rose-800">
        Failed to load grade: {String(err)}
      </div>
    );
  }
  if (!grade) {
    return <Placeholder text="Loading grade…" />;
  }
  const expected = (grade.details as { expected?: unknown })?.expected;
  const actual = (grade.details as { actual?: unknown })?.actual;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="text-xs uppercase tracking-wider text-neutral-500">
          Grade
        </div>
        <AttemptPill
          status={grade.passed ? "passed" : grade.passed === false ? "failed" : "error"}
          label={grade.message ?? "?"}
        />
      </div>
      <JsonDiff expected={expected} actual={actual} passed={grade.passed} />
      {grade.task?.task && (
        <details className="rounded-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 text-sm">
          <summary className="cursor-pointer text-xs uppercase tracking-wider text-neutral-500">
            Original task prompt
          </summary>
          <p className="mt-2 whitespace-pre-wrap text-neutral-700 dark:text-neutral-300">
            {grade.task.task}
          </p>
        </details>
      )}
    </div>
  );
}

function Transcript({
  attemptId,
  terminal,
}: {
  attemptId: string;
  terminal: boolean;
}) {
  const [events, setEvents] = useState<TrajectoryEvent[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  // poll while not terminal; once terminal fetch once.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const next = await api.getTrajectory(attemptId);
        if (cancelled) return;
        setEvents(next);
        setErr(null);
        if (!terminal) {
          timer = setTimeout(tick, 3000);
        }
      } catch (e) {
        if (cancelled) return;
        setErr(e);
        if (!terminal) timer = setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [attemptId, terminal]);

  if (err) {
    return (
      <div className="rounded-md border border-rose-300 bg-rose-50 dark:bg-rose-950/30 p-3 text-sm text-rose-800">
        Failed to load trajectory: {String(err)}
      </div>
    );
  }
  if (events === null) {
    return <Placeholder text="Loading trajectory…" />;
  }
  return (
    <div className="max-h-[70vh] overflow-y-auto rounded-md border border-neutral-200 dark:border-neutral-800 p-3 bg-neutral-50 dark:bg-neutral-950">
      <TranscriptViewer attemptId={attemptId} events={events} />
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="text-sm text-neutral-500 py-8 text-center border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg">
      {text}
    </div>
  );
}
