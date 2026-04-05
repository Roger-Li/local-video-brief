# Lecture Study Pack Enhancement — Implementation Plan

## Context

Long lecture videos (30-120 min) get poor summaries because `build_summarizer_prompt()` at `summarizer.py:35` silently truncates each chapter to its first text chunk (`text_chunks[:1]`). Content beyond `summarizer_max_input_chars` (18,000 chars) is discarded. Additionally, the app has no lecture-oriented study output — only flat chapter summaries.

This plan implements `LECTURE_PLAN_V2.md` in three phases: fix coverage (A), add study pack (B), add frontend (C). Each phase ships independently.

**Post-rebase note:** PR #1 merged `feat/omlx-summarizer`. The summarizer now has three providers (`mlx`, `omlx`, `fallback`) behind a `create_summary_generator()` factory. Shared helpers (`build_summarizer_prompt`, `extract_json`, `compute_max_tokens`) are module-level in `summarizer.py`. The truncation bug lives in the shared `build_summarizer_prompt()` and affects both LLM-backed providers (MLX and oMLX). The rule-based fallback is unaffected — it reads `chapter["text"]` directly and extracts sentences without chunking.

---

## Phase A — Fix Coverage + Hierarchical Summarization

**Goal:** All chapter content reaches the LLM-backed summarizers. Long chapters use multi-step summarization. Output schema unchanged. Both MLX and oMLX providers benefit; the rule-based fallback is unaffected and unchanged.

### A1. Add segment-aware chunking helper

**New functions in:** `backend/app/utils/text.py`

```python
def chunk_segments(segments: list[dict], max_chars: int) -> list[list[dict]]:
    """Group transcript segments into chunks respecting segment boundaries.
    
    Each chunk is a list of consecutive segments whose total text length
    does not exceed max_chars. Never splits mid-segment.
    If a single segment exceeds max_chars, it becomes its own chunk.
    """

def segments_to_text(segments: list[dict]) -> str:
    """Join segment texts with spaces."""
```

**Why not fix `chunk_text()`:** Walking back to word boundaries helps English but does nothing for Chinese, and still cuts across caption/sentence boundaries. Each chapter already carries its raw `segments` list (`chaptering.py:107`), so we chunk at segment boundaries instead. `chunk_text()` is left unchanged.

### A2. Extract `_call_llm()` helper on `MlxQwenSummaryGenerator`

**File:** `backend/app/services/summarizer.py`

```python
def _call_llm(self, system_msg: str, user_msg: str, max_tokens: int,
              artifact_dir: Path | None = None, artifact_label: str = "") -> str:
    """Apply chat template, call mlx_lm.generate, save artifacts, return raw text."""
```

Extracted from existing `summarize()` lines 136-158.

### A3. Extract `_call_omlx()` helper on `OmlxSummaryGenerator`

**File:** `backend/app/services/summarizer.py`

```python
def _call_omlx(self, system_msg: str, user_msg: str, max_tokens: int,
               artifact_dir: Path | None = None, artifact_label: str = "") -> str:
    """Send messages to oMLX server, save artifacts, return raw text."""
```

Extracted from existing `OmlxSummaryGenerator.summarize()` lines 232-283.

### A4. Add chunk-note summarization

**File:** `backend/app/services/summarizer.py`

New method on both `MlxQwenSummaryGenerator` and `OmlxSummaryGenerator`:
```python
def _summarize_chunk(self, chunk_text: str, chapter_title: str,
                     chunk_index: int, total_chunks: int,
                     artifact_dir: Path | None = None) -> str:
```
- Produces **plain English text** (not JSON) — 3-5 sentence note
- `max_tokens=512`
- English-only to reduce JSON fragility and token cost

### A5. Add chapter synthesis

**File:** `backend/app/services/summarizer.py`

```python
def _synthesize_chapter(self, chapter: dict, chunk_notes: list[str],
                        artifact_dir: Path | None = None) -> dict:
```
- Input: chapter metadata + concatenated chunk notes
- Output: `ChapterSummary`-shaped dict (bilingual JSON)
- Uses shared `extract_json()` for parsing; `max_tokens=1024`

### A6. Add overall synthesis

**File:** `backend/app/services/summarizer.py`

```python
def _synthesize_overall(self, source_metadata: dict,
                        chapter_summaries: list[dict],
                        artifact_dir: Path | None = None) -> dict:
```
- Input: metadata + chapter summary dicts
- Output: `OverallSummary`-shaped dict (bilingual JSON); `max_tokens=1024`

