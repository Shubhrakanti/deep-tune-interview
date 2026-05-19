"""Asyncio worker that turns queued attempts into rollouts.

Lifecycle:
  1. On startup, `Database.reconcile_on_startup()` marks any 'running' attempts
     (e.g. left stranded by a previous worker crash) as 'error'.
  2. Worker loop polls the DB every second for queued attempts and creates an
     asyncio task per claim, capped at MAX_PARALLEL via a semaphore.
  3. Each task asks the configured `Launcher` to actually run the attempt and
     then reads the runner's `run.json` to derive grade + metrics.

The `Launcher` protocol exists so M3 can swap SubprocessLauncher for a Docker-
or Modal- based launcher without changing the worker. Only SubprocessLauncher
is wired up for M2; the other two raise NotImplementedError.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional, Protocol

from backend.db import Database
from backend.models import Attempt, AttemptStatus

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_PARALLEL = int(os.environ.get("M2_MAX_PARALLEL", "3"))
POLL_INTERVAL_S = 1.0


class LaunchResult:
    def __init__(
        self,
        returncode: int,
        status: AttemptStatus,
        grade_message: Optional[str],
        duration_ms: Optional[int],
        step_count: Optional[int],
        error_message: Optional[str] = None,
    ):
        self.returncode = returncode
        self.status = status
        self.grade_message = grade_message
        self.duration_ms = duration_ms
        self.step_count = step_count
        self.error_message = error_message


class Launcher(Protocol):
    async def launch(self, attempt: Attempt, tasks_file_path: str) -> LaunchResult: ...


def _parse_run_json(artifact_dir: Path, returncode: int) -> LaunchResult:
    """Read the runner's run.json + metrics.json and derive the final status.

    The runner writes both even on partial failure, so this is safe to call
    regardless of return code. If neither file exists, we infer an error.
    """
    run_path = artifact_dir / "run.json"
    metrics_path = artifact_dir / "metrics.json"
    grade_passed: Optional[bool] = None
    grade_message: Optional[str] = None
    step_count: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None

    if metrics_path.exists():
        try:
            m = json.loads(metrics_path.read_text())
            step_count = m.get("step_count")
            duration_ms = m.get("duration_ms")
        except Exception as e:
            error_message = f"metrics.json parse failed: {e}"
    if run_path.exists():
        try:
            r = json.loads(run_path.read_text())
            grade = r.get("grade", {}) or {}
            grade_passed = grade.get("passed")
            grade_message = grade.get("message")
            if step_count is None:
                step_count = r.get("step_count")
            if duration_ms is None:
                duration_ms = r.get("duration_ms")
        except Exception as e:
            error_message = f"run.json parse failed: {e}"
    else:
        error_message = error_message or "no run.json produced (runner crashed before writing)"

    if grade_passed is True:
        status: AttemptStatus = "passed"
    elif grade_passed is False:
        status = "failed"
    else:
        status = "error"
    return LaunchResult(
        returncode=returncode,
        status=status,
        grade_message=grade_message,
        duration_ms=duration_ms,
        step_count=step_count,
        error_message=error_message,
    )


class SubprocessLauncher:
    """Run an attempt by shelling out to `python -m runner.run_task` on the host.

    The runner already owns full env lifecycle (compose up/down on a random
    port, unique project name, finally + atexit + SIGTERM teardown), so the
    worker doesn't need to know about Docker at all.
    """

    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root

    async def launch(self, attempt: Attempt, tasks_file_path: str) -> LaunchResult:
        artifact_dir = Path(attempt.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        runs_root = artifact_dir.parent
        run_name = artifact_dir.name

        stdout_log = open(artifact_dir / "stdout.log", "wb")
        stderr_log = open(artifact_dir / "stderr.log", "wb")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "runner.run_task",
                "--task-id",
                attempt.problem_id,
                "--task-file",
                tasks_file_path,
                "--runs-dir",
                str(runs_root),
                "--run-name",
                run_name,
                "--headless",
                cwd=str(self.repo_root),
                env={**os.environ},
                stdout=stdout_log,
                stderr=stderr_log,
            )
            rc = await proc.wait()
        finally:
            stdout_log.close()
            stderr_log.close()
        return _parse_run_json(artifact_dir, rc)


class DockerLauncher:
    """M3 stub: `docker run agent:latest ...`. Image built from Dockerfile.agent."""

    async def launch(self, attempt: Attempt, tasks_file_path: str) -> LaunchResult:
        raise NotImplementedError("DockerLauncher: wire up in M3")


class ModalLauncher:
    """M3 stub: spawn each attempt as a Modal function call."""

    async def launch(self, attempt: Attempt, tasks_file_path: str) -> LaunchResult:
        raise NotImplementedError("ModalLauncher: wire up in M3")


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


async def _run_one(db: Database, launcher: Launcher, attempt: Attempt) -> None:
    """Run a single claimed attempt and update its row."""
    job = db.get_job_with_attempts(attempt.job_id)
    if job is None:
        db.mark_finished(
            attempt.id,
            status="error",
            grade_message=None,
            duration_ms=None,
            step_count=None,
            error_message="parent job vanished",
        )
        return
    tasks_file_path = job.job.tasks_file_path
    print(
        f"[worker] starting attempt {attempt.id[:8]} "
        f"job={attempt.job_id[:8]} problem={attempt.problem_id} "
        f"attempt_num={attempt.attempt_num}",
        flush=True,
    )
    try:
        result = await launcher.launch(attempt, tasks_file_path)
    except Exception as e:
        print(f"[worker] attempt {attempt.id[:8]} launcher raised: {e}", flush=True)
        db.mark_finished(
            attempt.id,
            status="error",
            grade_message=None,
            duration_ms=None,
            step_count=None,
            error_message=f"launcher exception: {e}",
        )
        return
    db.mark_finished(
        attempt.id,
        status=result.status,
        grade_message=result.grade_message,
        duration_ms=result.duration_ms,
        step_count=result.step_count,
        error_message=result.error_message,
    )
    print(
        f"[worker] finished attempt {attempt.id[:8]} status={result.status} "
        f"grade={result.grade_message!r} duration_ms={result.duration_ms}",
        flush=True,
    )


async def worker_loop(
    db: Database,
    launcher: Optional[Launcher] = None,
    max_parallel: int = MAX_PARALLEL,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Main worker loop. Cancellable via cancellation of the parent task or
    via `stop_event.set()`."""
    launcher = launcher or SubprocessLauncher()
    reconciled = db.reconcile_on_startup()
    if reconciled:
        print(f"[worker] reconciled {reconciled} stranded attempt(s)", flush=True)
    sem = asyncio.Semaphore(max_parallel)
    in_flight: set[asyncio.Task] = set()
    print(
        f"[worker] running (max_parallel={max_parallel}, launcher={type(launcher).__name__})",
        flush=True,
    )

    async def _spawn(att: Attempt) -> None:
        async with sem:
            await _run_one(db, launcher, att)

    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            attempt = db.claim_next_queued()
            if attempt is None:
                await asyncio.sleep(POLL_INTERVAL_S)
                # Reap completed tasks so we don't leak references.
                in_flight = {t for t in in_flight if not t.done()}
                continue
            task = asyncio.create_task(_spawn(attempt))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)
    finally:
        # Drain on shutdown so we don't leave attempt rows in 'running'.
        if in_flight:
            print(f"[worker] draining {len(in_flight)} in-flight attempt(s)", flush=True)
            await asyncio.gather(*in_flight, return_exceptions=True)
