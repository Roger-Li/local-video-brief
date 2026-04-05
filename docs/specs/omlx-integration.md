# OMLX Integration V3

## Summary
- Add `omlx` as a new summarizer provider behind the existing `SummaryGenerator` interface, with no changes to pipeline stages, API contracts, or result payload shape.
- Scope v1 to OpenAI-compatible `POST /v1/chat/completions` only.
- Preserve current resilience: OMLX runtime failures fall back to the existing rule-based summarizer so jobs still complete.

## Implementation Changes
- In [backend/app/core/config.py](backend/app/core/config.py):
  - Add `summarizer_provider` resolved from `OVS_SUMMARIZER_PROVIDER=fallback|mlx|omlx`.
  - Resolution order:
    - explicit `OVS_SUMMARIZER_PROVIDER` wins
    - else legacy `OVS_ENABLE_MLX_SUMMARIZER=true` maps to `mlx`
    - else `fallback`
  - Add `OVS_OMLX_BASE_URL`, required when provider is `omlx`; normalize with trailing slash stripped so requests always use `f"{base_url}/chat/completions"`.
  - Add `OVS_OMLX_MODEL`, required when provider is `omlx`; no default.
  - Add `OVS_OMLX_API_KEY`, optional bearer token.
  - Add `OVS_OMLX_TIMEOUT_SECONDS`, default `180`.
  - Validate provider value and required OMLX fields in settings initialization when `provider=omlx`.
- In [backend/app/services/summarizer.py](backend/app/services/summarizer.py):
  - Extract shared module-level helpers:
    - prompt builder returning `(system_msg, user_msg)`
    - JSON extraction / cleanup
    - shared dynamic `max_tokens` calculation using the current formula `max(OVS_SUMMARIZER_MAX_TOKENS, 1024 * chapter_count + 1024)`
  - Keep `RuleBasedSummaryGenerator`.
  - Keep `MlxQwenSummaryGenerator` using `tokenizer.apply_chat_template(enable_thinking=False)`.
  - Add `OmlxSummaryGenerator` using `httpx` sync client:
    - send `model`, `messages`, `max_tokens`, `stream=false`
    - messages array is the structured `system` + `user` output from the shared prompt builder
    - do not call chat-template formatting
    - extract text from `response["choices"][0]["message"]["content"]`
    - treat timeouts, connection failures, non-200 responses, malformed response JSON, missing content, and invalid model output JSON as runtime failures that trigger rule-based fallback
  - Save artifacts:
    - `summarizer_prompt.txt`
    - `summarizer_request.json` containing request body only, never headers
    - `summarizer_raw_output.txt`
  - Add `create_summary_generator(settings)` in this module:
    - `fallback` returns rule-based
    - `mlx` returns MLX generator
    - `omlx` returns OMLX generator
    - missing `httpx` for `omlx` raises a clear startup error
- In [backend/app/main.py](backend/app/main.py):
  - Replace direct `MlxQwenSummaryGenerator(settings)` construction with `create_summary_generator(settings)`.
- In [pyproject.toml](pyproject.toml):
  - Add `omlx = ["httpx>=0.28.0"]` to optional dependencies.
  - Keep `httpx` in `dev` so tests remain easy to run.
- In [scripts/test_video_job.sh](scripts/test_video_job.sh):
  - Add `OVS_TEST_SUMMARIZER_PROVIDER`.
  - Preserve `OVS_TEST_ENABLE_MLX_SUMMARIZER=true` as backward-compatible shorthand for `mlx` only when provider is unset.
  - Print effective summarizer provider plus redacted OMLX config presence.
- Update docs:
  - [.env.example](.env.example) with `OVS_SUMMARIZER_PROVIDER`, `OVS_OMLX_BASE_URL`, `OVS_OMLX_MODEL`, `OVS_OMLX_API_KEY`, `OVS_OMLX_TIMEOUT_SECONDS`
  - [README.md](README.md) with provider-selection and OMLX usage
  - [CLAUDE.md](CLAUDE.md) with OMLX assumptions and summarizer notes
  - [AGENTS.md](AGENTS.md) only if its repo instructions should mention the new summarizer provider and smoke-test mode; skip unrelated edits

## Test Plan
- Extend [backend/tests/test_config.py](backend/tests/test_config.py) for:
  - provider resolution
  - legacy `OVS_ENABLE_MLX_SUMMARIZER` compatibility
  - invalid provider rejection
  - required OMLX field validation
  - base URL normalization
  - timeout parsing
- Add [backend/tests/test_summarizer.py](backend/tests/test_summarizer.py) covering:
  - OMLX success with standard OpenAI chat-completions payload
  - fallback on timeout
  - fallback on connection error
  - fallback on 401
  - fallback on 500
  - fallback on malformed API response
  - fallback on bad model JSON output
  - artifact creation
  - factory selection for `fallback`, `mlx`, and `omlx`
- Keep existing backend tests passing unchanged.

## Verification
- Bootstrap env for implementation-time verification with `uv sync --extra dev` and `uv sync --extra omlx`; add `--extra mlx` when testing the MLX path.
- Verify in this order:
  1. `OVS_SUMMARIZER_PROVIDER=fallback ./scripts/test_video_job.sh`
  2. `OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh` on a caption-backed URL
  3. same OMLX settings plus `OVS_ENABLE_MLX_ASR=true` on a captionless or weak-caption URL
  4. stop OMLX or use a bad key and confirm the job still completes with rule-based fallback
- Acceptance criteria:
  - completed jobs retain the current result schema
  - OMLX-generated summaries are returned when the server is healthy
  - OMLX request/output artifacts are written
  - explicit `provider=omlx` misconfiguration fails fast at startup
  - runtime OMLX failures degrade cleanly to rule-based summaries

## Assumptions
- v1 supports only OpenAI-compatible OMLX chat completions.
- v1 does not retry OMLX calls; immediate fallback is intentional.
- Output sizing uses the same dynamic `max_tokens` formula for MLX and OMLX.
- ASR remains unchanged and stays on `mlx-whisper`.