### A7. Rewire `summarize()` on both LLM providers

**File:** `backend/app/services/summarizer.py`

Replace the body of `MlxQwenSummaryGenerator.summarize()` and `OmlxSummaryGenerator.summarize()`:

1. For each chapter:
   a. `segment_chunks = chunk_segments(chapter["segments"], max_input_chars)`
   b. Single chunk → use segment text directly for chapter synthesis (skip chunk-note step)
   c. Multiple chunks → `_summarize_chunk()` each → collect notes → `_synthesize_chapter(chapter, notes)`
2. `_synthesize_overall(source_metadata, chapter_summaries)`
3. Return `{"chapters": [...], "overall_summary": {...}}`

Fallback: any JSON parse failure → `RuleBasedSummaryGenerator` (same as current).

`build_summarizer_prompt()` remains for backward compatibility but is no longer the main code path.

**Artifacts saved:**
- `chunk_notes.json` — intermediate notes keyed by chapter index
- Per-step prompts/outputs: `chunk_{i}_{j}_prompt.txt`, `chapter_{i}_synthesis_prompt.txt`, etc.

### A8. Add progress sub-stages

**Files:** `backend/app/services/interfaces.py`, `backend/app/services/summarizer.py`, `backend/app/services/pipeline.py`

- Add optional `progress_callback: Callable[[str], None] | None = None` to `SummaryGenerator` protocol and all three implementations
- Pipeline passes `lambda stage: self.repository.update_job(job_id, progress_stage=stage)`
- Sub-stages: `summarizing_chunks`, `synthesizing_chapters`, `synthesizing_overall`
- `RuleBasedSummaryGenerator` accepts the param but ignores it

### A9. Tests

**New file:** `backend/tests/test_text_utils.py`
- `test_chunk_segments_respects_boundaries` — no segment split across chunks
- `test_chunk_segments_single_large_segment` — oversized segment is its own chunk
- `test_chunk_segments_small_input_single_chunk` — all fit in one chunk
- `test_chunk_segments_empty_input` — returns empty list
- `test_segments_to_text` — joins correctly

**New file:** `backend/tests/test_summarizer.py`
- Mock `mlx_lm.generate` / `mlx_lm.load` via `unittest.mock.patch`
- Test `_summarize_chunk` returns expected notes
- Test `_synthesize_chapter` / `_synthesize_overall` parse JSON correctly
- Test full `summarize()` orchestration with mocked `_call_llm`
- Test fallback on `json.JSONDecodeError`
- Test `extract_json` edge cases (think blocks, markdown fences, trailing text)
- Test single-chunk chapters skip chunk-note step

### A: Execution order
1. A1 — `chunk_segments` + `segments_to_text` + tests
2. A2 + A3 — extract `_call_llm` / `_call_omlx` (refactor only)
3. A8 — protocol update for `progress_callback`
4. A4 + A5 + A6 — new methods
5. A7 — rewire `summarize()` on both LLM providers
6. A9 — remaining tests

---

## Phase B — Minimal Study Pack Behind Feature Flag

**v1 status: COMPLETED (2026-04-01).** All items B1–B7 implemented and tested. 88 tests pass (20 new study pack + 68 existing — zero regressions).

**Goal:** Optional `study_pack` in result payload. Sections are one-per-chapter in v1 (no splitting). Fully deterministic — no extra LLM call.

### B1. Feature flag

**File:** `backend/app/core/config.py`
```python
enable_study_pack: bool = field(
    default_factory=lambda: os.getenv("OVS_ENABLE_STUDY_PACK", "false").lower() == "true"
)
```

### B2. Pydantic models

**File:** `backend/app/schemas/jobs.py`

```python
class StudySection(BaseModel):
    chapter_index: int
    start_s: float
    end_s: float
    title: str
    summary_en: str
    summary_zh: str
    key_points: List[str]

class StudyPack(BaseModel):
    version: int = 1
    format: str = "lecture_study_guide"
    learning_objectives: List[str]
    sections: List[StudySection]
    final_takeaways: List[str]
```

Add to `JobResultResponse`:
```python
study_pack: Optional[StudyPack] = None
```

**Response semantics:** With `Optional[StudyPack] = None`, FastAPI will serialize this as `"study_pack": null` in JSON, not omit the field. This is acceptable — the frontend checks `study_pack != null`. If field omission is preferred, add `response_model_exclude_none=True` to the endpoint decorator. Recommend accepting `null` for simplicity and explicit API contracts.

