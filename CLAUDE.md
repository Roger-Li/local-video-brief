# CLAUDE.md

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
| Summarizer | `services/summarizer.py` | MLX / oMLX / rule-based summarization |
| Pipeline | `services/pipeline.py` | Orchestrates all stages, persists artifacts |

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
- Rolling-caption dedup: merges adjacent caption segments with token suffix/prefix overlap >= 0.75 ratio and <= 2s gap; also detects sliding-window patterns via substring prefix matching.
- Sound-marker blocklist: strips `[Music]`, `[Applause]`, `[♪]`, etc.; preserves `[inaudible]`, `[laughter]`, `[crosstalk]`.
- Short-fragment merge: only for caption-sourced segments (ASR segments are left intact).
- Zero-segment fallback: if normalization eliminates all segments, falls back to raw parsed segments.
- Raw and normalized transcripts are saved as JSON artifacts per job.
- `transcript_stats` is exposed in the API result with segment counts, dedup stats, and source mode.

## Testing Expectations

- Run backend tests with `python3 -m pytest backend/tests` (88 tests).
- For real end-to-end validation, run:

```bash
./scripts/test_video_job.sh
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"
OVS_TEST_ENABLE_MLX_SUMMARIZER=true ./scripts/test_video_job.sh "https://youtu.be/j190mwiVlwA"
OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh
```

- Successful smoke-test outputs are written to `artifacts/test-runs/<job-id>-result.json`.
- Test fixtures live in `backend/tests/fixtures/` (VTT samples) and `backend/tests/fixtures/golden/` (reference transcripts and summaries).

## Summarizer Notes

- Three providers behind the `SummaryGenerator` protocol: `RuleBasedSummaryGenerator`, `MlxQwenSummaryGenerator`, `OmlxSummaryGenerator`.
- `create_summary_generator(settings)` factory in `summarizer.py` selects the provider; called from `main.py` at startup.
- Shared module-level helpers: `build_summarizer_prompt()`, `extract_json()`, `compute_max_tokens()`.
- The MLX summarizer uses chat template formatting via `tokenizer.apply_chat_template(enable_thinking=False)` to suppress Qwen3.5 thinking mode.
- The oMLX summarizer sends structured `system`/`user` messages to `{base_url}/chat/completions` (OpenAI-compatible); the server handles chat templating.
- `extract_json()` uses `json.JSONDecoder(strict=False).raw_decode()` to handle trailing characters and tolerate unescaped control characters in LLM output; strips `<think>` blocks as a safety net.
- Only essential metadata fields (title, description, duration, upload_date, channel, tags) are passed to the prompt.
- All providers fall back to rule-based output on failure. oMLX runtime failures (timeout, HTTP errors, bad JSON) trigger fallback; config errors (missing URL/model) fail at startup.
- The rule-based fallback caps summaries at 500 chars to prevent transcript dumps when text lacks sentence punctuation.

### Hierarchical Summarization (MLX + oMLX)

- Both LLM providers use a hierarchical per-chapter flow instead of a single monolithic prompt.
- For each chapter: `chunk_segments()` groups transcript segments by `summarizer_max_input_chars` budget without splitting mid-segment.
- Single-chunk chapters go directly to `_synthesize_chapter()` (the raw segment text is passed as the "note").
- Multi-chunk chapters first produce a plain-English note per chunk via `_summarize_chunk()`, then synthesize the chapter from those notes.
- After all chapters: `_synthesize_overall()` produces the overall summary from chapter summaries.
- Per-step token limits are derived from `settings.summarizer_max_tokens`: chunk notes get `max(512, max_tokens // 4)`, synthesis steps get `max(1024, max_tokens // 2)`.
- `_call_llm()` / `_call_omlx()` are extracted helpers that handle chat template formatting, artifact saving, and generation for each LLM call.
- `build_summarizer_prompt()` is retained for backward compatibility but is no longer on the main code path.
- Artifacts saved per chapter: `ch{N}/summarizer_chapter_synthesis_prompt.txt`, `ch{N}/summarizer_chapter_synthesis_raw_output.txt`, and (oMLX) `ch{N}/summarizer_chapter_synthesis_request.json`.
- Root-level artifacts: `summarizer_overall_synthesis_prompt.txt`, `summarizer_overall_synthesis_raw_output.txt`.
- `chunk_notes.json` is saved when any chapter has multiple chunks.
- Progress sub-stages reported via `progress_callback`: `summarizing_chunks` → `synthesizing_chapters` → `synthesizing_overall`.

