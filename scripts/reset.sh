#!/usr/bin/env bash
# Reset the demo database (LLD_next C15): fresh Postgres volume, dated synthetic data from today, baseline import.
# The schema changed in v2 and is applied in place, so an existing demo database must be recreated once.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose down -v
docker compose up -d postgres
for _ in $(seq 1 30); do
  docker compose exec -T postgres pg_isready -U emon >/dev/null 2>&1 && break
  sleep 1
done
(cd api && uv run python seed/gen.py --out seed/ && uv run python -m app.connector import seed --batch baseline)
echo "Reset done. Next: ./scripts/dev.sh, and 'cd api && uv run python -m app.connector check-links' before the demo."
