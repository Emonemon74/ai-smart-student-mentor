# AI Smart Student Mentor (Trialshopy assignment)

Build contract: [docs/HLD.md](docs/HLD.md) and [docs/LLD.md](docs/LLD.md). Synthetic data only.

## Setup
```bash
cp .env.example api/.env     # set ADMIN_PASSWORD (12+ chars) and provider keys
docker compose up -d         # Postgres on host port 5433
cd api && uv sync && uv run python -m app.connector import seed --batch baseline
```
If something already uses port 8000 on your machine, add `API_PORT=8010` to `api/.env`.

## Run the demo
```bash
./scripts/dev.sh             # Postgres, tunnel, API, web; prints the URLs
google-chrome --kiosk --user-data-dir=$HOME/.emon-kiosk http://localhost:3000
```
Demo sequence: import baseline, run the student journey, scan the QR on a phone, then
`cd api && uv run python -m app.connector import seed --batch review` and open the report.

## Tests
`cd api && uv run pytest`   (uses database `emon_test`; the LLM is never called)

## Reset
`docker compose exec postgres psql -U emon -c "TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log RESTART IDENTITY CASCADE"` then re-import.
