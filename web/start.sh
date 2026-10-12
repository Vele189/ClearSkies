#!/usr/bin/env bash
#
# Start the frontend for local development.
#
# No --host. Vite then binds localhost and prints localhost, which matters:
# the API's CORS_ORIGINS names `http://localhost:5173` and a browser treats
# http://127.0.0.1:5173 as a different origin however it resolves, so every
# request from that address is blocked with no CORS header.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-5173}"

if [[ ! -d node_modules ]]; then
    echo "installing dependencies first..."
    npm install --no-audit --no-fund
fi

# Vite reads VITE_* at startup and inlines them, so a missing .env is not a
# runtime warning the reader will see -- it is a map with no hexes and a banner
# explaining why. Worth saying before the server comes up rather than after.
if [[ ! -e .env ]]; then
    echo "warning: no web/.env. The map will show the basemap only." >&2
    echo "         Copy .env.example; VITE_TILES_URL is the one that matters." >&2
fi

api="$(grep -E '^VITE_API_BASE_URL=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"'" )"
api="${api:-http://localhost:8000}"
if ! curl -fsS -o /dev/null --max-time 3 "${api}/health" 2>/dev/null; then
    echo "warning: no API answering at ${api}. Start it with api/start.sh." >&2
fi

# --strictPort, and a check before it.
#
# Vite's default is to take the next free port when the one it was asked for is
# busy, and to say so only in its own banner. A second dev server therefore
# comes up on 5174 looking healthy, while the API's CORS_ORIGINS names 5173 and
# nothing else -- so every request from it is blocked and the page reports "the
# API is not reachable", which is true and points at entirely the wrong thing.
# Better to refuse the port than to serve a page that cannot reach anything.
if curl -fsS -o /dev/null --max-time 2 "http://localhost:${PORT}/" 2>/dev/null; then
    echo "something is already serving http://localhost:${PORT}." >&2
    echo "  Stop it first: pkill -f 'vite --port ${PORT}'" >&2
    echo "  A second server would take the next free port, which the API's" >&2
    echo "  CORS_ORIGINS does not name, and the page would report the API" >&2
    echo "  unreachable while the API is fine." >&2
    exit 1
fi

echo "frontend on http://localhost:${PORT}  (use localhost, not 127.0.0.1)"
exec npm run dev -- --port "$PORT" --strictPort
