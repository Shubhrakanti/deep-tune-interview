"""SQLite metadata layer for jobs + attempts.

A single file (default `jobs.db` at the repo root) in WAL mode is plenty for
M2's scale (3 concurrent rollouts, a few writes per second). We open a fresh
connection per call to keep things thread-safe without juggling thread-local
state — SQLite connection open is microseconds.

The worker is the only writer; the FastAPI request handlers are readers. WAL
mode lets readers proceed without blocking on writes.

Job status is derived from attempt statuses on read (no rollup column to keep
in sync). This is the single biggest correctness simplification in this file.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from backend.models import (
    Attempt,
    AttemptStatus,
    Job,
    JobCounts,
    JobStatus,
    JobSummary,
    JobWithAttempts,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id                    TEXT PRIMARY KEY,
  name                  TEXT,
  tasks_file_path       TEXT NOT NULL,
  attempts_per_problem  INTEGER NOT NULL,
  created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
  id                TEXT PRIMARY KEY,
  job_id            TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  problem_id        TEXT NOT NULL,
  attempt_num       INTEGER NOT NULL,
  status            TEXT NOT NULL,
  grade_message     TEXT,
  duration_ms       INTEGER,
  step_count        INTEGER,
  artifact_dir      TEXT NOT NULL,
  error_message     TEXT,
  created_at        TEXT NOT NULL,
  started_at        TEXT,
  completed_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_job_status ON attempts(job_id, status);
CREATE INDEX IF NOT EXISTS idx_attempts_status     ON attempts(status);
"""


def _now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that is GUARANTEED to be closed on exit.

        IMPORTANT: do not replace this with a plain `sqlite3.connect()` and
        `with conn:` — sqlite3.Connection's __exit__ only commits/rolls back
        the transaction; it does NOT close the connection. Forgetting to close
        leaks an FD per call and eventually wedges WAL mode.
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _bootstrap(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(SCHEMA)

    # ----- writes ----------------------------------------------------------

    def insert_job(
        self,
        name: Optional[str],
        tasks_file_path: str,
        attempts_per_problem: int,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            name=name,
            tasks_file_path=tasks_file_path,
            attempts_per_problem=attempts_per_problem,
            created_at=_now(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, name, tasks_file_path, attempts_per_problem, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.name,
                    job.tasks_file_path,
                    job.attempts_per_problem,
                    job.created_at,
                ),
            )
        return job

    def enqueue_attempts(
        self,
        job_id: str,
        problem_ids: list[str],
        attempts_per_problem: int,
        runs_root: Path,
    ) -> list[Attempt]:
        """Create N x M attempt rows for a job; returns the inserted rows.

        artifact_dir is set to runs_root/<job_id>/<attempt_id>/, which is what
        the worker passes as --runs-dir + --run-name to the runner.
        """
        attempts: list[Attempt] = []
        now = _now()
        rows = []
        for problem_id in problem_ids:
            for n in range(1, attempts_per_problem + 1):
                aid = uuid.uuid4().hex
                artifact_dir = str(runs_root / job_id / aid)
                att = Attempt(
                    id=aid,
                    job_id=job_id,
                    problem_id=problem_id,
                    attempt_num=n,
                    status="queued",
                    artifact_dir=artifact_dir,
                    created_at=now,
                )
                attempts.append(att)
                rows.append(
                    (
                        att.id,
                        att.job_id,
                        att.problem_id,
                        att.attempt_num,
                        att.status,
                        att.artifact_dir,
                        att.created_at,
                    )
                )
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO attempts (id, job_id, problem_id, attempt_num, status, "
                "artifact_dir, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return attempts

    def claim_next_queued(self) -> Optional[Attempt]:
        """Atomically pick one queued attempt and mark it 'running'.

        Uses BEGIN IMMEDIATE so a second worker (if we ever add one) can't
        claim the same row. Returns None if nothing is queued.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM attempts WHERE status='queued' "
                "ORDER BY created_at, attempt_num LIMIT 1"
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            started_at = _now()
            conn.execute(
                "UPDATE attempts SET status='running', started_at=? "
                "WHERE id=? AND status='queued'",
                (started_at, row["id"]),
            )
            conn.execute("COMMIT")
            d = dict(row)
            d["status"] = "running"
            d["started_at"] = started_at
            return Attempt(**d)

    def mark_finished(
        self,
        attempt_id: str,
        status: AttemptStatus,
        grade_message: Optional[str],
        duration_ms: Optional[int],
        step_count: Optional[int],
        error_message: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE attempts SET status=?, grade_message=?, duration_ms=?, "
                "step_count=?, error_message=?, completed_at=? WHERE id=?",
                (
                    status,
                    grade_message,
                    duration_ms,
                    step_count,
                    error_message,
                    _now(),
                    attempt_id,
                ),
            )

    def reconcile_on_startup(self) -> int:
        """Mark any stranded 'running' attempts as 'error'.

        Called from worker_loop startup. Their docker compose projects may
        still be running, but `make clean-runs` (or the user) can clean those.
        Returns the number of rows reconciled.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE attempts SET status='error', "
                "error_message='worker restart while running', "
                "completed_at=? WHERE status='running'",
                (_now(),),
            )
            return cur.rowcount or 0

    # ----- reads -----------------------------------------------------------

    def list_jobs(self) -> list[JobSummary]:
        with self._connect() as conn:
            jobs = [
                Job(**dict(r))
                for r in conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC"
                ).fetchall()
            ]
            counts_by_job = self._counts_by_job(conn)
        return [
            JobSummary(
                job=j,
                counts=counts_by_job.get(j.id, JobCounts()),
                status=_job_status(counts_by_job.get(j.id, JobCounts())),
            )
            for j in jobs
        ]

    def get_job_with_attempts(self, job_id: str) -> Optional[JobWithAttempts]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                return None
            job = Job(**dict(row))
            attempts = [
                Attempt(**dict(r))
                for r in conn.execute(
                    "SELECT * FROM attempts WHERE job_id=? "
                    "ORDER BY problem_id, attempt_num",
                    (job_id,),
                ).fetchall()
            ]
            counts = self._counts_by_job(conn).get(job_id, JobCounts())
        return JobWithAttempts(
            job=job,
            attempts=attempts,
            counts=counts,
            status=_job_status(counts),
        )

    def get_attempt(self, attempt_id: str) -> Optional[Attempt]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()
        return Attempt(**dict(row)) if row else None

    def _counts_by_job(self, conn: sqlite3.Connection) -> dict[str, JobCounts]:
        out: dict[str, JobCounts] = {}
        for r in conn.execute(
            "SELECT job_id, status, COUNT(*) AS n FROM attempts GROUP BY job_id, status"
        ).fetchall():
            c = out.setdefault(r["job_id"], JobCounts())
            setattr(c, r["status"], r["n"])
        return out


def _job_status(counts: JobCounts) -> JobStatus:
    if counts.total == 0:
        return "queued"
    if counts.running > 0 or counts.queued > 0:
        return "running" if counts.running > 0 or counts.terminal > 0 else "queued"
    return "done"
