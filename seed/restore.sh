#!/usr/bin/env bash
# Idempotent restore of metabase_envdata.sql into root_db.
# Mounted as /restore.sh and run as the entrypoint of the `seed` service.
set -euo pipefail

# Wait for Postgres to actually accept queries (compose healthcheck is usually
# enough, but be defensive — pg_isready can flap during initial setup).
for i in {1..30}; do
  if psql -d postgres -c "SELECT 1" >/dev/null 2>&1; then break; fi
  echo "waiting for postgres ($i/30)..."
  sleep 1
done

# Skip the restore if root_db already has user tables — lets `docker compose up`
# be re-run cheaply without nuking state.
if psql -lqt | cut -d'|' -f1 | grep -qw root_db; then
  table_count=$(psql -d root_db -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
  if [ "$table_count" -gt 0 ]; then
    echo "root_db already has $table_count tables; skipping restore."
    echo "Run 'docker compose down -v' to wipe and reseed."
    exit 0
  fi
fi

echo "Dropping and recreating root_db..."
dropdb --if-exists root_db
createdb root_db

echo "Restoring metabase_envdata.sql into root_db..."
# --no-owner / --no-acl: the dump references a 'postgres' owner that doesn't
# match what Metabase will reconnect as; ignoring these keeps the restore clean.
# --exit-on-error: fail loudly if any object fails to restore.
pg_restore \
  --dbname=root_db \
  --no-owner \
  --no-acl \
  --exit-on-error \
  /dump.sql

table_count=$(psql -d root_db -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
echo "Seed complete: root_db has $table_count tables."
