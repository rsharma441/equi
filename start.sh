#!/bin/bash
# Start both servers for local development
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=== Equi Allocator Memo Builder ==="

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  if [ -f "$ROOT/.env" ]; then
    export $(grep -v '^#' "$ROOT/.env" | xargs)
  fi
fi

if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "your_key_here" ]; then
  echo "ERROR: Set ANTHROPIC_API_KEY in .env or your environment before running."
  exit 1
fi

echo "Starting FastAPI backend on http://localhost:8001 ..."
source "$ROOT/.venv/bin/activate"
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload &
BACKEND_PID=$!

echo "Starting Next.js frontend on http://localhost:3001 ..."
cd "$ROOT/frontend" && npm run dev -- --port 3001 &
FRONTEND_PID=$!

echo ""
echo "  Backend: http://localhost:8001"
echo "  Frontend: http://localhost:3001"
echo "  API Docs: http://localhost:8001/docs"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
