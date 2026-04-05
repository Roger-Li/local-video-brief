# Local Video Brief: Transcript Quality Hardening Plan V3

## Summary

The main quality gap is still the empty `normalizing_transcript` stage in [pipeline.py](backend/app/services/pipeline.py). This change should add a concrete transcript normalizer, wire it between transcript loading and chaptering, expose normalization diagnostics in the API, and keep a safe rollback switch.

This implementation stays local-first and avoids architecture churn. ASR remains in-process with `mlx-whisper`, oMLX stays out of scope for this change, and the work focuses on transcript quality, chapter quality, and debuggability.

## Implementation Phases

1. Build a dedicated transcript normalizer service in `backend/app/services` and add committed regression fixtures under `backend/tests/fixtures/`.
2. Add `OVS_ENABLE_TRANSCRIPT_NORMALIZATION` to settings with default `true`, preserve raw parsed transcript segments, and run normalization during the existing `normalizing_transcript` stage.
3. Persist raw and normalized transcript JSON files in the job artifact directory, record their paths in `artifacts`, and compute job-level transcript stats.
4. Keep the current chaptering rules, then add a second density-aware repartitioning pass only for dense single-chapter outputs after normalization.
5. Extend the result schema with a top-level `transcript_stats` field, keep `transcript_segments` as the normalized transcript, and render a compact debug summary in the frontend transcript panel.
6. Update README and test workflow docs to use the repo’s canonical `uv` setup, since the repo already uses `uv sync`, `uv run`, and `uv.lock`, while the smoke-test script still executes a concrete Python interpreter from `.venv` or `OVS_TEST_PYTHON`.

## Normalization Rules

- Run overlap and dedup on parsed timed segments, not on raw VTT text.
- Apply rolling-caption dedup only to `source="captions"` segments. ASR segments only get light whitespace cleanup and short-fragment merging.
- Treat two adjacent caption segments as candidates for rolling-caption merge only when their temporal gap is `<= 2.0s` or they overlap in time.
- Compute the longest token overlap between the suffix of the current accumulated text and the prefix of the next segment text, using normalized whitespace tokenization.
- Merge only when overlap token count is at least `2` and overlap ratio against the shorter token list is at least `0.75`.
- If the next segment is a pure rolling expansion of the current line, keep the longer phrasing and extend the time window.
- If the next segment continues the line after a qualifying overlap, append only the non-overlapping suffix and extend the time window.
- Preserve legitimate speech repetition by refusing to merge when the gap exceeds `2.0s`, the overlap ratio is below `0.75`, or the source is not captions.
- Merge ultra-short continuation fragments only when they are temporally adjacent and would otherwise leave one- or two-word dangling segments.
- Use an explicit blocklist for non-semantic bracketed sound markers such as `[music]`, `[applause]`, `[cheering]`, `[♪]`, and `[♫]`.
- Preserve bracketed text such as `[inaudible]`, `[laughter]`, `[crosstalk]`, and any other bracketed phrase not on the blocklist.
- Leave [text.py](backend/app/utils/text.py) `split_sentences()` and `chunk_text()` unchanged. Reuse only their whitespace-normalization style if helpful; keep overlap helpers inside the new normalizer service.
- If normalization produces zero non-empty segments, fall back to the raw parsed transcript for downstream processing and set a job-level fallback flag in transcript stats.

## Chaptering Rules

- Keep the current first pass exactly as-is:
  - split on gap `>= 45s`
  - split when accumulated duration exceeds `OVS_MAX_CHAPTER_MINUTES`
- Run a second pass only when the first pass yields exactly one chapter, total normalized duration is at least `180s`, and total normalized word count is at least `300`.
- For the second pass, set `target_chapters = min(4, max(2, round(total_words / 220)))`.
- Repartition sequential normalized segments into that many chapters by cumulative word budget, without splitting individual segments and without changing transcript order.
- Skip the second pass for sparse transcripts, short clips, or any transcript that already produced multiple chapters.

## Public Interfaces

- Add a new `TranscriptStats` model in [jobs.py](backend/app/schemas/jobs.py) and expose it as a new top-level `transcript_stats` field in `JobResultResponse`.
- Keep `JobResultResponse.transcript_segments` as the normalized transcript shown in the UI and used by chaptering and summarization.
- Store raw and normalized transcript file paths plus additional debug metadata under `artifacts`.
- Keep per-segment `source` unchanged. Add job-level `source_mode` in `transcript_stats` with values `captions`, `asr`, or `mixed`.
- Include these stats fields:
  - `raw_segment_count`
  - `normalized_segment_count`
  - `cleaned_markup_count`
  - `merged_or_deduped_count`
  - `normalization_applied`
  - `normalization_fallback_used`
  - `source_mode`
- Keep request schemas unchanged and keep frontend changes limited to lightweight diagnostics in the transcript panel.

## Test Plan

- Add committed fixtures under `backend/tests/fixtures/`, including at least `youtube_rolling_en.vtt` and `inline_markup_en.vtt`.
- Add normalizer unit tests that verify inline `<00:...>` and `<c>` markup is removed without losing spoken words.
- Add normalizer unit tests that verify rolling captions collapse into readable non-duplicated segments using the committed YouTube-style fixture.
- Add normalizer unit tests that verify blocklisted sound markers are removed while preserved bracketed content remains intact.
- Add normalizer unit tests that verify clean ASR-like segments remain effectively unchanged.
- Add normalizer unit tests that verify zero-segment normalization falls back to raw transcript.
- Add pipeline tests that verify normalized transcript, not raw transcript, is stored in `transcript_segments`, and raw or normalized artifact paths plus `transcript_stats` are present in the result schema.
- Add chaptering tests that verify dense single-chapter transcripts split into multiple chapters while sparse short videos remain single-chapter when appropriate.
- Keep smoke tests centered on one caption-first YouTube case and one ASR fallback case, with raw vs normalized stats visible in saved artifacts.

## Assumptions And Defaults

- Default direction remains quality-first.
- `OVS_ENABLE_TRANSCRIPT_NORMALIZATION` defaults to `true` and provides rollback to prior behavior when disabled.
- The repo’s canonical setup remains `uv`-based: `uv sync --extra dev` for backend tests and `uv sync --extra dev --extra mlx` for full local smoke tests.
- ASR remains in-process for this change. oMLX is still a later summarizer-adapter candidate, not part of this implementation.
- API compatibility is preserved except for the additive `transcript_stats` field.
