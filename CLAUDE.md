# CLAUDE.md

## Purpose

This repository builds a local-first video summary tool for Apple Silicon Macs. It accepts video URLs, prefers captions, falls back to local ASR, and produces bilingual summaries.

## Current Architecture

- Backend: FastAPI app in `backend/app`
- Frontend: React/Vite app in `frontend`
- Persistence: SQLite in `data/local_video_brief.sqlite3`
- Artifacts: local files under `artifacts/`
- Smoke test entrypoint: `scripts/test_video_job.sh`

## Working Assumptions

- The backend auto-loads `.env` from the repo root.
- Successful smoke-test runs should work without the frontend.
- For real provider tests, prefer `scripts/test_video_job.sh` over ad hoc curl sequences because it forces the required ASR flags and captures logs and outputs.
- `OVS_ENABLE_MLX_ASR=true` is required for videos without usable captions.
- `OVS_ENABLE_MLX_SUMMARIZER=true` is optional for smoke tests; the fallback summarizer is acceptable for pipeline validation.
- The smoke-test script accepts `OVS_TEST_PYTHON` to override the Python interpreter (e.g., `OVS_TEST_PYTHON=$HOME/ml-env/bin/python`).

## Caption Fetch Policy

- Try caption languages one at a time.
- Prefer English subtitle variants first.
- If English is found, stop trying other subtitle languages.
- If English is unavailable, try Chinese variants.
- If Chinese is unavailable, try other requested/preferred languages.
- Partial subtitle failures must not fail the job if a usable subtitle file was already retrieved.

## Testing Expectations

- Run backend tests with `python3 -m pytest backend/tests`.
- For real end-to-end validation, run:

```bash
./scripts/test_video_job.sh
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"
```

- Successful smoke-test outputs are written to `artifacts/test-runs/<job-id>-result.json`.

## Summarizer Notes

- The MLX summarizer uses chat template formatting via `tokenizer.apply_chat_template()`. Prompt construction lives in `summarizer.py._build_prompt()` (returns system/user message tuple).
- Qwen3.5 models have a "thinking" mode; `/no_think` is appended to the user message to suppress it. The `_extract_json()` method also strips `<think>` blocks and markdown fences as a safety net.
- `max_tokens` is dynamic: `max(OVS_SUMMARIZER_MAX_TOKENS, 512 * chapters + 512)`.
- Only essential metadata fields (title, description, duration, upload_date, channel, tags) are passed to the prompt — the full yt-dlp dump is too large.

## Known Limitations

- Provider rate limits can still block extraction entirely.
- There is no auth, cloud sync, OCR, diarization, or Q&A flow in this repo.

## Editing Guidance

- Keep the app local-first.
- Preserve the current service boundaries in `backend/app/services`.
- Do not replace the smoke-test script with a manual-only workflow.
- Avoid coupling provider-specific logic into API handlers; keep it inside service adapters.
