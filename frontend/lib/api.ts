/**
 * Tiny typed client for the FastAPI backend at NEXT_PUBLIC_API_BASE.
 *
 * Types here mirror backend/models.py — kept in sync manually since there are
 * only a handful of fields. If they drift, the API responses will fail to
 * narrow at compile time and you'll see it immediately in TranscriptViewer
 * etc.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type AttemptStatus =
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "error";

export type JobStatus = "queued" | "running" | "done";

export interface Job {
  id: string;
  name: string | null;
  tasks_file_path: string;
  attempts_per_problem: number;
  created_at: string;
}

export interface Attempt {
  id: string;
  job_id: string;
  problem_id: string;
  attempt_num: number;
  status: AttemptStatus;
  grade_message: string | null;
  duration_ms: number | null;
  step_count: number | null;
  artifact_dir: string;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobCounts {
  queued: number;
  running: number;
  passed: number;
  failed: number;
  error: number;
}

export interface JobSummary {
  job: Job;
  counts: JobCounts;
  status: JobStatus;
}

export interface JobWithAttempts {
  job: Job;
  counts: JobCounts;
  status: JobStatus;
  attempts: Attempt[];
}

export interface GradeResponse {
  passed: boolean | null;
  message: string | null;
  details: {
    expected?: unknown;
    actual?: unknown;
    [k: string]: unknown;
  };
  task?: { id: string; task: string; answer: string };
  final_reasoning?: string;
}

export type TrajectoryEvent =
  | {
      ts: string;
      seq: number;
      kind: "task_start";
      data: { task_id: string; model: string; base_url: string; prompt: string };
    }
  | {
      ts: string;
      seq: number;
      kind: "action";
      data: { name: string; args: Record<string, unknown> };
    }
  | {
      ts: string;
      seq: number;
      kind: "observation";
      data: { screenshot: string; url: string; step: number };
    }
  | {
      ts: string;
      seq: number;
      kind: "final_answer";
      data: { text: string };
    }
  | {
      ts: string;
      seq: number;
      kind: "grade";
      data: { passed: boolean; message: string };
    }
  | { ts: string; seq: number; kind: string; data: Record<string, unknown> };

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  listJobs: () => getJson<JobSummary[]>("/api/jobs"),
  getJob: (id: string) => getJson<JobWithAttempts>(`/api/jobs/${id}`),
  getAttempt: (id: string) => getJson<Attempt>(`/api/attempts/${id}`),
  getGrade: (id: string) => getJson<GradeResponse>(`/api/attempts/${id}/grade`),
  // trajectory is JSONL; we parse client-side.
  getTrajectory: async (id: string): Promise<TrajectoryEvent[]> => {
    const r = await fetch(`${API_BASE}/api/attempts/${id}/trajectory`, {
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`trajectory -> ${r.status}`);
    const text = await r.text();
    if (!text.trim()) return [];
    return text
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as TrajectoryEvent);
  },
  videoUrl: (id: string) => `${API_BASE}/api/attempts/${id}/video`,
  screenshotUrl: (id: string, n: number) =>
    `${API_BASE}/api/attempts/${id}/screenshots/${n}`,
  createJob: async (
    tasksFile: File,
    attemptsPerProblem: number,
    name: string,
  ): Promise<{ job_id: string; attempts_created: number }> => {
    const fd = new FormData();
    fd.append("tasks_json", tasksFile);
    fd.append("attempts_per_problem", String(attemptsPerProblem));
    if (name) fd.append("name", name);
    const r = await fetch(`${API_BASE}/api/jobs`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`create job ${r.status}: ${body}`);
    }
    return r.json();
  },
};
