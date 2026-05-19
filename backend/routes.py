"""HTTP routes for jobs + attempts.

All endpoints live under /api/. Conventions:
  - Read-only routes load data from SQLite or from the per-attempt artifact
    directory on disk (run.json, trajectory.jsonl, video.webm, screenshots/).
  - Bulky artifacts (video, screenshots) are served via StreamingResponse /
    FileResponse so we don't load them into Python memory.
  - POST /jobs validates the uploaded tasks.json shape, copies it under
    runs/<job_id>/tasks.json, and enqueues N x M attempts. The worker (in the
    same process) picks them up automatically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from backend.db import Database
from backend.models import (
    Attempt,
    CreateJobResponse,
    JobSummary,
    JobWithAttempts,
)


def build_router(db: Database, runs_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api")

    # ----- jobs --------------------------------------------------------

    @router.post("/jobs", response_model=CreateJobResponse)
    async def create_job(
        tasks_json: UploadFile = File(...),
        attempts_per_problem: int = Form(...),
        name: Optional[str] = Form(None),
    ) -> CreateJobResponse:
        if attempts_per_problem < 1:
            raise HTTPException(400, "attempts_per_problem must be >= 1")
        raw = await tasks_json.read()
        try:
            tasks = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"uploaded file is not valid JSON: {e}")
        if not isinstance(tasks, list) or not tasks:
            raise HTTPException(400, "tasks.json must be a non-empty JSON array")
        problem_ids: list[str] = []
        for i, t in enumerate(tasks):
            if (
                not isinstance(t, dict)
                or "id" not in t
                or "task" not in t
                or "answer" not in t
            ):
                raise HTTPException(
                    400,
                    f"task {i} must be an object with keys id/task/answer",
                )
            problem_ids.append(str(t["id"]))

        # Create the job row first so we have an id, then freeze a copy of
        # the uploaded file under runs/<job_id>/tasks.json. We store the
        # absolute path on disk in tasks_file_path so the worker (spawned
        # later) doesn't depend on cwd.
        job_id_placeholder = "_"
        job = db.insert_job(
            name=name,
            tasks_file_path=job_id_placeholder,
            attempts_per_problem=attempts_per_problem,
        )
        job_dir = (runs_root / job.id).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        tasks_file = job_dir / "tasks.json"
        tasks_file.write_bytes(raw)

        # Update the stored path now that we have the final location.
        with db._connect() as conn:
            conn.execute(
                "UPDATE jobs SET tasks_file_path=? WHERE id=?",
                (str(tasks_file), job.id),
            )
        attempts = db.enqueue_attempts(
            job.id, problem_ids, attempts_per_problem, runs_root
        )
        return CreateJobResponse(job_id=job.id, attempts_created=len(attempts))

    @router.get("/jobs", response_model=list[JobSummary])
    def list_jobs() -> list[JobSummary]:
        return db.list_jobs()

    @router.get("/jobs/{job_id}", response_model=JobWithAttempts)
    def get_job(job_id: str) -> JobWithAttempts:
        out = db.get_job_with_attempts(job_id)
        if out is None:
            raise HTTPException(404, "job not found")
        return out

    # ----- attempts ----------------------------------------------------

    def _load_attempt(attempt_id: str) -> Attempt:
        att = db.get_attempt(attempt_id)
        if att is None:
            raise HTTPException(404, "attempt not found")
        return att

    def _artifact_path(attempt_id: str, *parts: str) -> Path:
        att = _load_attempt(attempt_id)
        p = Path(att.artifact_dir, *parts).resolve()
        # Path-traversal guard: every artifact must live under runs_root.
        root = runs_root.resolve()
        if root not in p.parents and p != root:
            raise HTTPException(403, "path outside runs root")
        return p

    @router.get("/attempts/{attempt_id}", response_model=Attempt)
    def get_attempt(attempt_id: str) -> Attempt:
        return _load_attempt(attempt_id)

    @router.get("/attempts/{attempt_id}/trajectory")
    def get_trajectory(attempt_id: str) -> Response:
        p = _artifact_path(attempt_id, "trajectory.jsonl")
        if not p.exists():
            return Response(content="", media_type="application/x-ndjson")
        return FileResponse(p, media_type="application/x-ndjson")

    @router.get("/attempts/{attempt_id}/messages")
    def get_messages(attempt_id: str) -> Response:
        p = _artifact_path(attempt_id, "messages.json")
        if not p.exists():
            return JSONResponse([])
        return FileResponse(p, media_type="application/json")

    @router.get("/attempts/{attempt_id}/grade")
    def get_grade(attempt_id: str) -> Response:
        # grade lives inside run.json; pull just the grade subtree.
        p = _artifact_path(attempt_id, "run.json")
        if not p.exists():
            return JSONResponse(
                {"passed": None, "message": "no run.json yet", "details": {}}
            )
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise HTTPException(500, f"run.json malformed: {e}")
        return JSONResponse(
            {
                "passed": data.get("grade", {}).get("passed"),
                "message": data.get("grade", {}).get("message"),
                "details": data.get("grade", {}).get("details", {}),
                "task": data.get("task"),
                "final_reasoning": data.get("final_reasoning"),
            }
        )

    @router.get("/attempts/{attempt_id}/video")
    def get_video(attempt_id: str, request: Request) -> Response:
        p = _artifact_path(attempt_id, "video.webm")
        if not p.exists():
            raise HTTPException(404, "video not produced yet")
        return _range_response(p, request, "video/webm")

    @router.get("/attempts/{attempt_id}/screenshots/{n}")
    def get_screenshot(attempt_id: str, n: int) -> FileResponse:
        p = _artifact_path(attempt_id, "screenshots", f"step_{n:04d}.png")
        if not p.exists():
            raise HTTPException(404, f"screenshot step_{n:04d}.png not found")
        return FileResponse(p, media_type="image/png")

    return router


# ---------------------------------------------------------------------------
# HTTP Range helper for <video> seeking
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _range_response(path: Path, request: Request, media_type: str) -> Response:
    """Serve a file with optional `Range: bytes=...` support for media playback.

    Browsers issue Range requests on <video src>; serving 206 Partial Content
    enables seeking. If no Range header is present, fall through to FileResponse.
    """
    range_header = request.headers.get("range") or request.headers.get("Range")
    file_size = path.stat().st_size
    if not range_header:
        return FileResponse(path, media_type=media_type)
    m = _RANGE_RE.match(range_header.strip())
    if not m:
        return FileResponse(path, media_type=media_type)
    start_s, end_s = m.group(1), m.group(2)
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    length = end - start + 1

    def _iter():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk = 64 * 1024
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        _iter(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )
