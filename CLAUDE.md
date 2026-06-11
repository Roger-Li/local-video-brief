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

## Dev Commands

- Start full stack (backend + frontend): `./scripts/dev_server.sh`
- Backend only: `uvicorn backend.app.main:app --host 127.0.0.1 --port 8010`
- Frontend only: `cd frontend && npm run dev`
- Backend tests: `python3 -m pytest backend/tests` (291 tests; 2 of them assume DeepSeek is unconfigured and fail when `.env` sets `OVS_DEEPSEEK_API_KEY`)
- Frontend tests: `cd frontend && npx vitest run` (`npm run test` may fail if vitest is not on PATH)
- Build frontend: `cd frontend && npx vite build` (`npm run build` runs `tsc` first, which has pre-existing type errors in node_modules from dependency version mismatches — use `npx vite build` to verify the production bundle directly)

## Key Entry Points

- `backend/app/main.py` — FastAPI app factory, startup hooks, summary generator init
- `backend/app/core/config.py` — `Settings` model, all env var definitions
- `backend/app/services/pipeline.py` — Job processing pipeline orchestration
- `backend/app/services/summarizer.py` — Summary provider implementations and factory
- `frontend/src/App.tsx` — Root React component
- `frontend/src/components/JobForm.tsx` — Job submission form with options UI

## Working Assumptions

- The backend auto-loads `.env` from the repo root.
- Successful smoke-test runs should work without the frontend.
- For real provider tests, prefer `scripts/test_video_job.sh` over ad hoc curl sequences because it forces the required ASR flags and captures logs and outputs.
- `OVS_ENABLE_MLX_ASR=true` is required for videos without usable captions.
- `OVS_SUMMARIZER_PROVIDER` selects the summarizer: `fallback` (rule-based), `mlx` (in-process mlx-lm), `omlx` (remote oMLX server), or `deepseek` (DeepSeek API). If unset, falls back to `mlx` when `OVS_ENABLE_MLX_SUMMARIZER=true`, else `fallback`.
- `OVS_ENABLE_MLX_SUMMARIZER=true` is a legacy shorthand for `OVS_SUMMARIZER_PROVIDER=mlx`; the fallback summarizer extracts transcript sentences only.
- When `provider=omlx`, `OVS_OMLX_BASE_URL` and `OVS_OMLX_MODEL` are required. Optional: `OVS_OMLX_API_KEY`, `OVS_OMLX_TIMEOUT_SECONDS` (default 180).
- When `provider=deepseek`, `OVS_DEEPSEEK_API_KEY` is required. Optional: `OVS_DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`), `OVS_DEEPSEEK_MODEL` (`deepseek-v4-flash` | `deepseek-v4-pro`, default flash), `OVS_DEEPSEEK_TIMEOUT_SECONDS` (default 600). DeepSeek is also offered as a per-job provider whenever the API key is set, regardless of the default provider.
- `OVS_WORKER_CONCURRENCY` (default 2) sets the job worker pool size. GPU-bound stages (mlx-whisper ASR, in-process MLX generation) are serialized by a process-wide GPU lock, so parallelism mainly speeds up network-bound stages and remote-provider summarization.
- `OVS_ENABLE_TRANSCRIPT_NORMALIZATION=true` (default) runs dedup/cleanup; set to `false` to bypass.
- The smoke-test script accepts `OVS_TEST_PYTHON` to override the Python interpreter (e.g., `OVS_TEST_PYTHON=$HOME/ml-env/bin/python`).
- `OVS_COOKIES_FILE` points to a Netscape cookies.txt file for yt-dlp authentication (e.g., bilibili). `OVS_COOKIES_FROM_BROWSER` is an alternative that reads cookies from a browser directly (e.g., `brave`). File takes precedence if browser is unset; browser takes precedence if both are set. Required for bilibili videos.

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

- For real end-to-end validation, run:

```bash
./scripts/test_video_job.sh
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"
OVS_TEST_ENABLE_MLX_SUMMARIZER=true ./scripts/test_video_job.sh "https://youtu.be/j190mwiVlwA"
OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh
OVS_TEST_POWER_MODE=true OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh
OVS_TEST_WORKER_CONCURRENCY=2 ./scripts/test_video_job.sh "<url1>" "<url2>"   # parallel batch
```

- Successful smoke-test outputs are written to `artifacts/test-runs/<job-id>-result.json`.
- Test fixtures live in `backend/tests/fixtures/` (VTT samples) and `backend/tests/fixtures/golden/` (reference transcripts and summaries).

## Summarizer

