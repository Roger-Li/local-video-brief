---
name: test-e2e
description: Run end-to-end pipeline tests against real video URLs to validate feature changes. Use when the user wants to test with real videos, validate summarization, or verify pipeline behavior after code changes.
argument-hint: [video-url] [--provider fallback|mlx|omlx] [--timeout 300] [--allow-section-refinement] [--expect-timestamps] [--no-frontend]
disable-model-invocation: true
---

# E2E Pipeline Test

Run end-to-end tests against real video URLs to validate the full pipeline: backend summarization, study pack generation, artifacts, and frontend build health. Prefer automated checks over manual inspection.

## Arguments

- `$ARGUMENTS` contains the raw arguments string
- Parse video URLs (anything starting with `http`) and flags from the arguments
- Supported flags:
  - `--provider <fallback|mlx|omlx>` — summarizer provider (default: reads from `.env` or falls back to `fallback`)
  - `--timeout <seconds>` — oMLX timeout (default: 300)
  - `--asr` — force enable MLX ASR even if captions are available
  - `--allow-section-refinement` — allow `study_pack.sections` to differ from chapter count for Phase B v2+
  - `--expect-timestamps` — require timestamp ranges in generated `study_guide.md`
  - `--no-frontend` — skip frontend build and frontend test checks
- If no URL is provided, use the default bilibili URL from the smoke test script

## Environment Setup

1. Detect the user's Python environment:
   - Check `OVS_TEST_PYTHON` env var first
   - Then `$HOME/ml-env/bin/python`
   - Then `.venv/bin/python`

2. If provider is `omlx`:
   - Read `OVS_OMLX_BASE_URL`, `OVS_OMLX_MODEL`, `OVS_OMLX_API_KEY` from the environment or `.env` file
   - If not set, query the oMLX server at common ports (8000, 8080) via `curl /v1/models` to auto-discover
   - Print the effective oMLX config (redact API key)

3. Clear stale DB before each run: `rm -f data/local_video_brief.sqlite3`

4. Record the smoke-test backend port:
   - `PORT="${OVS_TEST_PORT:-8010}"`
   - Use this same port for any frontend checks via `VITE_API_BASE_URL=http://127.0.0.1:${PORT}`

## Execution

Run each video URL through the smoke test. Always set `OVS_ENABLE_STUDY_PACK=true` to exercise the study-pack path:

```bash
rm -f data/local_video_brief.sqlite3
OVS_TEST_SUMMARIZER_PROVIDER=<provider> \
OVS_OMLX_BASE_URL=<base_url> \
OVS_OMLX_MODEL=<model> \
OVS_OMLX_API_KEY=<api_key> \
OVS_OMLX_TIMEOUT_SECONDS=<timeout> \
OVS_ENABLE_MLX_ASR=<true if --asr or provider needs it> \
OVS_ENABLE_STUDY_PACK=true \
OVS_TEST_PYTHON=<python_path> \
OVS_TEST_MAX_POLLS=300 \
./scripts/test_video_job.sh "<url>"
```

## Result Inspection

After each run, validate the saved result automatically with the helper script:

```bash
RESULT_PATH="$(ls -t artifacts/test-runs/*-result.json | head -1)"
PORT="${OVS_TEST_PORT:-8010}"
VALIDATE_ARGS=(
  --result "${RESULT_PATH}"
  --backend-log "artifacts/test-runs/backend-${PORT}.log"
  --expect-study-pack
)
```

Add flags based on the run:

- If provider is `mlx` or `omlx`, append `--expect-llm-artifacts`
- If provider is `omlx`, append `--expect-omlx-request`
- If `--allow-section-refinement` was passed, append `--allow-section-refinement`
- If `--expect-timestamps` was passed, append `--expect-timestamp-markdown`

Then run:

```bash
python3 ./scripts/validate_e2e_run.py "${VALIDATE_ARGS[@]}"
```

The validator checks:
- completed status
- non-empty chapters, transcript segments, bilingual summaries, highlights
- transcript artifacts
- optional study-pack structure and artifact files
- optional timestamp rendering in `study_guide.md`
- current hierarchical artifact layout
- oMLX request artifacts when applicable
- warning/error/fallback lines in the backend log

## Frontend Validation

Unless `--no-frontend` is passed, run automated frontend checks after the backend validation succeeds.

```bash
cd frontend
npx tsc --noEmit --skipLibCheck
npx vite build
```

If the repo has a frontend test script, run it too:

```bash
npm run test --if-present
npm run test:e2e --if-present
```

If there is no frontend test script yet, report that the automated frontend coverage is currently limited to build validation and recommend adding component/e2e tests instead of asking the user to click around manually.

Only start a frontend dev server if the user explicitly asks for browser verification. When doing so, wire it to the smoke-test backend port:

```bash
VITE_API_BASE_URL="http://127.0.0.1:${PORT}" npx vite --port 5173
```

## Output Format

For each URL, report:

```
## <video-title> (<url>)

| Field | Value |
|---|---|
| Status | completed / failed |
| Provider | omlx / mlx / fallback |
| Chapters | N |
| Transcript source | captions / asr / mixed |
| Validation | pass / fail |
| Frontend build | pass / fail / skipped |

### Study Pack
| Field | Value |
|---|---|
| Present | yes/no |
| Learning objectives | N |
| Sections | N |
| Final takeaways | N |
| Timestamp markdown | yes/no/not-checked |

### Artifacts
- transcript_raw_path: yes/no
- transcript_normalized_path: yes/no
- summarizer prompts/raw output: yes/no
- oMLX requests: yes/no/not-applicable
- study_pack_path: yes/no
- study_guide_path: yes/no

### Warnings
(any warnings or errors from the backend log)
```

## Multiple URLs

If multiple URLs are provided, run them sequentially (they share GPU resources). Present each result separately, then a final summary table.

## Error Handling

- If the smoke test script fails, show the last 30 lines of the backend log
- If the validator fails, report each failed assertion clearly and stop claiming success
- If the oMLX server is unreachable, note whether fallback to rule-based worked
- If ASR is needed but mlx-whisper is not installed, tell the user how to install it
- If `study_pack` is null despite `OVS_ENABLE_STUDY_PACK=true`, check for `study_pack_error.txt` in the artifact directory and report the error
- If frontend build fails, show the TypeScript / Vite errors
- Do not replace automated checks with manual inspection unless the user explicitly asks for browser verification