### B3. Study pack generator (fully deterministic in v1)

**New file:** `backend/app/services/study_pack.py`

```python
class StudyPackGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        source_metadata: dict,
        chapters: list[dict],
        chapter_summaries: list[dict],
        overall_summary: dict,
        artifact_dir: Path | None = None,
    ) -> dict | None:
        """Generate study pack deterministically. Returns dict or None on failure. Never raises."""
```

**v1 is fully deterministic — no LLM call:**
- `learning_objectives`: up to 5 items from `overall_summary["highlights"]`, falling back to first 5 chapter titles if highlights are empty/short
- `sections`: one section per chapter — map `chapter_summaries[i]` to `StudySection`:
  - `chapter_index = i`
  - `start_s`, `end_s`, `title` from chapter summary
  - `summary_en`, `summary_zh`, `key_points` from chapter summary
- `final_takeaways`: reuse `overall_summary["highlights"]`

**Why one-per-chapter in v1:** Splitting chapters into finer sections requires per-section LLM summarization from section transcript slices. Deferring to v2 avoids the shared-model design problem and keeps Phase B purely deterministic.

**Failure isolation:** Entire `generate()` wrapped in try/except → logs warning → returns `None`. On failure, saves error detail to `study_pack_error.txt` artifact.

### B4. Markdown template renderer

**Same file:** `backend/app/services/study_pack.py`

```python
def render_study_guide_markdown(study_pack: dict, source_metadata: dict) -> str:
    """Pure string formatting — no LLM. Returns standalone Markdown."""
```

### B5. Pipeline integration with explicit artifact persistence

**File:** `backend/app/services/pipeline.py`

After the existing summarizer call and before the `COMPLETED` update:

```python
study_pack_data = None
if self._settings.enable_study_pack:
    self.repository.update_job(job_id, progress_stage="generating_study_pack")
    logger.info("stage=generating_study_pack job=%s", job_id)
    t0 = time.perf_counter()
    try:
        from backend.app.services.study_pack import StudyPackGenerator, render_study_guide_markdown
        sp_gen = StudyPackGenerator(self._settings)
        study_pack_data = sp_gen.generate(
            source_metadata=source_metadata or {},
            chapters=chapters,
            chapter_summaries=summary_payload.get("chapters", []),
            overall_summary=summary_payload.get("overall_summary", {}),
            artifact_dir=summary_artifact_dir,
        )
        if study_pack_data is not None:
            # Persist study_pack.json
            sp_path = artifact_root / "study_pack.json"
            sp_path.write_text(
                json.dumps(study_pack_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # Persist study_guide.md from template
            md_content = render_study_guide_markdown(study_pack_data, source_metadata or {})
            md_path = artifact_root / "study_guide.md"
            md_path.write_text(md_content, encoding="utf-8")
            # Merge paths into existing artifacts dict (do NOT overwrite existing fields)
            latest_job = self.repository.get_job(job_id)
            current_artifacts = latest_job.artifacts if latest_job else {}
            current_artifacts["study_pack_path"] = str(sp_path)
            current_artifacts["study_guide_path"] = str(md_path)
            self.repository.update_job(job_id, artifacts=current_artifacts)
        logger.info("stage=generating_study_pack DONE job=%s (%.1fs)", job_id, time.perf_counter() - t0)
    except Exception as exc:
        logger.warning("study_pack generation failed (non-fatal): %s", exc)

# Merge study_pack into result_payload if present
if study_pack_data is not None:
    summary_payload["study_pack"] = study_pack_data
```

**Artifact persistence detail:** Study pack artifacts follow the same pattern as existing transcript artifacts (`transcript_raw_path`, `transcript_normalized_path`). The pipeline:
1. Writes `study_pack.json` and `study_guide.md` to `{artifact_root}/{job_id}/`
2. Re-reads the current `artifacts` dict from the job (to pick up any concurrent updates)
3. Adds `study_pack_path` and `study_guide_path` fields alongside existing entries
4. Updates the job record with the merged artifacts

This ensures no overwrites of transcript or subtitle artifact fields set earlier in the pipeline.

### B6. API endpoint update — explicit pass-through

**File:** `backend/app/api/jobs.py`

The `get_job_result` function constructs `JobResultResponse` explicitly (line 57). Must add:

```python
raw_study_pack = job.result_payload.get("study_pack")

return JobResultResponse(
    ...
    study_pack=raw_study_pack,  # NEW — explicit extraction and pass-through
)
```

