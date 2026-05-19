# Metabase RL Environment — Milestones 1 & 2

A local, single-machine MVP of a computer-use RL environment for Metabase.

- **M1 — Env + agent + grader:** Metabase + Postgres in Docker Compose seeded from `metabase_envdata.sql`, the Gemini computer-use agent driving Playwright/Chromium, JSON-match grader. Every task run gets a fresh, ephemeral compose stack on a random port, torn down after the run.
- **M2 — Jobs/rollouts platform:** FastAPI + SQLite job queue, an asyncio worker that fans M1 runs out across 3 parallel slots, and a Next.js dashboard for submitting tasks.json files and reviewing per-attempt video + transcript + grade.

```
M1 = `make run TASK=problem1`            (one rollout, one terminal)
M2 = `make api` + `make web` + browser  (many rollouts, web UI)
```

## M1 — single task

- **Agent:** [google-gemini/computer-use-preview](https://github.com/google-gemini/computer-use-preview) used **verbatim** as a git submodule.
- **Browser:** local Chromium driven by Playwright (the upstream default).
- **Grader:** extracts the final JSON object from the agent's last message and compares it to `tasks.json[*].answer` with normalized matching.

## Architecture

```
+----------------------- host machine ---------------------------+
|                                                                |
|   python -m runner.run_task --task-id problem1                 |
|        |                                                       |
|        |  1. pick free port, build unique project name         |
|        |  2. docker compose -p <project> up -d                 |
|        |  3. wait for Metabase /api/health on dynamic port     |
|        |  4. run BrowserAgent (from vendor/computer-use-preview)|
|        |  5. JsonMatchGrader on agent.final_reasoning          |
|        |  6. docker compose -p <project> down -v  (finally)    |
|        |                                                       |
|   Chromium (Playwright)  <----- screenshots / actions -------- |
|        |                                                       |
+--------|-------------------------------------------------------+
         |
         | http://localhost:<random-port>
         v
+----------------- docker compose project: dt-m1-... -+
|  metabase  ->  postgres (root_db, seeded)           |
+-----------------------------------------------------+
       (lives only for the duration of one task)
```

## One-time setup

```bash
# 1) Clone WITH submodules (pulls vendor/computer-use-preview).
git clone --recurse-submodules <this repo>
cd deeptune-interview
# If you already cloned without --recurse-submodules:
git submodule update --init --recursive

# 2) Python venv + deps (matches upstream's requirements.txt exactly).
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) Install Chrome for Playwright.
playwright install-deps chrome   # may need sudo on Linux
playwright install chrome

# 4) Pre-pull the heavy Docker images so the first run isn't blocked on
#    a ~700 MB download mid-task.
make pull

# 5) Set your Gemini key (see Instructions.md for the one provided).
export GEMINI_API_KEY="..."
```

## Run a task

```bash
make run TASK=problem1
# or:
python -m runner.run_task --task-id problem1
```

That single command:

1. Generates a project name like `dt-m1-problem1-20260519t180000z` and a random free host port.
2. Boots a fresh Postgres + Metabase stack via `docker compose -p <project> up -d`.
3. Waits for Metabase to report healthy on the dynamic port (cold boot ~60–90s).
4. Hands control to the upstream Gemini Computer Use agent loop, pointed at `http://localhost:<port>`.
5. Grades the agent's final JSON answer against `tasks.json[*].answer`.
6. Tears the whole project down (`docker compose down -v`) — containers and the Postgres volume are deleted. **Every task run starts from a clean DB.**

Step 6 runs from a `finally` block plus a SIGTERM handler plus `atexit`, so the env is cleaned up even if the agent crashes, you hit Ctrl+C, or the OS sends a SIGTERM.

Optional flags:

- `--headless` — run Chromium without a visible window (default is headed so you can watch).
- `--highlight-mouse` — draw a red dot at each click coordinate (debugging).
- `--model gemini-3-flash-preview` — try a different Gemini model.
- `--task-file path/to/other-tasks.json` — override the default `tasks.json`.

Per-run artifacts land in `runs/<task_id>-<UTC-timestamp>/`:

```
runs/problem1-20260519T184257Z/
├── prompt.txt          # the exact query handed to the agent
├── run.json            # task, project, base_url, final reasoning, grade
├── trajectory.jsonl    # M2: one event per action/observation/grade (NDJSON)
├── messages.json       # M2: full Gemini conversation (screenshots stripped)
├── metrics.json        # M2: step_count, duration_ms, model
├── video.webm          # M2: full Playwright session recording
└── screenshots/        # M2: one PNG per observation (step_NNNN.png)
```

These M2-only artifacts also show up for solo `make run TASK=…` invocations — the runner uses the recording computer either way.

## Stranded containers

If a run gets SIGKILL'd before its teardown can fire (e.g. `kill -9`), the
stack is left running. `make clean-runs` finds any compose project whose
name starts with `dt-m1-` and tears it down:

```bash
make clean-runs
```

## Manual exploration

Sometimes you want a long-lived Metabase to click around in (debugging the
seed dump, checking what the bundled Sample Database looks like, etc.).
The same `docker-compose.yml` works for that — just use the default project:

```bash
make up        # boots on port 3000
# ... browse http://localhost:3000 ...
make down      # stop, keep data volume
make reset     # stop, wipe volume, re-seed
```

This stack is *separate* from per-task runs (different project name) and
they don't conflict; per-task runs use random ports.

## Layout

```
deeptune-interview/
├── docker-compose.yml          # parametrized port; seed step is inline (pg_restore)
├── Dockerfile.agent            # M3 stub image for DockerLauncher
├── tasks.json                  # M1 tasks + expected answers
├── metabase_envdata.sql        # pg_dump -Fc of root_db (Metabase metadata)
├── Instructions.md             # original take-home brief
├── vendor/
│   └── computer-use-preview/   # git submodule, used verbatim
├── runner/
│   ├── run_task.py             # env up -> agent -> grade -> env down
│   └── recording_computer.py   # PlaywrightComputer wrapper: video + screenshots + trajectory.jsonl
├── grading/
│   ├── base.py                 # Grader protocol (slot for DB-diff later)
│   └── json_match.py           # normalized JSON-match grader
├── backend/                    # M2 FastAPI app + asyncio worker
│   ├── main.py                 # ASGI entrypoint + lifespan-owned worker task
│   ├── routes.py               # /api/jobs + /api/attempts/* HTTP routes
│   ├── worker.py               # poll SQLite -> SubprocessLauncher -> grade
│   ├── db.py                   # SQLite (WAL) access layer
│   └── models.py               # pydantic schemas shared by routes + worker
├── frontend/                   # M2 Next.js dashboard (app router, port 3001)
├── Makefile
└── requirements.txt
```

## Grading

`JsonMatchGrader` ([grading/json_match.py](grading/json_match.py)) extracts
the last balanced `{...}` block in the agent's final assistant text and
compares it to `task["answer"]` with these rules:

- strings: stripped + lowercased
- floats: rounded to 2 decimal places
- lists: sorted (order doesn't matter)
- dicts whose values are multiple equal-length lists (like
  `{product_titles: [...], ratings: [...]}`) are treated as parallel arrays:
  the row-pairing is preserved but the row order is not.

`grading/base.py` defines a `Grader` protocol so a future `db_diff.py`
(snapshotting `root_db` before/after, modeled on
`apps/metabase/src/app.py::snapshot_diff` in the gym) can be added in M2/M3
without changing the runner.

## Trade-offs (worth knowing)

- **Cold boot ~60–90s per task.** Each task pays for a fresh Metabase init
  against a freshly-restored Postgres. Acceptable for M1; M2 can optimize
  via a warm pool or by baking the seeded DB into a custom image.
- **Concurrency is free.** Unique project + random port means two
  `runner.run_task` invocations can run in parallel on the same host
  without colliding.
- **Headed browsers stack up.** Each task opens its own Chromium window.
  For batch runs use `--headless`.

## What's intentionally not here

- No cloud (no Modal, Browserbase, or Harbor remote backends).
- No DB-state-diff grading wired up — interface only.

---

# M2 — Jobs / rollouts platform

```
+------------------------- host ----------------------------+
|                                                           |
|  Next.js  --fetch-->  FastAPI :8000                       |
|  :3001               (lifespan also runs an               |
|  (web UI)             asyncio worker, Semaphore(3))       |
|                            |                              |
|                            | for each queued attempt:     |
|                            |   asyncio.subprocess of      |
|                            |   `python -m runner.run_task`|
|                            v                              |
|  jobs.db (sqlite, WAL)  +  runs/<job>/<attempt>/          |
|       ^                       (run.json, video.webm,      |
|       |                        trajectory.jsonl,          |
|       |                        screenshots/, ...)         |
|       |                                                   |
|  reads <-> writes (worker is single writer)               |
+-----------------------------------------------------------+

each subprocess invokes its own ephemeral compose stack
(M1 design, unchanged), so attempts are fully isolated.
```

## Setup (one time)

In addition to the M1 setup above:

```bash
# Python deps (idempotent if already done)
source .venv/bin/activate
pip install -r requirements.txt

# Frontend deps
make web-install     # cd frontend && pnpm install
```

## Run M2

Two terminals:

```bash
# terminal 1
make api            # uvicorn backend.main:app --port 8000
                    # (use `make api-dev` for --reload while iterating on backend code;
                    #  --reload is off by default because watchfiles is flaky on Python 3.14)

# terminal 2
make web            # cd frontend && pnpm dev  (Next.js on :3001)
```

Then open <http://localhost:3001>:

1. **Jobs list (`/`)** — table of all submitted jobs, auto-refreshes every 3s while any job is running.
2. **New job (`/jobs/new`)** — upload a `tasks.json` file, pick attempts-per-problem, optional name. Redirects to the job detail page.
3. **Job detail (`/jobs/[id]`)** — attempts grouped by problem, each shown as a pill (`PASS`/`FAIL`/`RUN`/`QUE`/`ERR`); click any pill to drill into the attempt.
4. **Attempt detail (`/attempts/[id]`)** — header with grade + duration + step count, expected-vs-actual JSON diff, embedded `.webm` video, and the transcript stream (interleaved actions + thumbnail observations + final answer + grade).

Submitting `tasks.json` with 3 attempts per problem creates `10 × 3 = 30` rollouts. The worker runs up to 3 in parallel; each cold boot is ~60–90s, so the whole job takes roughly `ceil(30/3) × (boot + agent)` ≈ 15–30 min.

## Storage

- `jobs.db` — SQLite (WAL mode) with two tables: `jobs` (one row per submission), `attempts` (one row per `(problem, attempt#)`). Job-level status (`queued`/`running`/`done`) is derived from attempt statuses on read.
- `runs/<job_id>/tasks.json` — frozen copy of the uploaded file.
- `runs/<job_id>/<attempt_id>/` — all per-rollout artifacts (same shape as M1's per-task `runs/` dirs, listed above).

Reset:

```bash
make clean-jobs     # rm jobs.db + runs/   (does not touch docker)
make clean-runs     # tear down any stranded dt-m1-* compose projects
```

## API surface (also browsable at <http://localhost:8000/docs>)

```
POST   /api/jobs                         multipart: tasks_json, attempts_per_problem, name
GET    /api/jobs                         list with aggregated pass/fail/run/queue counts
GET    /api/jobs/{id}                    job + its attempts
GET    /api/attempts/{id}                row from sqlite
GET    /api/attempts/{id}/trajectory     trajectory.jsonl (streamed)
GET    /api/attempts/{id}/messages       full Gemini conversation
GET    /api/attempts/{id}/grade          grade.json + expected/actual
GET    /api/attempts/{id}/video          video.webm with HTTP Range
GET    /api/attempts/{id}/screenshots/N  PNG for step N
```

## Scaling hook (M3)

The agent's CLI contract is the unit of work. `backend/worker.py` calls it via `SubprocessLauncher` for M2; the `Launcher` protocol has two stub launchers ready to swap in:

- `DockerLauncher` → `docker run agent:latest …` (image is buildable now via `Dockerfile.agent` at the repo root).
- `ModalLauncher` → `modal.spawn(agent_fn, …)`.

M3 = wire one of those up and (optionally) move the FastAPI app + queue to a managed Postgres/Redis. None of the routes, schemas, runner, or grader need to change.

## What's intentionally not here in M2

- **No live browser stream** — review is post-hoc via the .webm + screenshots.
- **No multi-host worker** — single asyncio task in the FastAPI process. Crashes mark in-flight attempts as `error` on next startup (`reconcile_on_startup`).
- **No cancel / retry buttons** — for M2, kill stranded compose stacks with `make clean-runs` and resubmit the job.
- **No token/$ cost tracking** — the vendored agent doesn't surface `usage_metadata` cleanly; deferred to M3.
