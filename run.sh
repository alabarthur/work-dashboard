#!/usr/bin/env bash
# Start the Work Table dashboard server.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${WORKTABLE_PORT:-8787}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "Work Table → http://localhost:${PORT}"
# --reload auto-restarts on backend code changes. Only watch source dirs (not
# data/, which the collector writes to) so collections don't trigger reloads.
exec "$PY" -m uvicorn app.main:app --port "$PORT" --host 127.0.0.1 \
    --reload --reload-dir app --reload-dir collector --reload-dir scoring
