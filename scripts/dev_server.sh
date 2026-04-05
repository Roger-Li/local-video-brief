#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${OVS_DEV_BACKEND_PORT:-8010}"
# Frontend port is fixed at 5173 to match CORS allow_origins in backend/app/main.py.
FRONTEND_PORT=5173
BACKEND_HOST="127.0.0.1"
PYTHON="${OVS_DEV_PYTHON:-}"

# Resolve Python: explicit env var > ~/ml-env > repo .venv > system python3
if [[ -z "${PYTHON}" ]]; then
  if [[ -x "$HOME/ml-env/bin/python" ]]; then
    PYTHON="$HOME/ml-env/bin/python"
  elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON="${ROOT_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

echo "==> Using Python: ${PYTHON}"
echo "==> Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "==> Frontend: http://localhost:${FRONTEND_PORT}"
echo ""

# Kill anything already on our ports
for port in "${BACKEND_PORT}" "${FRONTEND_PORT}"; do
  pids=$(lsof -ti:"${port}" 2>/dev/null || true)
  if [[ -n "${pids}" ]]; then
    echo "==> Killing stale process(es) on port ${port}: ${pids}"
    echo "${pids}" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
done

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "==> Shutting down..."
  [[ -n "${FRONTEND_PID}" ]] && kill "${FRONTEND_PID}" 2>/dev/null || true
  [[ -n "${BACKEND_PID}" ]] && kill "${BACKEND_PID}" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "==> Done."
}
trap cleanup EXIT INT TERM

# Start backend
cd "${ROOT_DIR}"
"${PYTHON}" -m uvicorn backend.app.main:app \
  --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" &
BACKEND_PID=$!

# Wait for backend to be ready
echo "==> Waiting for backend..."
BACKEND_READY=false
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    echo "==> Backend ready."
    BACKEND_READY=true
    break
  fi
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "ERROR: Backend process exited." >&2
    exit 1
  fi
  sleep 1
done
if [[ "${BACKEND_READY}" != "true" ]]; then
  echo "ERROR: Backend did not become healthy within 30s." >&2
  exit 1
fi

# Start frontend
cd "${ROOT_DIR}/frontend"
VITE_API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}" \
  npx vite --port "${FRONTEND_PORT}" &
FRONTEND_PID=$!

echo ""
echo "==> Both servers running. Press Ctrl-C to stop."
wait
