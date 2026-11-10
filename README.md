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

## Demo script (about 3 minutes)
1. `./scripts/dev.sh`, then open the kiosk: `google-chrome --kiosk --user-data-dir=$HOME/.emon-kiosk http://localhost:3000`.
2. Sign in as `CS23001` / PIN `1234` (all 30 synthetic students use `1234`), accept the privacy notice.
3. Profile: Data Structures is flagged with reasons (below self, below class, falling quizzes, weak Graphs).
4. Mentor: talk or type ("BFS and DFS confuse me, one hour a day"), then **Create my plan**, **Generate**, edit, **Save plan**.
5. **Send to my phone**: scan the QR (single use, 10 minutes). Tick tasks on the phone; open the Progress tab.
6. Review day: `cd api && uv run python -m app.connector import seed --batch review`, then open the report: verified before/after, kept apart from the ticks.
7. Staff: `/admin` with the `ADMIN_PASSWORD` from `api/.env`: group totals (small groups hidden), request queue, health, audit.

Hindi: switch with the language button (UI strings and mentor replies).  Wellbeing worries are answered with a human-mentor referral, never counselling.

## Local port notes
Postgres is mapped to host port **5433** and the API defaults to port 8000 (set `API_PORT=8010` in `api/.env` if 8000 is busy).

## Tests
`cd api && uv run pytest`   (89 tests; uses database `emon_test`; the LLM is never called; includes the full demo journey run twice)

## Reset
`docker compose exec postgres psql -U emon -c "TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log RESTART IDENTITY CASCADE"` then re-import.
