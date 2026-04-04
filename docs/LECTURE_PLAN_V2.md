# LECTURE_PLAN_V2

## Summary

- Adopt the review’s phased rollout: ship the lecture enhancement in three increments instead of one large schema jump.
- Highest priority is fixing summary coverage for long chapters before adding any new study-oriented contract.
- Keep the existing `chapters` and `overall_summary` response shape fully backward compatible.
- Add the new lecture-oriented output behind a feature flag, with failure isolation so study-pack generation never breaks the base summary flow.
- Use repo-relative file mentions only in the written doc; do not embed stale Codex worktree paths.

## Phase A — Fix Coverage And Stabilize Existing Summaries

**v1 status: COMPLETED (2026-04-01).** Hierarchical summarization implemented on both MLX and oMLX providers. All chapter content reaches the LLM; 68 tests pass.

### v1 (shipped)

- Fixed the truncation bug: chapter summarization uses full segment text, not just the first chunk.
- Replaced single-prompt flow with hierarchical summarization (per-chapter synthesis + overall synthesis).
- Added segment-aware chunking (`chunk_segments`) that never splits mid-segment.
- Chunk-note step activates only when a chapter exceeds `summarizer_max_input_chars`.
- Internal chunk notes are plain English text; only chapter and overall outputs are bilingual JSON.
- All MLX/oMLX calls sequential within a job.
- Split `summarizing` stage into sub-stages: `summarizing_chunks`, `synthesizing_chapters`, `synthesizing_overall`.
- Per-step token limits derived from `settings.summarizer_max_tokens` (floor of 512 for chunk notes, 1024 for synthesis).
- Per-chapter artifact subdirs with prompt/request/raw_output files.

### v2 status: COMPLETED (2026-04-03). Hybrid routing implemented on both MLX and oMLX providers.

- `_choose_strategy()` selects single-shot / per-chapter / hierarchical based on total and per-chapter text size vs `summarizer_max_input_chars`.
- **Small** (total text <= threshold): Single-shot prompt with all chapters (1 LLM call, best coherence).
- **Medium** (total text > threshold but each chapter fits): Per-chapter synthesis + overall (N+1 calls).
- **Large** (individual chapters exceed threshold): Full hierarchical with chunk notes (N+K+1 calls).
- `summarizer_strategy.txt` artifact saved for debugging.
- 133 tests pass (45 new). E2E validated on 15-min English video via oMLX.

## Phase B — Add A Minimal Study Pack

**v1 status: COMPLETED (2026-04-01).** Deterministic study pack behind `OVS_ENABLE_STUDY_PACK` feature flag. No LLM calls. 87 tests pass (19 new).

### v1 (shipped)

- Optional `study_pack` in result payload behind `OVS_ENABLE_STUDY_PACK=false` by default.
- Schema: `version`, `format`, `learning_objectives`, `sections[]`, `final_takeaways`.
- Each `sections[]` item: `chapter_index`, `start_s`, `end_s`, `title`, `summary_en`, `summary_zh`, `key_points`.
- Fully deterministic — no LLM call. One section per chapter, derived from existing chapter summaries.
- `learning_objectives`: up to 5 items from `overall_summary.highlights`, falling back to chapter titles.
- `final_takeaways`: reuses `overall_summary.highlights`.
- `study_guide.md` generated from `study_pack.json` using a deterministic template renderer.
- Failure isolation: study-pack errors never fail the job; `study_pack_error.txt` artifact saved on failure.
- API response: `study_pack: null` when disabled/absent (explicit `null`, not field omission).
- Pipeline stage: `generating_study_pack` runs after summarizer, before `COMPLETED`.
- Artifacts: `study_pack.json`, `study_guide.md` persisted alongside existing transcript artifacts.

### v2 (proposed) — Quality Improvements

E2E testing against a 61-minute workshop (YouTube Live) and comparison with Gemini's summary revealed quality gaps in the deterministic v1 output:

**Identified gaps:**
- `learning_objectives` and `final_takeaways` are identical (both copy `highlights`) — no differentiation.
- No timestamp formatting in the markdown renderer (section `start_s`/`end_s` exist in JSON but are not rendered as `[MM:SS]`).
- No speaker attribution — the LLM chapter summaries mention organizations but rarely name individuals.
- ~~`_build_sections()` derives `start_s`/`end_s` from LLM chapter summaries rather than the authoritative `chapters` list~~ — **FIXED in v1** (authoritative chapter timestamps now used).
- Section refinement deferred: v1 maps 1:1 chapter-to-section with no splitting of oversized chapters.

**v2 status: COMPLETED (2026-04-03).** Timestamps, differentiated objectives, and differentiated takeaways shipped. 133 tests pass.

**What shipped in v2:**
- `[MM:SS–MM:SS]` timestamp ranges rendered in `study_guide.md` section headings (backend + frontend export already had this).
- `learning_objectives` rewritten with action verb prefixes ("Understand ...", "Learn about ...", "Explore ...", "Examine ...", "Discover ...") derived from chapter titles, not highlights.
- `final_takeaways` now derived from unique chapter `key_points` (up to 5), falling back to highlights. Distinct from `learning_objectives`.
- No-double-prefix guard: titles already starting with an action verb are not re-prefixed.
- All changes deterministic (no LLM calls). Backward compatible — `study_pack` JSON schema unchanged.

