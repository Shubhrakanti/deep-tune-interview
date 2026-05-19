"""FastAPI app entrypoint.

Single process, two concerns:
  - HTTP API (/api/*) serving the Next.js dashboard at http://localhost:3001
  - Asyncio worker loop polling SQLite for queued attempts and shelling out to
    `python -m runner.run_task` for each one (max 3 concurrent).

Start with:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import Database
from backend.routes import build_router
from backend.worker import worker_loop

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("M2_DB_PATH", REPO_ROOT / "jobs.db"))
RUNS_ROOT = Path(os.environ.get("M2_RUNS_ROOT", REPO_ROOT / "runs"))

# Honored at the time the worker spawns; default 3 per the M2 plan.
MAX_PARALLEL = int(os.environ.get("M2_MAX_PARALLEL", "3"))

# How long to give the worker to drain in-flight attempts on shutdown before
# we escalate from `stop_event` to `task.cancel()`.
SHUTDOWN_TIMEOUT_S = float(os.environ.get("M2_SHUTDOWN_TIMEOUT_S", "30"))

# Browsers from which the API will accept requests. Next.js dev defaults to
# 3000 but we move it to 3001 so it doesn't collide with M1's standalone
# `make up` Metabase on :3000.
CORS_ORIGINS = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resources (db handle, runs dir) are created once in `create_app()` and
    # stashed on `app.state`. Lifespan only owns the background worker task,
    # which is the only thing here that actually needs start/stop semantics.
    db: Database = app.state.db
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        worker_loop(db, max_parallel=MAX_PARALLEL, stop_event=stop_event),
        name="worker_loop",
    )
    app.state.worker_task = worker_task
    app.state.stop_event = stop_event
    logger.info("startup complete; worker_loop running (max_parallel=%d)", MAX_PARALLEL)
    try:
        yield
    finally:
        logger.info("shutdown: signaling worker_loop to stop")
        stop_event.set()
        try:
            # Give the worker a chance to drain in-flight attempts cleanly.
            # `wait_for` will cancel the task on timeout and await its cleanup.
            await asyncio.wait_for(worker_task, timeout=SHUTDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(
                "worker_loop did not stop within %.1fs; force cancelled",
                SHUTDOWN_TIMEOUT_S,
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("worker_loop raised during shutdown")
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(title="DeepTune RL — M2", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    app.state.db = db
    app.state.runs_root = RUNS_ROOT
    app.include_router(build_router(db, RUNS_ROOT))

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "db_path": str(DB_PATH),
            "runs_root": str(RUNS_ROOT),
            "max_parallel": MAX_PARALLEL,
        }

    return app


app = create_app()