### B7. Tests

**New file:** `backend/tests/test_study_pack.py`
- `test_generate_produces_valid_structure` — returns dict with `version`, `format`, `learning_objectives`, `sections`, `final_takeaways`
- `test_generate_one_section_per_chapter` — section count equals chapter count
- `test_generate_learning_objectives_from_highlights` — derives from highlights
- `test_generate_learning_objectives_fallback_to_titles` — uses chapter titles when highlights empty
- `test_generate_final_takeaways_from_highlights` — reuses highlights
- `test_generate_returns_none_on_failure` — given bad input, returns None (not exception)
- `test_render_markdown_contains_sections` — markdown output has expected headings
- `test_study_pack_schema_optional` — `JobResultResponse` validates with and without `study_pack`
- `test_api_result_includes_study_pack` — endpoint response includes `study_pack` when present in `result_payload`
- `test_api_result_null_study_pack` — response has `"study_pack": null` when absent

**Existing test updates:**
- `test_config.py`: `test_study_pack_flag_defaults_false`

### B: Execution order
1. B1 — feature flag
2. B2 — Pydantic models
3. B3 — generator (deterministic)
4. B4 — markdown renderer
5. B5 — pipeline integration (with explicit artifact persistence)
6. B6 — API endpoint (explicit study_pack pass-through)
7. B7 — tests

---

## Phase B — v1 Completion Status

**Completed 2026-04-01.** All items B1–B7 implemented and tested. 88 tests pass (20 new study pack + 68 existing — zero regressions).

### What shipped
- `enable_study_pack` feature flag in `config.py` (`OVS_ENABLE_STUDY_PACK`, default `false`)
- `StudySection`, `StudyPack` Pydantic models in `schemas/jobs.py`; optional `study_pack` on `JobResultResponse`
- `StudyPackGenerator` in `services/study_pack.py` — deterministic, no LLM calls
- `render_study_guide_markdown()` — pure template renderer
- Pipeline integration: `generating_study_pack` stage after summarizer, artifact persistence, failure isolation
- API: explicit `study_pack` pass-through from `result_payload` in `get_job_result`
- `_build_sections()` uses authoritative `chapters` for `start_s`/`end_s`, LLM `chapter_summaries` for content only
- 20 tests: generator (11), markdown renderer (4), schema compatibility (3), config (2)

### Bugfix shipped alongside
- `extract_json()` in `summarizer.py` now uses `json.JSONDecoder(strict=False)` to tolerate unescaped control characters (newlines, tabs) in LLM JSON output. Previously, a single chapter with an unescaped newline in a string value would cause the entire hierarchical summarizer to fall back to rule-based output.