### Text Utilities

- `chunk_segments(segments, max_chars)` in `utils/text.py`: groups transcript segments into chunks by char budget, never splitting mid-segment. If a single segment exceeds `max_chars`, it becomes its own chunk.
- `segments_to_text(segments)`: joins segment texts with spaces.

## Study Pack

- Optional `study_pack` in the job result payload, behind `OVS_ENABLE_STUDY_PACK=false` (default off).
- v1 is fully deterministic — no LLM calls. Transforms existing chapter summaries and overall summary into a structured study guide.
- `StudyPackGenerator` in `services/study_pack.py`; `StudySection`, `StudyPack` Pydantic models in `schemas/jobs.py`.
- Schema: `version`, `format`, `learning_objectives`, `sections[]` (one per chapter), `final_takeaways`.
- Section `start_s`/`end_s` are derived from authoritative chapter data (not LLM output), preventing timestamp drift.
- `learning_objectives`: up to 5 items from `overall_summary.highlights`, falling back to chapter titles.
- `final_takeaways`: reuses `overall_summary.highlights`.
- `render_study_guide_markdown()` produces standalone Markdown from `study_pack.json` via pure template rendering.
- Pipeline stage: `generating_study_pack` runs after summarizer, before `COMPLETED`. Failure-isolated — errors never fail the job.
- Artifacts: `study_pack.json`, `study_guide.md` persisted under `artifacts/<job-id>/`.
- API: `study_pack: null` in response when disabled or absent.

## Known Limitations

- Provider rate limits can still block extraction entirely.
- There is no auth, cloud sync, OCR, diarization, or Q&A flow in this repo.
- Transcript normalization handles most rolling-caption patterns but may leave residual duplication in edge cases.
- The summarizer worker processes jobs sequentially; concurrent submissions queue up.
- The hierarchical summarization path runs unconditionally on LLM providers — even short videos get N+1 LLM calls. A hybrid routing approach (single-shot for short videos, per-chapter for medium, full hierarchical for long) is proposed in `artifacts/plan/LECTURE_PLAN_V2_IMPLEMENTATION.md` as Phase A v2.
- Chaptering splits purely on duration (8 min) and gap (45s) thresholds with no semantic awareness. Continuous lectures without natural pauses get uniform time-based chapters.

## Editing Guidance

- Keep the app local-first.
- Preserve the current service boundaries in `backend/app/services`.
- Do not replace the smoke-test script with a manual-only workflow.
- Avoid coupling provider-specific logic into API handlers; keep it inside service adapters.

## Future Directions

- **Study pack quality (Phase B v2)**: Add `[MM:SS]` timestamps to markdown, differentiate `learning_objectives` from `final_takeaways`, optional section refinement for oversized chapters. See `artifacts/plan/LECTURE_PLAN_V2.md`.
- **Frontend study guide (Phase C)**: Tabbed result view (Summary | Study Guide | Transcript), `StudyGuideView` component, Markdown/HTML export. Depends on Phase B. See `artifacts/plan/LECTURE_PLAN_V2_IMPLEMENTATION.md`.
- **Hybrid summarization routing (Phase A v2)**: Route short videos through single-shot prompt, medium through per-chapter synthesis, long/dense through full hierarchical with chunk notes. Reduces LLM calls for short videos while preserving coverage for long lectures.
- **oMLX server for model hosting**: The `omlx` summarizer provider is implemented (v1, OpenAI-compatible, non-streaming). Future work: streaming support, retry-once for transient errors, and Anthropic-compatible endpoint support if needed.
- **Browser-integrated summarization**: Build a browser extension (Chrome/Firefox WebExtension API) that detects YouTube/bilibili video pages, triggers summary jobs against the local backend, and displays results in a sidebar overlay. This requires the backend to be running locally and the extension to communicate via `localhost` API. A Safari Web Extension variant would need a native app wrapper. Alternatively, a Tauri or Electron desktop app with an embedded webview could wrap the existing React frontend and add system-tray quick-access.
- **ASR server migration**: If ASR moves to a server, `mlx-audio` (with `/v1/audio/transcriptions`) is the better fit over oMLX, since oMLX does not expose audio transcription endpoints.
