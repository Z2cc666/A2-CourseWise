#!/usr/bin/env bash
#
# CourseWise — start the whole system locally.
#
#   ./run.sh          start the server (creates the venv on first run)
#   ./run.sh --dev    start with auto-reload
#
# Then open http://127.0.0.1:8000

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

if [ ! -d "$VENV" ]; then
  echo "→ Creating virtual environment…"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
  echo "→ Dependencies installed."
fi

# Load .env if it exists. Values already in the environment win.
if [ -f "$ROOT/.env" ]; then
  echo "→ Loading .env"
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

cd "$ROOT/backend"

if [ "${1:-}" = "--dev" ]; then
  echo "→ Starting CourseWise in development mode on http://127.0.0.1:$PORT"
  exec "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --reload
else
  echo "→ Starting CourseWise on http://127.0.0.1:$PORT"
  exec "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT"
fi
