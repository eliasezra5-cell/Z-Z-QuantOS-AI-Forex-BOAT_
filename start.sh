#!/bin/bash
# ZZ_QuantOS AI BOAT - unified startup script
# Starts the backend API server and the frontend dev server.
# The frontend port (5173) is the exposed preview port and reverse-proxies /api to the backend.

set -e

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[boot] Starting backend (port 3001) ..."
(cd backend-py && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3001) &
BACKEND_PID=$!

echo "[boot] Waiting for backend health ..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:3001/api/health >/dev/null 2>&1; then
    echo "[boot] Backend is healthy."
    break
  fi
  sleep 1
done

echo "[boot] Starting frontend (port 5173) ..."
(cd frontend && npm run dev)
