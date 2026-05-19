.PHONY: help pull run clean-runs clean-jobs up down reset logs status api web web-install web-build

help:
	@echo "M1 — single-task runs (debugging):"
	@echo "  make pull                - pre-pull postgres + metabase images (first time only)"
	@echo "  make run TASK=problem1   - boot fresh env -> run agent -> grade -> teardown"
	@echo "  make clean-runs          - tear down any stranded dt-m1-* compose projects"
	@echo
	@echo "M2 — jobs/rollouts platform (two terminals):"
	@echo "  make api                 - FastAPI backend + asyncio worker on :8000"
	@echo "  make web                 - Next.js dashboard on :3001"
	@echo "  make web-install         - pnpm install (first time)"
	@echo "  make clean-jobs          - rm jobs.db + runs/ (start fresh)"
	@echo
	@echo "Manual exploration (long-lived stack on port 3000):"
	@echo "  make up                  - start Postgres + Metabase, seed the dump"
	@echo "  make down                - stop containers (keep data volume)"
	@echo "  make reset               - stop + wipe volume + start fresh (re-seeds)"
	@echo "  make status              - show container status"
	@echo "  make logs                - tail logs from all containers"

# Pre-pull the two large images once so a cold `make run` isn't stuck on a
# ~700 MB download mid-task.
pull:
	docker compose pull postgres metabase

run:
	@test -n "$(TASK)" || (echo "usage: make run TASK=problem1"; exit 2)
	python -m runner.run_task --task-id $(TASK)

# Find any compose projects named dt-m1-* and tear them down. Handy if a
# previous run got SIGKILL'd before its finally clause could clean up.
clean-runs:
	@docker compose ls --format json \
	  | python3 -c "import sys, json; \
[print(p['Name']) for p in json.load(sys.stdin) if p['Name'].startswith('dt-m1-')]" \
	  | while read -r p; do \
	      echo "down: $$p"; \
	      docker compose -p $$p down -v; \
	    done

# --- M2 platform ----------------------------------------------------------

# Note: no --reload by default. uvicorn's --reload + watchfiles has been
# flaky on Python 3.14 (the worker subprocess can leave the parent with a
# bound socket but no live ASGI app). Use `make api-dev` if you want
# auto-reload while iterating on backend code.
api:
	uvicorn backend.main:app --port 8000

api-dev:
	uvicorn backend.main:app --reload --port 8000

web:
	cd frontend && pnpm dev

web-install:
	cd frontend && pnpm install

web-build:
	cd frontend && pnpm build

# Nuke the job DB + all artifact dirs. Does NOT touch stranded docker projects;
# use `make clean-runs` for those.
clean-jobs:
	@rm -rf runs/ jobs.db jobs.db-wal jobs.db-shm
	@echo "jobs.db + runs/ removed"

# --- manual exploration targets (port 3000) -------------------------------

up:
	docker compose up -d
	@echo "Waiting for Metabase to report healthy..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' $$(docker compose ps -q metabase) 2>/dev/null)" = "healthy" ]; do \
	  sleep 3; printf "."; \
	done; echo
	@echo "Metabase ready at http://localhost:3000"

down:
	docker compose down

reset:
	docker compose down -v
	$(MAKE) up

status:
	docker compose ps

logs:
	docker compose logs -f --tail=100
