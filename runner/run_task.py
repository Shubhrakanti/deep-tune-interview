"""Single-task runner for Milestone 1.

Each invocation:
  1. picks a unique compose project name + a free host port
  2. boots a fresh Postgres + Metabase via `docker compose -p <project> up -d`
  3. waits for Metabase to report healthy on the dynamic port
  4. runs google-gemini/computer-use-preview verbatim against that Metabase
  5. grades the agent's final JSON answer against tasks.json[*].answer
  6. ALWAYS tears the project down (`down -v`) in a finally block, even on
     Ctrl+C or crash — every run gets a clean environment.

Upstream BrowserAgent + PlaywrightComputer are imported as-is from
vendor/computer-use-preview (see sys.path setup below).

Example:

    export GEMINI_API_KEY=...
    python -m runner.run_task --task-id problem1
"""

from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Make the vendored upstream importable. Its top-level layout is:
#   vendor/computer-use-preview/
#     agent.py              -> exports BrowserAgent
#     computers/__init__.py -> exports PlaywrightComputer, BrowserbaseComputer
# We import from submodules directly (skipping computers/__init__.py) so we
# don't pull in the optional `browserbase` dependency.
REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR = REPO_ROOT / "vendor" / "computer-use-preview"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from agent import BrowserAgent  # noqa: E402  (vendor/computer-use-preview/agent.py)
from computers.playwright.playwright import PlaywrightComputer  # noqa: E402

from grading.json_match import JsonMatchGrader  # noqa: E402

DEFAULT_TASKS = REPO_ROOT / "tasks.json"
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"
DEFAULT_MODEL = "gemini-2.5-computer-use-preview-10-2025"

# Upstream's main.py uses (1440, 900); same here so the model sees the same
# coordinate space it was trained against.
SCREEN_SIZE = (1440, 900)

# Login creds embedded in metabase_envdata.sql (see Instructions.md).
METABASE_EMAIL = "daksh@deeptune.com"
METABASE_PASSWORD = "Daksh@123"

# Time we'll wait for Metabase /api/health to return 200 after `compose up`.
# Cold boot against a freshly-restored Postgres typically lands in 60-90s; the
# 4-minute cap is for slow first-pull machines.
METABASE_HEALTH_TIMEOUT_S = 240


# ---------------------------------------------------------------------------
# Per-task env lifecycle
# ---------------------------------------------------------------------------


def pick_free_port() -> int:
    """Ask the kernel for a currently-unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def project_name(task_id: str, ts: str) -> str:
    """Build a compose project name. Compose only accepts [a-z0-9-]."""
    raw = f"dt-m1-{task_id}-{ts}".lower()
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")


def compose_up(project: str, port: int) -> None:
    env = {**os.environ, "METABASE_HOST_PORT": str(port)}
    subprocess.run(
        ["docker", "compose", "-p", project, "up", "-d"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def compose_down(project: str) -> None:
    """Tear down. Never raises — we call this from finally / atexit."""
    subprocess.run(
        ["docker", "compose", "-p", project, "down", "-v"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )


def wait_metabase_healthy(
    base_url: str, timeout_s: int = METABASE_HEALTH_TIMEOUT_S
) -> None:
    health_url = f"{base_url}/api/health"
    deadline = time.monotonic() + timeout_s
    last_err: Optional[str] = None
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(health_url, timeout=3) as r:
                if r.status == 200:
                    print(f"[env] Metabase healthy after {attempt} attempts")
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = repr(e)
        if attempt % 10 == 0:
            print(f"[env] still waiting on {health_url} (attempt {attempt}): {last_err}")
        time.sleep(3)
    raise RuntimeError(
        f"Metabase at {health_url} did not become healthy within {timeout_s}s; "
        f"last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# Task loading + prompt building
# ---------------------------------------------------------------------------


def load_task(tasks_file: Path, task_id: str) -> dict:
    with tasks_file.open() as f:
        tasks = json.load(f)
    for t in tasks:
        if t.get("id") == task_id:
            return t
    available = [t.get("id") for t in tasks]
    raise SystemExit(f"task '{task_id}' not in {tasks_file}; available: {available}")


def build_prompt(task: dict, base_url: str) -> str:
    # Mirrors the spirit of apps/metabase/src/app.py::get_prompt from gym:
    # tell the agent where Metabase is, hand it creds, and pin the output
    # format so the JSON grader has something to match on.
    expected_schema = task["answer"]
    return f"""You are an analyst using Metabase to answer a data question.

App: Metabase at {base_url}
Login email: {METABASE_EMAIL}
Password: {METABASE_PASSWORD}

Task:
{task["task"]}

