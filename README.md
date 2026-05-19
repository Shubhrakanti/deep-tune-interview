# Metabase RL Environment — Milestone 1

A local, single-machine MVP of a computer-use RL environment for Metabase.

- **Env:** Metabase + Postgres in Docker Compose, seeded from `metabase_envdata.sql`.
- **Lifecycle:** every task run gets a **fresh, ephemeral** stack — unique compose project, random host port, torn down after the run.
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
├── prompt.txt    # the exact query handed to the agent
└── run.json      # task, project, base_url, final reasoning, grade
```

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
├── tasks.json                  # M1 tasks + expected answers
├── metabase_envdata.sql        # pg_dump -Fc of root_db (Metabase metadata)
├── vendor/
│   └── computer-use-preview/   # git submodule, used verbatim
├── runner/
│   └── run_task.py             # env up -> agent -> grade -> env down
├── grading/
│   ├── base.py                 # Grader protocol (slot for DB-diff later)
│   └── json_match.py           # normalized JSON-match grader
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
- No frontend / job submission UI — that's Milestone 2.
- No DB-state-diff grading wired up — interface only.
- No multi-attempt rollouts — Milestone 2.
