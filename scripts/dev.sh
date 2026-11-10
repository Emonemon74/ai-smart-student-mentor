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
# List a process and everything it started (the API and web server run under subshells and npm/uv wrappers).
tree() {
  local pid="$1" child
  echo "$pid"
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do tree "$child"; done
}
cleanup() {
  trap - EXIT INT TERM
  echo; echo "Stopping..."
  local all=() p
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && all+=($(tree "$p")); done
  [ ${#all[@]} -gt 0 ] && kill "${all[@]}" 2>/dev/null || true
  sleep 2
  for p in "${all[@]:-}"; do kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true; done  # anything slow to exit
}
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