- Four providers behind the `SummaryGenerator` protocol: `RuleBasedSummaryGenerator`, `MlxQwenSummaryGenerator`, `OmlxSummaryGenerator`, `DeepseekSummaryGenerator`.
- `create_summary_generator(settings)` factory in `summarizer.py` selects the provider; called from `main.py` at startup. When two or more providers are configured it returns a `RoutingSummaryGenerator` that dispatches per job via `summarizer_provider_override`.
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
- Ten options: `enable_study_pack`, `enable_transcript_normalization`, `style_preset`, `focus_hint`, `omlx_model_override`, `power_mode`, `power_prompt`, `strategy_override`, `summarizer_provider_override`, `deepseek_model`. `null` = use server default.
- `summarizer_provider_override` switches between *remote* providers (`omlx`/`deepseek`) per job, dispatched by `RoutingSummaryGenerator`. The `mlx` provider remains startup-only because it loads a multi-GB model into GPU memory.
- Frontend: collapsible "Options" section in `JobForm.tsx` below the URL field. Prompt controls (presets, focus hint, model override) are capability-gated via `GET /config`.
- The URL field is a multi-line textarea (one URL per line); all options apply to every job in the batch. Submitted jobs appear in a job list panel (`GET /jobs`, polled while any job is active) with per-job result selection.

## Configurable Prompts

- Style presets (`default`, `detailed`, `concise`, `technical`, `academic`) in `backend/app/core/style_presets.py`. Each preset owns sentence-length guidance, a system suffix, and a token-budget multiplier.
- The `default` preset reproduces the original hardcoded prompt text byte-for-byte.
- Focus hints go in user messages (not system) to avoid conflicting with JSON schema enforcement. They are threaded through all prompt paths: single-shot, chunk notes, chapter synthesis, and overall synthesis.
- Token multiplier is applied to `compute_max_tokens()`, `_step_tokens()`, and `_chunk_note_tokens()`. Single-shot tokens are clamped to `base + summarizer_max_tokens` to avoid exceeding provider completion-token limits.
- `omlx_model_override` changes the `model` field in oMLX HTTP requests. Ignored by MLX and fallback providers.
- `GET /config` returns capability flags (`supports_prompt_customization`, `model_override_allowed`) so the frontend hides inert controls. For MLX, checks runtime availability of `mlx_lm` before advertising support.
- The API always accepts and stores prompt options regardless of provider. Only LLM providers act on them.

## Power Mode (v3)

- Opt-in expert path: users see and edit the summarization brief, optionally force single-shot, and get prose/markdown output instead of structured JSON.
- `power_mode: true` on `JobOptions` enables it. `power_prompt` is the user-edited brief (max 2000 chars). `strategy_override` is `"auto"` or `"force_single_shot"`.
- Power mode produces `raw_summary_text` (prose) in the result. `chapters` and `overall_summary` are empty stubs for schema compat.
- `GET /config` returns `supports_power_mode` (same gate as `supports_prompt_customization`). Hidden for fallback provider.
- `GET /config/power-prompt-default` returns a default brief derived from preset + focus hint via `build_power_default_brief()`.
- The system message (`_POWER_MODE_SYSTEM`) is a fixed constant requesting markdown output. The user's brief goes in the user message.
- Auto strategy routes to per-chapter/hierarchical paths using power-specific prompts. `force_single_shot` bypasses strategy routing.
- Study pack generation is skipped for power mode jobs. Fallback provider silently ignores `power_mode`.
- Smoke test: `OVS_TEST_POWER_MODE=true OVS_TEST_STRATEGY_OVERRIDE=force_single_shot ./scripts/test_video_job.sh`.

## Known Limitations

- Provider rate limits can still block extraction entirely.
- There is no auth, cloud sync, OCR, diarization, or Q&A flow in this repo.
- Transcript normalization handles most rolling-caption patterns but may leave residual duplication in edge cases.
- Jobs run in parallel up to `OVS_WORKER_CONCURRENCY` (default 2). GPU-bound stages (ASR, in-process MLX summarization) are serialized by a process-wide GPU lock, so `mlx`-provider jobs gain little wall-clock speedup from parallelism; remote providers (`omlx`/`deepseek`) and the fallback overlap fully.
- The study pack is fully deterministic (no LLM calls). Section refinement splits oversized chapters but additional sub-sections use extracted transcript sentences, not LLM summaries.
- Chaptering splits purely on duration (8 min) and gap (45s) thresholds with no semantic awareness. Continuous lectures without natural pauses get uniform time-based chapters.

## Editing Guidance

- Keep the app local-first.
- Preserve the current service boundaries in `backend/app/services`.
- Do not replace the smoke-test script with a manual-only workflow.
- Avoid coupling provider-specific logic into API handlers; keep it inside service adapters.
- Frontend styles live in a single `frontend/src/styles.css` file (vanilla CSS, no Tailwind/preprocessor). Theme colors use CSS custom variables in `:root` but many component rules also contain hardcoded `rgba(...)` accent references — a full theme swap requires rewriting the entire file.
- Google Fonts loaded in `frontend/index.html`: IBM Plex Sans (body) and DM Serif Display (hero heading).
