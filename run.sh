#!/usr/bin/env bash
# Start the Work Table dashboard server.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${WORKTABLE_PORT:-8787}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "Work Table → http://localhost:${PORT}"
exec "$PY" -m uvicorn app.main:app --port "$PORT" --host 127.0.0.1
