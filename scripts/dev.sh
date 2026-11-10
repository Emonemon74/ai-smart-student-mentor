#!/usr/bin/env bash
# Start everything for the demo (LLD C15): Postgres, tunnel, API, web.
# Needs: docker, uv, node, cloudflared. API port defaults to 8000; override with API_PORT in api/.env.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

[ -f api/.env ] || { echo "Missing api/.env (copy .env.example to api/.env first)"; exit 1; }
set -a; . api/.env; set +a
API_PORT="${API_PORT:-8000}"
export API_PORT

docker compose up -d postgres

PIDS=()
cleanup() { echo; echo "Stopping..."; for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

# Tunnel: only the web port is exposed. Read its log until the public URL appears.
if command -v cloudflared >/dev/null 2>&1; then
  TLOG="$(mktemp)"
  cloudflared tunnel --url http://localhost:3000 >"$TLOG" 2>&1 &
  PIDS+=($!)
  URL=""
  for _ in $(seq 1 40); do
    URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TLOG" | head -1 || true)"
    [ -n "$URL" ] && break
    sleep 1
  done
  [ -n "$URL" ] && export PUBLIC_BASE_URL="$URL" || echo "Tunnel URL not found; phone links will use $PUBLIC_BASE_URL"
else
  echo "cloudflared not installed: phone hand-off will use PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-http://localhost:3000} (LAN/hotspot fallback)"
fi

(cd api && uv run fastapi run app/main.py --port "$API_PORT") &
PIDS+=($!)
(cd web && npm run build && npm start) &
PIDS+=($!)

sleep 6
echo
echo "Kiosk:  http://localhost:3000"
echo "Phone:  ${PUBLIC_BASE_URL:-http://localhost:3000}"
echo "Admin:  ${PUBLIC_BASE_URL:-http://localhost:3000}/admin"
wait