**v3 status: COMPLETED (2026-04-03).** Deterministic section refinement shipped. 157 tests pass (11 new).

**What shipped in v3:**
- Oversized chapters (>5 min AND >450 words) split into 2-3 sub-sections by word budget (~300 words/section), capped at 10 total sections.
- Fully deterministic — first sub-section inherits LLM chapter summary; additional sub-sections extract representative sentences from transcript slices.
- Sub-section titles append "(Part N)"; key_points distributed round-robin.
- Frontend React key fixed to avoid duplicate keys when multiple sections share `chapter_index`.
- E2E validated on 61-min workshop (4 chapters → 10 sections: 3 oversized chapters split into 3 sub-sections each + 1 short chapter pass-through).

**Deferred:**
- LLM-based per-section summarization for additional sub-sections (currently uses sentence extraction).
- Speaker attribution, `prerequisites`, `teaching_notes`, `core_terms`, `review_questions`.

## Phase C — Frontend Study Guide And Export Path

- Keep the current result page structure, but turn it into a tabbed result shell instead of adding routing in the first pass.
- Use three tabs:
  - `Summary`
  - `Study Guide`
  - `Transcript`
- Keep the existing overall-summary and chapter-card UI under `Summary`.
- Add a dedicated `Study Guide` view that renders:
  - learning objectives
  - ordered study sections
  - final takeaways
- Hide the `Study Guide` tab when `study_pack` is absent so older jobs and fallback-only jobs still render cleanly.
- Keep the transcript view unchanged except for tab placement.
- Add a deterministic export renderer that reads `study_pack.json` and produces standalone Markdown or HTML as a post-processing/export step, not as part of core summarization logic.
- Treat Codex skills as optional consumers of `study_pack.json` for future slide or polished webpage generation, but do not make backend runtime depend on Codex skills.

## Phase D — Per-Job Configuration Options

- Currently all configuration lives in server-side env vars set at backend startup. Users cannot toggle options per-job.
- Add optional per-job overrides to `CreateJobRequest`. When omitted, fall back to server defaults — fully backward compatible.
- Add a collapsible "Options" section in the frontend form.

### v1 scope

Two per-job options:
- `enable_study_pack` (boolean) — toggle study guide generation per video
- `enable_transcript_normalization` (boolean) — bypass normalization for specific videos

**Not in v1:** `summarizer_provider` — the MLX provider loads a multi-GB model into GPU memory at startup. Dynamic provider switching requires a provider pool with memory management. Deferred to v2.

### Backend changes

- `JobOptions` Pydantic model with optional fields (all `None` = use server default).
- `options: Optional[JobOptions] = None` on `CreateJobRequest`.
- `options TEXT` column on `jobs` table (JSON, default `'{}'`). Safe migration via `ALTER TABLE ADD COLUMN` with try/except.
- `resolve_job_setting(job_options, key, settings)` helper: checks job options first, falls back to global `Settings`.
- Pipeline reads `job.options` at start of `process_job()` and resolves each setting locally instead of reading `self._settings` directly.
- `JobStatusResponse` echoes back the resolved options so the frontend can display them.

### Frontend changes

- `JobOptions` TypeScript interface, `options?: JobOptions` on `CreateJobRequest`.
- Collapsible "Options" section in `JobForm.tsx` below the URL field, collapsed by default.
- Two toggles: "Generate study guide" (`enable_study_pack`), "Normalize transcript" (`enable_transcript_normalization`, default checked).
- `null` state = "use server default"; only non-null values sent in the request.

### v2 scope (future)

- `summarizer_provider` per-job (requires provider pool with memory management for MLX)
- `max_chapter_minutes` per-job
- `output_languages` as part of the options UI (already per-job in the API)
- Per-job `summarizer_max_input_chars` / `summarizer_max_tokens` for advanced users

## Public Interface Changes

- Add optional `study_pack` to the job result response.
- Add optional artifact entries for the generated study-pack JSON and study-guide Markdown.
- Preserve existing top-level response fields and existing frontend behavior when `study_pack` is missing.
- Add the new summarization sub-stage names so long-running lecture jobs expose finer-grained progress.

## Test Plan

- Add a regression test proving long chapter text is fully covered and no longer truncated to the first chunk.
- Add summarizer tests for hierarchical synthesis over multi-chunk chapters while preserving the existing response schema.
- Add schema tests showing `study_pack` is optional and backward compatible.
- Add section-planner tests proving sections never cross chapter boundaries and oversized chapters are refined predictably.
- Add fallback tests for minimal `study_pack` generation when MLX study-pack synthesis is disabled or fails.
- Add failure-isolation tests showing study-pack errors do not fail the whole job.
- Add frontend tests for tab visibility, study-guide rendering, and backward-compatible rendering when `study_pack` is absent.
- Extend smoke-test expectations so lecture-style runs can verify the presence of study-pack artifacts when the feature flag is enabled.

## Assumptions And Defaults

- The product goal remains local-first and lecture-focused, not generic slide generation.
- The first user-facing enhancement is an in-app study guide, not direct slide export.
- The current single-worker queue model stays unchanged for this feature; no concurrency redesign is included.
- Richer teaching artifacts such as glossary terms, review questions, and teaching notes are deferred until the minimal study-pack path is stable and parse-reliable.
- The V2 doc should explicitly describe this phased rollout and feature-flag strategy so implementation can ship in small, safe increments.