Rules:
- If you see the login page, log in with the credentials above.
- Use the Metabase UI to find the answer (Browse data, build a question,
  or the SQL editor — whichever is fastest). The "Sample Database" data
  source is already configured.
- When you have the final answer, your LAST message must be a single JSON
  object and NOTHING ELSE — no prose, no markdown fences. It must match
  the exact key names and value types in this example:
{expected_schema}
"""


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(
    task_id: str,
    tasks_file: Path,
    runs_dir: Path,
    model: str,
    headless: bool,
    highlight_mouse: bool,
) -> int:
    if "GEMINI_API_KEY" not in os.environ:
        print("error: GEMINI_API_KEY env var is required", file=sys.stderr)
        return 2

    task = load_task(tasks_file, task_id)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs_dir / f"{task_id}-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    project = project_name(task_id, ts)
    port = pick_free_port()
    base_url = f"http://localhost:{port}"
    print(f"[env] project={project} port={port}")

    # Best-effort teardown if the process gets killed before the finally clause
    # runs (SIGTERM, parent shell death, etc.). atexit takes care of normal
    # exits and SIGINT-triggered KeyboardInterrupt; an explicit SIGTERM handler
    # covers `docker compose down` from a sibling shell, kubectl-style stops,
    # etc.
    atexit.register(compose_down, project)
    _install_sigterm_handler(project)

    prompt = build_prompt(task, base_url)
    (run_dir / "prompt.txt").write_text(prompt)

    # Upstream PlaywrightComputer reads PLAYWRIGHT_HEADLESS from env; set it
    # before instantiation so --headless / --headed are honored.
    os.environ["PLAYWRIGHT_HEADLESS"] = "1" if headless else ""

    grade = None
    final_text = ""
    try:
        print(f"[env] docker compose -p {project} up -d")
        compose_up(project, port)
        print(f"[env] waiting for Metabase at {base_url}/api/health (cold boot ~60-90s)")
        wait_metabase_healthy(base_url)

        env = PlaywrightComputer(
            screen_size=SCREEN_SIZE,
            initial_url=base_url,
            highlight_mouse=highlight_mouse,
        )
        with env as browser_computer:
            agent = BrowserAgent(
                browser_computer=browser_computer,
                query=prompt,
                model_name=model,
            )
            agent.agent_loop()

        final_text = agent.final_reasoning or ""
        grade = JsonMatchGrader().grade(task, final_text)
    finally:
        print(f"[env] docker compose -p {project} down -v")
        compose_down(project)

    grade_payload = (
        {
            "passed": grade.passed,
            "message": grade.message,
            "details": grade.details,
        }
        if grade is not None
        else {"passed": False, "message": "no grade (env or agent failure)", "details": {}}
    )
    run_payload = {
        "task_id": task_id,
        "task": task,
        "model": model,
        "project": project,
        "base_url": base_url,
        "final_reasoning": final_text,
        "grade": grade_payload,
    }
    (run_dir / "run.json").write_text(json.dumps(run_payload, indent=2, default=str))

    if grade is None:
        print("[result] ERROR — environment never produced a grade")
        return 1
    status = "PASS" if grade.passed else "FAIL"
    print(f"[result] {status} — {grade.message}")
    if not grade.passed:
        print(f"  expected: {grade.details.get('expected')!r}")
        print(f"  actual:   {grade.details.get('actual')!r}")
    return 0 if grade.passed else 1


def _install_sigterm_handler(project: str) -> None:
    def _handler(signum, frame):  # noqa: ARG001
        print(f"[env] signal {signum} received; tearing down {project}", flush=True)
        compose_down(project)
        # Re-raise the default behavior for the signal so the process actually
        # exits (otherwise the SIGTERM gets swallowed).
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, _handler)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one Metabase task end-to-end.")
    p.add_argument("--task-id", required=True, help="ID from tasks.json (e.g. problem1)")
    p.add_argument("--task-file", type=Path, default=DEFAULT_TASKS)
    p.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    p.add_argument("--model", default=DEFAULT_MODEL)
    headless = p.add_mutually_exclusive_group()
    headless.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        default=False,
        help="Run Chromium with a visible window (default).",
    )
    headless.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run Chromium without a visible window.",
    )
    p.add_argument(
        "--highlight-mouse",
        action="store_true",
        help="Draw the mouse cursor position in the page for debugging.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    return run(
        task_id=args.task_id,
        tasks_file=args.task_file,
        runs_dir=args.runs_dir,
        model=args.model,
        headless=args.headless,
        highlight_mouse=args.highlight_mouse,
    )


if __name__ == "__main__":
    sys.exit(main())
