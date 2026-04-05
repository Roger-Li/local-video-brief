# CLAUDE.md

See @docs/roadmap.md for future feature plans.

## Purpose

This repository builds a local-first video summary tool for Apple Silicon Macs. It accepts video URLs, prefers captions, falls back to local ASR, normalizes transcripts, and produces bilingual summaries.

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
- `OVS_SUMMARIZER_PROVIDER` selects the summarizer: `fallback` (rule-based), `mlx` (in-process mlx-lm), or `omlx` (remote oMLX server). If unset, falls back to `mlx` when `OVS_ENABLE_MLX_SUMMARIZER=true`, else `fallback`.
- `OVS_ENABLE_MLX_SUMMARIZER=true` is a legacy shorthand for `OVS_SUMMARIZER_PROVIDER=mlx`; the fallback summarizer extracts transcript sentences only.
- When `provider=omlx`, `OVS_OMLX_BASE_URL` and `OVS_OMLX_MODEL` are required. Optional: `OVS_OMLX_API_KEY`, `OVS_OMLX_TIMEOUT_SECONDS` (default 180).
- `OVS_ENABLE_TRANSCRIPT_NORMALIZATION=true` (default) runs dedup/cleanup; set to `false` to bypass.
- The smoke-test script accepts `OVS_TEST_PYTHON` to override the Python interpreter (e.g., `OVS_TEST_PYTHON=$HOME/ml-env/bin/python`).

## Caption Fetch Policy

- Try caption languages one at a time.
- Prefer English subtitle variants first.
- If English is found, stop trying other subtitle languages.
- If English is unavailable, try Chinese variants.
- If Chinese is unavailable, try other requested/preferred languages.
- Partial subtitle failures must not fail the job if a usable subtitle file was already retrieved.

## Transcript Normalization

- Runs between caption/ASR parsing and chaptering (the `normalizing_transcript` pipeline stage).
- Raw and normalized transcripts are saved as JSON artifacts per job. `transcript_stats` is exposed in the API result.
- If normalization eliminates all segments, falls back to raw parsed segments.

## Testing Expectations

- Run backend tests with `python3 -m pytest backend/tests` (157 tests).
- For real end-to-end validation, run:

```bash
./scripts/test_video_job.sh
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"
OVS_TEST_ENABLE_MLX_SUMMARIZER=true ./scripts/test_video_job.sh "https://youtu.be/j190mwiVlwA"
OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh
```

- Successful smoke-test outputs are written to `artifacts/test-runs/<job-id>-result.json`.
- Test fixtures live in `backend/tests/fixtures/` (VTT samples) and `backend/tests/fixtures/golden/` (reference transcripts and summaries).

## Summarizer

- Three providers behind the `SummaryGenerator` protocol: `RuleBasedSummaryGenerator`, `MlxQwenSummaryGenerator`, `OmlxSummaryGenerator`.
- `create_summary_generator(settings)` factory in `summarizer.py` selects the provider; called from `main.py` at startup.
- The MLX summarizer uses `tokenizer.apply_chat_template(enable_thinking=False)` to suppress Qwen3.5 thinking mode.
- All providers fall back to rule-based output on failure. oMLX runtime failures (timeout, HTTP errors, bad JSON) trigger fallback; config errors (missing URL/model) fail at startup.
- The rule-based fallback caps summaries at 500 chars to prevent transcript dumps when text lacks sentence punctuation.

## Study Pack

- Optional `study_pack` in the job result payload, behind `OVS_ENABLE_STUDY_PACK=false` (default off).
- Pipeline stage `generating_study_pack` runs after summarizer. Failure-isolated — errors never fail the job.
- Artifacts: `study_pack.json`, `study_guide.md` persisted under `artifacts/<job-id>/`.
- API: `study_pack: null` in response when disabled or absent.

## Per-Job Options

- Optional per-job overrides via `options` field on `CreateJobRequest`. When omitted, all settings fall back to server defaults.
- Two options: `enable_study_pack`, `enable_transcript_normalization`. `null` = use server default.
- `summarizer_provider` is **not** per-job — the MLX provider loads a multi-GB model into GPU memory at startup.
- Frontend: collapsible "Options" section in `JobForm.tsx` below the URL field.

## Known Limitations

- Provider rate limits can still block extraction entirely.
- There is no auth, cloud sync, OCR, diarization, or Q&A flow in this repo.
- Transcript normalization handles most rolling-caption patterns but may leave residual duplication in edge cases.
- The summarizer worker processes jobs sequentially; concurrent submissions queue up.
- The study pack is fully deterministic (no LLM calls). Section refinement splits oversized chapters but additional sub-sections use extracted transcript sentences, not LLM summaries.
- Chaptering splits purely on duration (8 min) and gap (45s) thresholds with no semantic awareness. Continuous lectures without natural pauses get uniform time-based chapters.

## Editing Guidance

- Keep the app local-first.
- Preserve the current service boundaries in `backend/app/services`.
- Do not replace the smoke-test script with a manual-only workflow.
- Avoid coupling provider-specific logic into API handlers; keep it inside service adapters.