### E2E validation
- Tested with 61-minute English workshop (https://www.youtube.com/live/1jU05MlENOI) via oMLX (Qwen3.5-27B-8bit)
- 8 chapters, all single-chunk, captions source (3062 raw → 881 normalized segments)
- Full bilingual LLM summaries produced; no fallback triggered
- `study_pack.json` (14.9 KB) and `study_guide.md` (13.3 KB) artifacts generated
- Study pack: 3 learning objectives, 8 sections (1:1 with chapters), 3 final takeaways

### Quality observations (informing Phase B v2)
- Compared against Gemini "summarize this video" output on the same URL
- **Strengths:** depth (8 bilingual sections vs Gemini's 5 bullets), structured learning arc, parallel EN/ZH
- **Weaknesses identified:**
  1. `learning_objectives` = `final_takeaways` = `highlights` — same content appears 3 times
  2. No timestamps in markdown (data exists in JSON but not rendered)
  3. ~~`_build_sections()` takes `start_s`/`end_s` from LLM output instead of authoritative `chapters` list~~ — **FIXED** (Codex review P2)
  4. No speaker attribution
  5. No section refinement (1:1 chapter mapping)

---

## Phase C — Frontend Study Guide Tab + Export

**Goal:** Tabbed result view. Study Guide tab when study_pack present. Markdown export.

### C1. TypeScript types

**File:** `frontend/src/types/api.ts`
- Add `StudySection`, `StudyPack` interfaces matching backend schema
- Add `study_pack?: StudyPack | null` to `JobResultResponse`

### C2. Tabbed ResultView

**File:** `frontend/src/components/ResultView.tsx`
- Replace 3 static panels with tab navigation: Summary | Study Guide | Transcript
- Use `useState<"summary" | "study-guide" | "transcript">("summary")`
- Extract current content into `SummaryPanel` and `TranscriptPanel` inline components
- Hide Study Guide tab when `result.study_pack` is null/undefined
- Summary tab is default

### C3. StudyGuideView component

**New file:** `frontend/src/components/StudyGuideView.tsx`
- Renders: learning objectives, ordered sections (bilingual summaries + key points), final takeaways
- Reuses existing CSS patterns (`.panel`, `.chapter-card`, `.summary-block`)
- Includes export button

### C4. Export utility

**New file:** `frontend/src/lib/export.ts`
- `studyPackToMarkdown(studyPack: StudyPack): string` — mirrors backend renderer
- `downloadAsFile(content, filename, mimeType): void` — blob download

### C5. CSS additions

**File:** `frontend/src/styles.css`
- `.tab-bar`, `.tab-button`, `.tab-active` — using existing CSS variables
- `.study-guide-panel`, `.study-section-card` — reuse `.panel` and `.chapter-card` bases

### C: Execution order
1. C1 + C5 (types + CSS — parallel)
2. C2 (tabbed layout — Summary + Transcript tabs first)
3. C3 + C4 (study guide component + export)
4. Wire Study Guide tab into C2

---

## Phase D — Per-Job Configuration Options

**Goal:** Optional per-job overrides in the API and a collapsible options section in the frontend form. Omitted options fall back to server defaults — fully backward compatible.

### D1. `JobOptions` schema and `CreateJobRequest` update

**File:** `backend/app/schemas/jobs.py`

```python
class JobOptions(BaseModel):
    enable_study_pack: Optional[bool] = None
    enable_transcript_normalization: Optional[bool] = None
```

Add to `CreateJobRequest`:
```python
options: Optional[JobOptions] = None
```

All fields Optional — `None` means "use server default." Existing clients that omit `options` are unaffected.

### D2. `JobRecord` and database migration

**File:** `backend/app/models/job.py`
```python
options: Dict[str, Any] = field(default_factory=dict)
```

**File:** `backend/app/db/database.py`

Add migration after `CREATE TABLE`:
```python
try:
    connection.execute("ALTER TABLE jobs ADD COLUMN options TEXT DEFAULT '{}'")
    connection.commit()
except sqlite3.OperationalError:
    pass  # Column already exists
```

**File:** `backend/app/repositories/job_repository.py`
- `create_job()` — accept `options: dict` parameter, insert into new column
- `_row_to_job()` — read and `json.loads` the `options` column
- `update_job()` — add `"options"` to `allowed_json_fields` if needed

### D3. API: pass options through

**File:** `backend/app/api/jobs.py`

```python
@router.post("")
def create_job(payload: CreateJobRequest, request: Request) -> CreateJobResponse:
    repository = request.app.state.job_repository
    options_dict = payload.options.model_dump(exclude_none=True) if payload.options else {}
    job = repository.create_job(
        url=str(payload.url),
        output_languages=payload.output_languages,
        mode=payload.mode,
        options=options_dict,
    )
    return CreateJobResponse(job_id=job.id, status=job.status)
```

`exclude_none=True` ensures only explicitly-set options are stored. Absent options = use server default.

### D4. `resolve_job_setting` helper

**File:** `backend/app/core/config.py`

```python
def resolve_job_setting(job_options: dict, key: str, settings: Settings) -> Any:
    """Return job_options[key] if present, else getattr(settings, key)."""
    if key in job_options:
        return job_options[key]
    return getattr(settings, key)
```

### D5. Pipeline: use per-job options

**File:** `backend/app/services/pipeline.py`

At the start of `process_job()`:
```python
job_options = job.options or {}
enable_normalization = resolve_job_setting(job_options, "enable_transcript_normalization", self._settings)
enable_study_pack = resolve_job_setting(job_options, "enable_study_pack", self._settings)
```

Replace `self._settings.enable_transcript_normalization` with `enable_normalization` and `self._settings.enable_study_pack` with `enable_study_pack`.

### D6. Echo options in job status

**File:** `backend/app/schemas/jobs.py`

Add to `JobStatusResponse`:
```python
options: Optional[Dict[str, Any]] = None
```

**File:** `backend/app/api/jobs.py`

In `get_job()`, include `options=job.options or None`.

### D7. Frontend TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export interface JobOptions {
  enable_study_pack?: boolean;
  enable_transcript_normalization?: boolean;
}

export interface CreateJobRequest {
  url: string;
  output_languages?: string[];
  mode?: "captions_first";
  options?: JobOptions;
}
```

### D8. Frontend form with collapsible options

**File:** `frontend/src/components/JobForm.tsx`

- Add "Options" toggle button below URL field (collapsed by default)
- When expanded: "Generate study guide" toggle, "Normalize transcript" toggle (default checked)
- `null` state = "use server default"; only non-null values included in request
- Form state:
  ```typescript
  const [showOptions, setShowOptions] = useState(false);
  const [enableStudyPack, setEnableStudyPack] = useState<boolean | null>(null);
  const [enableNormalization, setEnableNormalization] = useState<boolean | null>(null);
  ```

### D9. Frontend CSS for options

**File:** `frontend/src/styles.css`

- `.options-toggle` — subtle button to expand/collapse
- `.options-panel` — expanded container
- `.toggle-row` — label + toggle switch row
- `.toggle-switch` — CSS-only toggle matching the warm color scheme

### D10. Backend tests

**New file:** `backend/tests/test_job_options.py`

- `test_create_job_without_options` — backward compatibility, `options` defaults to `{}`
- `test_create_job_with_study_pack_option` — options stored correctly
- `test_create_job_with_normalization_option` — options stored correctly
- `test_resolve_job_setting_uses_override` — job option wins when present
- `test_resolve_job_setting_falls_back_to_global` — global setting used when absent
- `test_resolve_job_setting_empty_options` — empty dict falls back to global
- `test_pipeline_respects_per_job_normalization_override` — mock pipeline verifying normalization skipped
- `test_api_create_job_with_options_returns_201`
- `test_get_job_status_includes_options`

### D11. E2E skill fix

**File:** `.claude/skills/test-e2e/SKILL.md`

The smoke test uses port 8010 (`OVS_TEST_PORT:-8010`), but the frontend defaults to `http://127.0.0.1:8000`. The frontend step must set `VITE_API_BASE_URL=http://127.0.0.1:${PORT}` matching the smoke test port.

### D12. Update docs

**Files:** `CLAUDE.md`

Add "Per-Job Options" section documenting available overrides, defaults, and the `summarizer_provider` v1 limitation.

### D: Execution order

1. D1 + D4 (schema + helper — independent)
2. D2 (model + DB migration — depends on D1)
3. D3 + D5 + D6 (API + pipeline + status — depends on D1, D2, D4)
4. D10 (backend tests)
5. D7 + D9 (frontend types + CSS — parallel)
6. D8 (frontend form — depends on D7, D9)
7. D11 + D12 (skill fix + docs)

### D: Design decisions

1. **JSON `options` column, not per-field columns** — Adding columns requires ALTER TABLE for each new option. A JSON column is consistent with how `artifacts` and `source_metadata` are stored, and handles sparse optional overrides naturally.

2. **`resolve_job_setting()` helper, not a new Settings subclass** — Keeps it simple. The pipeline calls the helper for the 2 settings it needs. No new abstraction until v2 adds more per-job options.

3. **No `summarizer_provider` in v1** — The MLX provider loads a multi-GB model into GPU memory at `_ensure_model_loaded()`. Creating a new provider instance per-job would require unloading the current model or having two models in memory. Deferred to v2 with a provider pool.

4. **`exclude_none=True` on serialization** — Only explicitly-set options are stored. This distinguishes "user chose false" from "user didn't set anything" (absent key = server default).

---

## Files Summary

### Modified
| File | Phase | Change |
|------|-------|--------|
| `backend/app/utils/text.py` | A | Add `chunk_segments()`, `segments_to_text()` |
| `backend/app/services/summarizer.py` | A | Hierarchical summarization on MLX + oMLX providers |
| `backend/app/services/interfaces.py` | A | `progress_callback` on `SummaryGenerator` protocol |
| `backend/app/services/pipeline.py` | A+B | Sub-stages + study pack integration with artifact persistence |
| `backend/app/core/config.py` | B | `enable_study_pack` flag |
| `backend/app/schemas/jobs.py` | B | `StudyPack`, `StudySection` models, optional field |
| `backend/app/api/jobs.py` | B | Explicit `study_pack` pass-through in response construction |
| `frontend/src/types/api.ts` | C+D | `StudyPack` types; `JobOptions` type, `options` on `CreateJobRequest` |
| `frontend/src/components/ResultView.tsx` | C | Tabbed layout |
| `frontend/src/styles.css` | C+D | Tab + study guide styles; options toggle + panel styles |
| `backend/app/models/job.py` | D | `options` field on `JobRecord` |
| `backend/app/db/database.py` | D | `ALTER TABLE` migration for `options` column |
| `backend/app/repositories/job_repository.py` | D | Read/write `options` in create/row mapping |
| `backend/app/core/config.py` | D | `resolve_job_setting()` helper |
| `backend/app/schemas/jobs.py` | B+D | `JobOptions` model; `options` on `CreateJobRequest` and `JobStatusResponse` |
| `backend/app/api/jobs.py` | B+D | Pass `options` through in create; echo in status |
| `backend/app/services/pipeline.py` | A+B+D | Per-job option resolution in `process_job()` |
| `frontend/src/components/JobForm.tsx` | D | Collapsible options section |

### Created
| File | Phase | Purpose |
|------|-------|---------|
| `backend/tests/test_text_utils.py` | A | `chunk_segments` tests |
| `backend/tests/test_summarizer.py` | A | Summarizer tests (mocked LLM) |
| `backend/app/services/study_pack.py` | B | Generator (deterministic v1) + markdown renderer |
| `backend/tests/test_study_pack.py` | B | Study pack tests |
| `frontend/src/components/StudyGuideView.tsx` | C | Study guide component |
| `frontend/src/lib/export.ts` | C | Markdown export + download |
| `backend/tests/test_job_options.py` | D | Per-job options tests |

---

## Verification

### Phase A
```bash
python3 -m pytest backend/tests/test_text_utils.py backend/tests/test_summarizer.py -v
python3 -m pytest backend/tests -v  # full suite, no regressions
# E2E with MLX:
OVS_ENABLE_MLX_SUMMARIZER=true ./scripts/test_video_job.sh "<long-lecture-url>"
# E2E with oMLX:
OVS_TEST_SUMMARIZER_PROVIDER=omlx OVS_OMLX_BASE_URL=http://localhost:8080/v1 OVS_OMLX_MODEL=<model> ./scripts/test_video_job.sh "<long-lecture-url>"
# Verify: artifacts/<job-id>/chunk_notes.json exists for multi-chunk chapters
```

### Phase B
```bash
python3 -m pytest backend/tests/test_study_pack.py -v
python3 -m pytest backend/tests -v
# E2E:
OVS_ENABLE_MLX_SUMMARIZER=true OVS_ENABLE_STUDY_PACK=true ./scripts/test_video_job.sh
# Verify: artifacts/<job-id>/study_pack.json and study_guide.md exist
# Verify: GET /jobs/{id}/result has "study_pack" field (non-null)
# Verify: with OVS_ENABLE_STUDY_PACK unset, "study_pack" is null in response
```

### Phase C
```bash
cd frontend && npm run build  # TypeScript check
cd frontend && npm run dev    # Manual: tabs render, study guide shows when present
# Export: download produces valid Markdown
```

### Phase D
```bash
python3 -m pytest backend/tests/test_job_options.py -v
python3 -m pytest backend/tests -v  # full suite, no regressions
cd frontend && npx tsc --noEmit --skipLibCheck && npx vite build
# E2E: submit via UI with "Generate study guide" toggled ON → study_pack present
# E2E: submit via UI with toggle OFF → study_pack null
# E2E: submit without expanding options → uses server defaults
```

---

## Key Design Decisions

1. **Segment-aware chunking, not string-level** — `chunk_segments()` groups transcript segments by char budget, never splitting mid-segment. Works for English and Chinese. Existing `chunk_text()` left unchanged.

2. **Hierarchical summarization for MLX and oMLX only** — the rule-based fallback reads `chapter["text"]` directly and extracts sentences without chunking, so it is unaffected by the truncation bug and unchanged in this plan.

3. **Phase B is fully deterministic** — no LLM call for study pack in v1. `learning_objectives` and `final_takeaways` derived from existing summaries. Avoids shared-model design problem.

4. **One section per chapter in v1** — splitting chapters requires per-section LLM summarization from transcript slices. Deferred to v2.

5. **Explicit API pass-through** — `jobs.py:get_job_result` constructs the response field-by-field; `study_pack` is extracted and passed explicitly.

6. **`study_pack: null` in response when absent** — FastAPI serializes `Optional[...] = None` as JSON `null`, not field omission. Frontend checks `!= null`. Acceptable for explicit API contracts.

7. **Artifact persistence is additive** — study pack paths (`study_pack_path`, `study_guide_path`) are merged into the existing `artifacts` dict by re-reading current state, adding new fields, and updating. No overwrite of transcript/subtitle artifact fields.

---

## Phase A — v1 Completion Status

**Completed 2026-04-01.** All items A1–A9 implemented and tested. 68 tests pass (6 new text utils, 11 new summarizer, 51 existing — zero regressions).

### What shipped
- `chunk_segments()` and `segments_to_text()` in `utils/text.py`
- `_call_llm()` / `_call_omlx()` extracted helpers on both LLM providers
- `_summarize_chunk()`, `_synthesize_chapter()`, `_synthesize_overall()` on both providers
- `summarize()` rewired to hierarchical flow on both MLX and oMLX; rule-based unchanged
- `progress_callback` on `SummaryGenerator` protocol; pipeline wires sub-stages
- Per-step token limits derived from `settings.summarizer_max_tokens` (not hard-coded)
- Per-chapter artifact subdirs (`ch0/`, `ch1/`, ...) with prompt/request/raw_output files
- `chunk_notes.json` saved when multi-chunk chapters exist
- `build_summarizer_prompt()` retained but no longer on the main code path

### E2E validation
- Tested with 83-minute Chinese lecture (https://www.youtube.com/watch?v=2rcJdFuNbZQ) via oMLX (Qwen3.5-27B-8bit)
- 11 chapters, all single-chunk (max chapter = 3141 chars, well under 18K threshold)
- Full bilingual LLM summaries produced; no fallback triggered

### Observations leading to Phase A v2

The current hierarchical path runs unconditionally — even short videos get N+1 LLM calls (1 per chapter + 1 overall). For the test lecture, all 11 chapters fit comfortably within the 18K per-chapter budget and within the model's 256K context. The multi-step approach adds latency without coverage benefit for videos where all text fits in a single prompt.

---

## Phase A v2 — Hybrid Routing (Proposed)

**Goal:** Use the simplest strategy that achieves full coverage. Only escalate to multi-step when the input doesn't fit.

### Routing logic

Decide strategy based on total transcript size:

| Condition | Strategy | LLM calls | Rationale |
|---|---|---|---|
| Total chapter text ≤ `max_input_chars` | **Single-shot** — one prompt with all chapters (the original `build_summarizer_prompt` path) | 1 | Best coherence; model sees all context at once |
| Total text > `max_input_chars` but each chapter ≤ `max_input_chars` | **Per-chapter synthesis** — `_synthesize_chapter` per chapter + `_synthesize_overall` | N+1 | Chapters summarized individually; overall from chapter summaries |
| Any chapter > `max_input_chars` | **Full hierarchical** — chunk notes + chapter synthesis + overall synthesis | N+K+1 | Long chapters compressed via chunk notes first |

### Why this is better

1. **Short videos (< 18K total):** 1 LLM call instead of N+1. Model sees full cross-chapter context, producing more coherent summaries. Most videos under ~30 minutes will hit this path.
2. **Medium videos (18K-256K total, chapters < 18K each):** Per-chapter synthesis. Each chapter gets its own synthesis call but no chunk-note overhead. The current E2E test (83 min, 30K total) would hit this path.
3. **Long/dense videos (chapters > 18K):** Full hierarchical with chunk notes. Only needed for very long lectures with few natural breaks.

### Config considerations

- `summarizer_max_input_chars` (currently 18K) controls the single-shot threshold AND the per-chapter chunk budget. Consider splitting into two settings: `summarizer_single_shot_max_chars` and `summarizer_chunk_max_chars`.
- With Qwen 3.5's 256K context, the single-shot threshold could be raised significantly (e.g., 50-80K chars). The 18K value was conservative for the old single-prompt approach where schema + metadata + all chapters competed for space.
- The per-chapter chunk budget could also be raised, since each `_synthesize_chapter` call only carries one chapter's notes plus the synthesis prompt.

### Implementation scope

- Add routing logic at the top of `summarize()` on both providers
- Restore `build_summarizer_prompt()` as the single-shot path
- Keep `_summarize_chunk` / `_synthesize_chapter` / `_synthesize_overall` for the multi-step paths
- Add tests for routing decisions at each threshold
- Consider adding `summarizer_strategy` config (`auto` | `single_shot` | `hierarchical`) for explicit override

### Open questions

1. Should the single-shot threshold be the same as the chunk budget, or a separate setting?
2. For the per-chapter path, should `_synthesize_overall` receive the raw chapter text alongside chapter summaries to improve overall summary quality?
3. Should routing be logged as an artifact (e.g., `summarizer_strategy.txt`) for debugging?
