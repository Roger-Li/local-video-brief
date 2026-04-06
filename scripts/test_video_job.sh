#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="${1:-https://www.bilibili.com/video/BV1E8UQBeEzg}"
PORT="${OVS_TEST_PORT:-8010}"
HOST="127.0.0.1"
BASE_URL="http://${HOST}:${PORT}"
LOG_DIR="${ROOT_DIR}/artifacts/test-runs"
SERVER_LOG="${LOG_DIR}/backend-${PORT}.log"
ENABLE_SUMMARIZER="${OVS_TEST_ENABLE_MLX_SUMMARIZER:-false}"
PYTHON="${OVS_TEST_PYTHON:-${ROOT_DIR}/.venv/bin/python}"

# Provider resolution: explicit OVS_TEST_SUMMARIZER_PROVIDER wins,
# then legacy OVS_TEST_ENABLE_MLX_SUMMARIZER=true maps to mlx,
# else fallback.
if [[ -n "${OVS_TEST_SUMMARIZER_PROVIDER:-}" ]]; then
  SUMMARIZER_PROVIDER="${OVS_TEST_SUMMARIZER_PROVIDER}"
elif [[ "${ENABLE_SUMMARIZER}" == "true" ]]; then
  SUMMARIZER_PROVIDER="mlx"
else
  SUMMARIZER_PROVIDER="fallback"
fi

mkdir -p "${LOG_DIR}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT

cd "${ROOT_DIR}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "error: python not found at ${PYTHON}. Set OVS_TEST_PYTHON or create a .venv." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "error: ffmpeg is required but not installed." >&2
  exit 1
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "error: yt-dlp is required on PATH. Install it with 'brew install yt-dlp'." >&2
  exit 1
fi

echo "Verifying project runtime..."
echo "summarizer_provider=${SUMMARIZER_PROVIDER}"
if [[ "${SUMMARIZER_PROVIDER}" == "omlx" ]]; then
  echo "omlx_base_url=${OVS_OMLX_BASE_URL:-(not set)}"
  echo "omlx_model=${OVS_OMLX_MODEL:-(not set)}"
  echo "omlx_api_key=${OVS_OMLX_API_KEY:+set}"
fi
OVS_ENABLE_MLX_ASR=true \
OVS_SUMMARIZER_PROVIDER="${SUMMARIZER_PROVIDER}" \
OVS_ENABLE_MLX_SUMMARIZER="${ENABLE_SUMMARIZER}" \
"${PYTHON}" - <<'PY'
import importlib.util
from backend.app.core.config import get_settings

settings = get_settings()
print(f"summarizer_provider={settings.summarizer_provider}")
print(f"enable_mlx_asr={settings.enable_mlx_asr}")
print(f"enable_mlx_summarizer={settings.enable_mlx_summarizer}")
print(f"mlx_whisper_installed={importlib.util.find_spec('mlx_whisper') is not None}")
print(f"mlx_lm_installed={importlib.util.find_spec('mlx_lm') is not None}")
print(f"httpx_installed={importlib.util.find_spec('httpx') is not None}")
PY

echo "Starting isolated backend on ${BASE_URL}..."
OVS_ENABLE_MLX_ASR=true \
OVS_SUMMARIZER_PROVIDER="${SUMMARIZER_PROVIDER}" \
OVS_ENABLE_MLX_SUMMARIZER="${ENABLE_SUMMARIZER}" \
"${PYTHON}" -m uvicorn backend.app.main:app --host "${HOST}" --port "${PORT}" >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  echo "error: backend did not become healthy. Log:" >&2
  tail -n 50 "${SERVER_LOG}" >&2 || true
  exit 1
fi

POWER_MODE="${OVS_TEST_POWER_MODE:-false}"
STRATEGY_OVERRIDE="${OVS_TEST_STRATEGY_OVERRIDE:-}"

# Build options JSON for job submission.
OPTIONS_JSON=""
if [[ "${POWER_MODE}" == "true" ]]; then
  OPTIONS_JSON='"options":{"power_mode":true'
  if [[ -n "${STRATEGY_OVERRIDE}" ]]; then
    OPTIONS_JSON="${OPTIONS_JSON},\"strategy_override\":\"${STRATEGY_OVERRIDE}\""
  fi
  OPTIONS_JSON="${OPTIONS_JSON}}"
fi

echo "Submitting job for ${URL}"
if [[ -n "${OPTIONS_JSON}" ]]; then
  JOB_BODY="{\"url\":\"${URL}\",\"output_languages\":[\"en\",\"zh-CN\"],\"mode\":\"captions_first\",${OPTIONS_JSON}}"
else
  JOB_BODY="{\"url\":\"${URL}\",\"output_languages\":[\"en\",\"zh-CN\"],\"mode\":\"captions_first\"}"
fi
echo "request body: ${JOB_BODY}"
JOB_ID="$(
  curl -fsS -X POST "${BASE_URL}/jobs" \
    -H 'Content-Type: application/json' \
    -d "${JOB_BODY}" \
  | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["job_id"])'
)"

echo "job_id=${JOB_ID}"

ATTEMPTS=0
MAX_ATTEMPTS="${OVS_TEST_MAX_POLLS:-180}"
SLEEP_SECONDS="${OVS_TEST_POLL_INTERVAL:-2}"

while true; do
  STATUS_JSON="$(curl -fsS "${BASE_URL}/jobs/${JOB_ID}")"
  STATUS="$(
    printf '%s' "${STATUS_JSON}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["status"])'
  )"
  STAGE="$(
    printf '%s' "${STATUS_JSON}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["progress_stage"])'
  )"
  echo "status=${STATUS} stage=${STAGE}"

  if [[ "${STATUS}" == "completed" ]]; then
    break
  fi

  if [[ "${STATUS}" == "failed" ]]; then
    echo "error: job failed" >&2
    printf '%s\n' "${STATUS_JSON}" >&2
    echo "backend log tail:" >&2
    tail -n 80 "${SERVER_LOG}" >&2 || true
    exit 1
  fi

  ATTEMPTS=$((ATTEMPTS + 1))
  if (( ATTEMPTS >= MAX_ATTEMPTS )); then
    echo "error: timed out waiting for job ${JOB_ID}" >&2
    printf '%s\n' "${STATUS_JSON}" >&2
    tail -n 80 "${SERVER_LOG}" >&2 || true
    exit 1
  fi

  sleep "${SLEEP_SECONDS}"
done

RESULT_JSON="$(curl -fsS "${BASE_URL}/jobs/${JOB_ID}/result")"
RESULT_PATH="${LOG_DIR}/${JOB_ID}-result.json"
printf '%s\n' "${RESULT_JSON}" > "${RESULT_PATH}"

echo "Job completed successfully."
echo "Saved result to ${RESULT_PATH}"
RESULT_PATH="${RESULT_PATH}" POWER_MODE="${POWER_MODE}" "${PYTHON}" - <<'PY'
import json
import os

with open(os.environ["RESULT_PATH"], "r", encoding="utf-8") as handle:
    result = json.load(handle)

power = os.environ.get("POWER_MODE", "false") == "true"
if power:
    raw = result.get("raw_summary_text")
    if raw is None:
        print("FAIL: power mode job missing raw_summary_text")
        raise SystemExit(1)
    print(f"raw_summary_text length={len(raw)}")
    print(f"raw_summary_text preview={raw[:200]}")
else:
    overall = result["overall_summary"]
    print(f"chapters={len(result['chapters'])}")
    print(f"summary_en={overall['summary_en']}")
    print(f"summary_zh={overall['summary_zh']}")
PY
