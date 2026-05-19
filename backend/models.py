"""Pydantic models for jobs + attempts.

Used by the FastAPI routes (request/response validation), the worker (DB row
hydration), and indirectly the frontend (typescript types are kept in sync by
hand — there are only ~6 fields per model).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

AttemptStatus = Literal["queued", "running", "passed", "failed", "error"]
JobStatus = Literal["queued", "running", "done"]


class Job(BaseModel):
    id: str
    name: Optional[str] = None
    tasks_file_path: str
    attempts_per_problem: int
    created_at: str


class Attempt(BaseModel):
    id: str
    job_id: str
    problem_id: str
    attempt_num: int
    status: AttemptStatus
    grade_message: Optional[str] = None
    duration_ms: Optional[int] = None
    step_count: Optional[int] = None
    artifact_dir: str
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobCounts(BaseModel):
    queued: int = 0
    running: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0

    @property
    def total(self) -> int:
        return self.queued + self.running + self.passed + self.failed + self.error

    @property
    def terminal(self) -> int:
        return self.passed + self.failed + self.error


class JobSummary(BaseModel):
    job: Job
    counts: JobCounts
    status: JobStatus


class JobWithAttempts(BaseModel):
    job: Job
    counts: JobCounts
    status: JobStatus
    attempts: list[Attempt]


class CreateJobResponse(BaseModel):
    job_id: str
    attempts_created: int
