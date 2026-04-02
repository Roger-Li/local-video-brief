---
name: test-e2e
description: Run end-to-end pipeline tests against real video URLs to validate feature changes. Use when the user wants to test with real videos, validate summarization, or verify pipeline behavior after code changes.
argument-hint: [video-url] [--provider fallback|mlx|omlx] [--timeout 300] [--no-frontend]
disable-model-invocation: true
---

# E2E Pipeline Test

Run end-to-end tests against real video URLs to validate the full pipeline — backend summarization, study pack generation, and frontend rendering.

## Arguments

- `$ARGUMENTS` contains the raw arguments string
- Parse video URLs (anything starting with `http`) and flags from the arguments
- Supported flags:
  - `--provider <fallback|mlx|omlx>` — summarizer provider (default: reads from `.env` or falls back to `fallback`)
  - `--timeout <seconds>` — oMLX timeout (default: 300)
  - `--asr` — force enable MLX ASR even if captions are available
  - `--no-frontend` — skip frontend build check and Playwright UI validation
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

## Execution

Run each video URL through the smoke test. Always set `OVS_ENABLE_STUDY_PACK=true` to exercise the study pack pipeline:

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

After each test completes, inspect the result:

1. Find the result JSON: `ls -t artifacts/test-runs/*-result.json | head -1`

2. Print a compact validation summary:
   - Number of chapters
   - For each chapter: time range, title, first 80 chars of English summary
   - Overall summary snippet (first 120 chars)
   - Highlights list
   - Whether summaries are LLM-generated (substantive bilingual) or rule-based (transcript extraction)

3. **Study pack validation** (always checked since `OVS_ENABLE_STUDY_PACK=true`):
   - Verify `study_pack` field is present and non-null in result JSON
   - Check `study_pack.version`, `study_pack.format`
   - Count `learning_objectives`, `sections`, `final_takeaways`
   - Verify section count matches chapter count (1:1 in v1)
   - Verify each section has `start_s`, `end_s`, `title`, `summary_en`, `summary_zh`, `key_points`
   - Verify section timestamps are monotonically increasing

4. Check artifacts exist:
   - `artifacts/<job-id>/summarizer_prompt.txt`
   - `artifacts/<job-id>/summarizer_request.json` (oMLX only)
   - `artifacts/<job-id>/summarizer_raw_output.txt` (LLM providers only)
   - `artifacts/<job-id>/transcript_raw.json`
   - `artifacts/<job-id>/transcript_normalized.json`
   - `artifacts/<job-id>/study_pack.json`
   - `artifacts/<job-id>/study_guide.md`

5. Check the backend log for warnings/errors:
   ```bash
   grep -E "WARNING|ERROR|fallback|timed out" artifacts/test-runs/backend-*.log
   ```

## Frontend Validation

Unless `--no-frontend` is passed, run frontend validation after the backend pipeline completes. This requires a completed job with `study_pack` present in the result JSON.

### Step 1: Build check

```bash
cd frontend && npm install && npx tsc --noEmit --skipLibCheck && npx vite build
```

Report pass/fail. If the build fails, show the errors and skip the dev server step.

### Step 2: Start frontend for manual UI inspection

The smoke test leaves the backend running. Start the frontend dev server so the user can open the browser and interact with the result UI:

1. Start the frontend dev server in the background:
   ```bash
   cd frontend && npx vite --port 5173 &
   ```
   Wait a few seconds for it to start, then verify it responds:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
   ```

2. Print a clear message telling the user what to do:
   ```
   Frontend is running at http://localhost:5173
   Backend is running at http://127.0.0.1:8000

   To verify the UI:
   1. Open http://localhost:5173 in your browser
   2. Paste the video URL and submit
   3. Wait for the job to complete
   4. Check: three tabs appear (Summary | Study Guide | Transcript)
   5. Click "Study Guide" — verify learning objectives, sections, and takeaways render
   6. Click "Export Markdown" — a .md file should download
   7. Click "Transcript" — verify transcript rows render

   Both servers will keep running until you stop them.
   To stop: kill the backend and frontend processes, or press Ctrl+C.
   ```

3. Do NOT stop the servers — leave them running for the user to inspect.

## Output Format

Present results as a table per video:

```
## <video-title> (<url>)

| Field | Value |
|---|---|
| Status | completed / failed |
| Provider | omlx / mlx / fallback |
| Chapters | N |
| Source | captions / asr / mixed |
| Summarizer | LLM / rule-based |
| Pipeline time | Xs |

### Chapters
- [0-120s] Chapter Title — first 80 chars of summary...
- [120-300s] Chapter Title — first 80 chars of summary...

### Overall
summary snippet...

### Study Pack
| Field | Value |
|---|---|
| Present | yes/no |
| Learning objectives | N |
| Sections | N (matches chapters: yes/no) |
| Final takeaways | N |
| study_pack.json | yes/no (size) |
| study_guide.md | yes/no (size) |

### Artifacts
- prompt: yes/no
- request: yes/no (omlx only)
- raw_output: yes/no
- transcripts: raw=yes normalized=yes
- study_pack.json: yes/no
- study_guide.md: yes/no

### Frontend
| Check | Result |
|---|---|
| TypeScript build | pass/fail |
| Vite build | pass/fail |
| Dev server running | yes/no (http://localhost:5173) |
| Backend still running | yes/no (http://127.0.0.1:8000) |

### Warnings
(any warnings or errors from the backend log)
```

## Multiple URLs

If multiple URLs are provided, run them sequentially (they share GPU resources). Present each result separately, then a final summary table.

## Error Handling

- If the smoke test script fails, show the last 30 lines of the backend log
- If the oMLX server is unreachable, note whether fallback to rule-based worked
- If ASR is needed but mlx-whisper is not installed, tell the user how to install it
- If `study_pack` is null despite `OVS_ENABLE_STUDY_PACK=true`, check for `study_pack_error.txt` in the artifacts directory and report the error
- If the frontend build fails, show the TypeScript / Vite errors and skip the dev server step
- If the frontend dev server doesn't start (curl check fails), report the error
