# Per-Job DeepSeek Summarizer Selection

## Summary
- DeepSeek’s docs confirm an OpenAI-format API at `https://api.deepseek.com`, using `POST /chat/completions`, Bearer auth, and current models `deepseek-v4-flash` / `deepseek-v4-pro`. The older `deepseek-chat` and `deepseek-reasoner` aliases are deprecated on **July 24, 2026**. Sources: [Quick Start](https://api-docs.deepseek.com/), [Chat API](https://api-docs.deepseek.com/api/create-chat-completion), [Models](https://api-docs.deepseek.com/quick_start/pricing), [JSON Output](https://api-docs.deepseek.com/guides/json_mode).
- Add DeepSeek as a first-class remote summarizer, not by simply pointing the current `omlx` provider at DeepSeek. The existing oMLX request sends `chat_template_kwargs`, while DeepSeek should receive `thinking` / `response_format` fields instead.
- Because the desired behavior is per-job selection, frontend changes are needed: add a Summarizer selector in Options with local oMLX and DeepSeek API, plus a DeepSeek model dropdown defaulting to `deepseek-v4-flash`.

## Backend / API Changes
- Extend settings with `OVS_DEEPSEEK_API_KEY`, `OVS_DEEPSEEK_BASE_URL=https://api.deepseek.com`, `OVS_DEEPSEEK_MODEL=deepseek-v4-flash`, and `OVS_DEEPSEEK_TIMEOUT_SECONDS=600`; allow `OVS_SUMMARIZER_PROVIDER=deepseek` as a server default.
- Add job option fields:
  - `summarizer_provider_override`: allowed values `omlx` or `deepseek`.
  - `deepseek_model`: allowed values `deepseek-v4-flash` or `deepseek-v4-pro`.
- Refactor the remote summarizer path so oMLX and DeepSeek share the existing chunking, hierarchical, prompt, fallback, and power-mode logic, while each provider owns its request body.
- DeepSeek request policy:
  - Use `POST {deepseek_base_url}/chat/completions`.
  - Send `Authorization: Bearer <key>`, never store/log the key.
  - Send `model`, `messages`, `max_tokens`, and `stream: false`.
  - Send `thinking: {"type": "disabled"}` by default for predictable summaries.
  - For structured JSON summary calls, send `response_format: {"type": "json_object"}`; omit it for power-mode prose and plain chunk-note calls.
- Add a routing `SummaryGenerator` that dispatches per job to oMLX or DeepSeek when the override is present; otherwise it uses the server default provider.
- Extend `GET /config` with `default_summarizer_provider` and `available_summarizer_providers`, including DeepSeek model choices only when `OVS_DEEPSEEK_API_KEY` is configured.
- No DB migration is needed; new per-job choices live in the existing `options` JSON column.

## Frontend Changes
- In `JobForm.tsx`, add a provider control inside the existing Options → Summarization area.
- Show `Local oMLX` when configured; keep its existing free-form model override field.
- Show `DeepSeek API` when configured; show a select menu for `deepseek-v4-flash` and `deepseek-v4-pro`, defaulting to Flash.
- Submit `summarizer_provider_override: "deepseek"` and `deepseek_model` only when DeepSeek is selected; preserve the current no-options payload behavior when the panel is untouched.
- Update frontend API types and CSS in the existing vanilla CSS file.

## Test Plan
- Backend unit tests for DeepSeek settings, provider validation, config endpoint provider list, job option validation, request body shape, JSON-mode behavior, power-mode non-JSON behavior, and router dispatch.
- Frontend tests for provider selector rendering and submitted payloads for local oMLX, DeepSeek Flash, and DeepSeek Pro.
- Verification commands:
  - `python3 -m pytest backend/tests`
  - `cd frontend && npx vitest run`
  - `cd frontend && npx vite build`
- Optional live smoke test once an API key is available:
  - `OVS_TEST_SUMMARIZER_PROVIDER=deepseek OVS_DEEPSEEK_API_KEY=... ./scripts/test_video_job.sh`

## Assumptions
- DeepSeek is opt-in and only appears in the UI when `OVS_DEEPSEEK_API_KEY` is set.
- Local oMLX remains the default in your current setup unless `OVS_SUMMARIZER_PROVIDER=deepseek` is explicitly configured.
- Runtime DeepSeek failures follow the existing guided-summary behavior: log and fall back to rule-based output; power mode continues to fail the job rather than silently discarding the user’s custom brief.
