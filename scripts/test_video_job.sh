#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Accept any number of video URLs; jobs are submitted up front and polled
# together, exercising the worker pool (OVS_TEST_WORKER_CONCURRENCY).
URLS=("$@")
if [[ ${#URLS[@]} -eq 0 ]]; then
  URLS=("https://www.bilibili.com/video/BV1E8UQBeEzg")
fi
PORT="${OVS_TEST_PORT:-8010}"
HOST="127.0.0.1"
BASE_URL="http://${HOST}:${PORT}"
LOG_DIR="${ROOT_DIR}/artifacts/test-runs"
SERVER_LOG="${LOG_DIR}/backend-${PORT}.log"
ENABLE_SUMMARIZER="${OVS_TEST_ENABLE_MLX_SUMMARIZER:-false}"
PYTHON="${OVS_TEST_PYTHON:-${ROOT_DIR}/.venv/bin/python}"
WORKER_CONCURRENCY="${OVS_TEST_WORKER_CONCURRENCY:-2}"

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
echo "worker_concurrency=${WORKER_CONCURRENCY}"
if [[ "${SUMMARIZER_PROVIDER}" == "omlx" ]]; then
  echo "omlx_base_url=${OVS_OMLX_BASE_URL:-(not set)}"
  echo "omlx_model=${OVS_OMLX_MODEL:-(not set)}"
  echo "omlx_api_key=${OVS_OMLX_API_KEY:+set}"
fi
if [[ "${SUMMARIZER_PROVIDER}" == "deepseek" ]]; then
  echo "deepseek_base_url=${OVS_DEEPSEEK_BASE_URL:-(default)}"
  echo "deepseek_model=${OVS_DEEPSEEK_MODEL:-(default)}"
  echo "deepseek_api_key=${OVS_DEEPSEEK_API_KEY:+set}"
fi
OVS_ENABLE_MLX_ASR=true \
OVS_SUMMARIZER_PROVIDER="${SUMMARIZER_PROVIDER}" \
OVS_ENABLE_MLX_SUMMARIZER="${ENABLE_SUMMARIZER}" \
OVS_WORKER_CONCURRENCY="${WORKER_CONCURRENCY}" \
"${PYTHON}" - <<'PY'
import importlib.util
from backend.app.core.config import get_settings

settings = get_settings()
print(f"summarizer_provider={settings.summarizer_provider}")
print(f"worker_concurrency={settings.worker_concurrency}")
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
OVS_WORKER_CONCURRENCY="${WORKER_CONCURRENCY}" \
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

# Submit every URL up front so the worker pool processes them in parallel.
# Bash 3.2 (macOS): parallel indexed arrays, no associative arrays.
JOB_IDS=()
for URL in "${URLS[@]}"; do
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
  JOB_IDS+=("${JOB_ID}")
done

ATTEMPTS=0
# MAX_POLLS counts poll cycles for the whole batch. Parallel jobs overlap, so
# the default usually suffices; raise it for large batches.
MAX_ATTEMPTS="${OVS_TEST_MAX_POLLS:-180}"
SLEEP_SECONDS="${OVS_TEST_POLL_INTERVAL:-2}"

JOB_STATES=()
for _ in "${JOB_IDS[@]}"; do
  JOB_STATES+=("")
done
ANY_FAILED=0

while true; do
  PENDING=0
  for i in "${!JOB_IDS[@]}"; do
    if [[ -n "${JOB_STATES[$i]}" ]]; then
      continue
    fi
    JOB_ID="${JOB_IDS[$i]}"
    STATUS_JSON="$(curl -fsS "${BASE_URL}/jobs/${JOB_ID}")"
    STATUS="$(
      printf '%s' "${STATUS_JSON}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["status"])'
    )"
    STAGE="$(
      printf '%s' "${STATUS_JSON}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["progress_stage"])'
    )"
    echo "job=${JOB_ID} status=${STATUS} stage=${STAGE}"

    if [[ "${STATUS}" == "completed" ]]; then
      JOB_STATES[$i]="completed"
    elif [[ "${STATUS}" == "failed" ]]; then
      # A failed job must not abort the loop; let sibling jobs finish.
      JOB_STATES[$i]="failed"
      ANY_FAILED=1
      echo "error: job ${JOB_ID} (${URLS[$i]}) failed" >&2
      printf '%s\n' "${STATUS_JSON}" >&2
    else
      PENDING=1
    fi
  done

  if (( PENDING == 0 )); then
    break
  fi

  ATTEMPTS=$((ATTEMPTS + 1))
  if (( ATTEMPTS >= MAX_ATTEMPTS )); then
    echo "error: timed out waiting for jobs" >&2
    tail -n 80 "${SERVER_LOG}" >&2 || true
    exit 1
  fi

  sleep "${SLEEP_SECONDS}"
done

for i in "${!JOB_IDS[@]}"; do
  JOB_ID="${JOB_IDS[$i]}"
  if [[ "${JOB_STATES[$i]}" != "completed" ]]; then
    continue
  fi
  RESULT_JSON="$(curl -fsS "${BASE_URL}/jobs/${JOB_ID}/result")"
  RESULT_PATH="${LOG_DIR}/${JOB_ID}-result.json"
  printf '%s\n' "${RESULT_JSON}" > "${RESULT_PATH}"

  echo "Job ${JOB_ID} (${URLS[$i]}) completed successfully."
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
done

if (( ANY_FAILED )); then
  echo "error: one or more jobs failed. Backend log tail:" >&2
  tail -n 80 "${SERVER_LOG}" >&2 || true
  exit 1
fi
