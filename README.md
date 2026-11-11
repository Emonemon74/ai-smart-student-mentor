# AI Smart Student Mentor (Trialshopy assignment)

Build contract: [docs/HLD.md](docs/HLD.md) and [docs/LLD.md](docs/LLD.md). Synthetic data only.

## Prerequisites
Docker (running), [uv](https://docs.astral.sh/uv/), Node.js 20+ with npm, and optionally `cloudflared` for the phone hand-off (`brew install cloudflared`). Without it the phone link falls back to `PUBLIC_BASE_URL` (LAN or hotspot). You need at least one LLM key: a free Groq key is enough, and a second provider (for example Gemini) is used automatically if the first is rate limited.

## Setup
```bash
cp .env.example api/.env     # set ADMIN_PASSWORD (12+ chars), GROQ_API_KEY and GROQ_MODEL (and optionally GEMINI_API_KEY and GEMINI_MODEL)
docker compose up -d         # Postgres on host port 5433
cd api && uv sync && uv run python -m app.connector import seed --batch baseline && cd ..
cd web && npm install && cd ..
```
The bundled synthetic data is dated around 10 November 2026. When you import it, every date is moved forward by the days that have passed since then, so the upcoming internal is always still in the future and nobody is flagged with a "missing mark" because the data went stale. Add `--exact-dates` to the import command to keep the CSV dates as they are. Real data (any folder other than the bundled `api/seed`) is never shifted.

If something already uses port 8000 on your machine, add `API_PORT=8010` to `api/.env`. Pick non-reasoning chat models, because reasoning models can spend their token budget thinking and return an empty reply.

## Run the demo
```bash
./scripts/dev.sh             # Postgres, tunnel, API, web; prints the URLs
google-chrome --kiosk --user-data-dir=$HOME/.emon-kiosk http://localhost:3000
```
On macOS use `open -na "Google Chrome" --args --kiosk --user-data-dir=$HOME/.emon-kiosk http://localhost:3000`, or simply open http://localhost:3000 in a normal Chrome window. Allow the microphone once for `localhost:3000`.

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
`cd api && uv run pytest`   (99 tests; uses database `emon_test`; the LLM is never called; includes the full demo journey run twice)

## Reset
Clear sessions, plans, requests, feedback and the audit log, and remove the imported review marks so the "review day" step works live again. The 30 students, baseline marks and resources are kept:
```bash
docker compose exec postgres psql -U emon -c "TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log RESTART IDENTITY CASCADE; DELETE FROM assessments WHERE batch='review'; DELETE FROM attendance WHERE batch='review'; DELETE FROM imports WHERE batch='review';"
```

## End of semester

Saved plans are cleared at semester end (HLD §9). This deletes all plans, tasks, share links and phone sessions, and keeps student records:

```bash
cd api && uv run python -m app.connector end-semester
```
