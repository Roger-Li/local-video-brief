# AGENTS.md

## Purpose

This repository builds a local-first video summary tool for Apple Silicon Macs. It accepts video URLs, prefers captions, falls back to local ASR, normalizes transcripts, and produces bilingual summaries.

## Current Architecture

- Backend: FastAPI app in `backend/app`
- Frontend: React/Vite app in `frontend`
- Persistence: SQLite in `data/local_video_brief.sqlite3`
- Artifacts: local files under `artifacts/`
- Smoke test entrypoint: `scripts/test_video_job.sh`

### Pipeline Services

| Service | File | Purpose |
|---|---|---|
| Video source | `services/video_source.py` | yt-dlp inspection, caption fetch, audio download |
| Transcript provider | `services/transcript.py` | VTT parsing, tag stripping, segment extraction |
| Normalizer | `services/normalizer.py` | Rolling-caption dedup, markup cleanup, short-fragment merge |
| Chaptering | `services/chaptering.py` | Gap/duration-based splitting + density-aware repartitioning |
| Summarizer | `services/summarizer.py` | MLX LLM summarization with rule-based fallback |
| Pipeline | `services/pipeline.py` | Orchestrates all stages, persists artifacts |

## Working Assumptions

- The backend auto-loads `.env` from the repo root.
- Successful smoke-test runs should work without the frontend.
- For real provider tests, prefer `scripts/test_video_job.sh` over ad hoc curl sequences because it forces the required ASR flags and captures logs and outputs.
- `OVS_ENABLE_MLX_ASR=true` is required for videos without usable captions.
- `OVS_ENABLE_MLX_SUMMARIZER=true` is required for real summaries; the fallback summarizer extracts transcript sentences only.
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
- Rolling-caption dedup: merges adjacent caption segments with token suffix/prefix overlap >= 0.75 ratio and <= 2s gap; also detects sliding-window patterns via substring prefix matching.
- Sound-marker blocklist: strips `[Music]`, `[Applause]`, `[♪]`, etc.; preserves `[inaudible]`, `[laughter]`, `[crosstalk]`.
- Short-fragment merge: only for caption-sourced segments (ASR segments are left intact).
- Zero-segment fallback: if normalization eliminates all segments, falls back to raw parsed segments.
- Raw and normalized transcripts are saved as JSON artifacts per job.
- `transcript_stats` is exposed in the API result with segment counts, dedup stats, and source mode.

## Testing Expectations

- Run backend tests with `python3 -m pytest backend/tests` (24 tests).
- For real end-to-end validation, run:

```bash
./scripts/test_video_job.sh
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"
OVS_TEST_ENABLE_MLX_SUMMARIZER=true ./scripts/test_video_job.sh "https://youtu.be/j190mwiVlwA"
```

- Successful smoke-test outputs are written to `artifacts/test-runs/<job-id>-result.json`.
- Test fixtures live in `backend/tests/fixtures/` (VTT samples) and `backend/tests/fixtures/golden/` (reference transcripts and summaries).

## Summarizer Notes

- The MLX summarizer uses chat template formatting via `tokenizer.apply_chat_template(enable_thinking=False)` to suppress Qwen3.5 thinking mode.
- The prompt includes an explicit JSON schema example for the expected output structure.
- `_extract_json()` uses `json.JSONDecoder().raw_decode()` to handle trailing characters, and strips `<think>` blocks as a safety net.
- `max_tokens` is dynamic: `max(OVS_SUMMARIZER_MAX_TOKENS, 1024 * chapters + 1024)`.
- Only essential metadata fields (title, description, duration, upload_date, channel, tags) are passed to the prompt.
- Both the prompt and raw LLM output are saved as artifacts (`summarizer_prompt.txt`, `summarizer_raw_output.txt`) for debugging.
- The rule-based fallback caps summaries at 500 chars to prevent transcript dumps when text lacks sentence punctuation.

## Known Limitations

- Provider rate limits can still block extraction entirely.
- There is no auth, cloud sync, OCR, diarization, or Q&A flow in this repo.
- Transcript normalization handles most rolling-caption patterns but may leave residual duplication in edge cases.
- The summarizer worker processes jobs sequentially; concurrent submissions queue up.

## Editing Guidance

- Keep the app local-first.
- Preserve the current service boundaries in `backend/app/services`.
- Do not replace the smoke-test script with a manual-only workflow.
- Avoid coupling provider-specific logic into API handlers; keep it inside service adapters.

## Future Directions

- **oMLX server for model hosting**: Replace in-process `mlx-lm` loading with a local oMLX server (`/v1/chat/completions`) for consolidated model management, shared GPU memory across requests, and decoupled model config. This also enables swapping models without restarting the backend.
- **Browser-integrated summarization**: Build a browser extension (Chrome/Firefox WebExtension API) that detects YouTube/bilibili video pages, triggers summary jobs against the local backend, and displays results in a sidebar overlay. This requires the backend to be running locally and the extension to communicate via `localhost` API. A Safari Web Extension variant would need a native app wrapper. Alternatively, a Tauri or Electron desktop app with an embedded webview could wrap the existing React frontend and add system-tray quick-access.
- **ASR server migration**: If ASR moves to a server, `mlx-audio` (with `/v1/audio/transcriptions`) is the better fit over oMLX, since oMLX does not expose audio transcription endpoints.
