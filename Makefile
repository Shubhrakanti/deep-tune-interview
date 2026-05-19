.PHONY: help pull run clean-runs up down reset logs status

help:
	@echo "Per-task runs (recommended):"
	@echo "  make pull                - pre-pull postgres + metabase images (first time only)"
	@echo "  make run TASK=problem1   - boot fresh env -> run agent -> grade -> teardown"
	@echo "  make clean-runs          - tear down any stranded dt-m1-* compose projects"
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
