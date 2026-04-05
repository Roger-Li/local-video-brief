# Configurable Prompts and Model Selection from UI — v2

## Context

The top roadmap item calls for letting users choose models, customize summarization focus, and select style presets from the frontend. The per-job options infrastructure already exists (`JobOptions` -> `resolve_job_setting()` -> pipeline), so this extends it with three new options: **style presets**, **focus hints**, and **oMLX model override**.

Constraint: `summarizer_provider` stays server-level (MLX loads multi-GB model at startup). Model override only applies to oMLX, where it's just an HTTP parameter.

### Scope decisions

**In v0:** Style/tone presets, content-focus hints ("emphasize mathematical proofs"), oMLX model override.

**Deferred:** VQA-style queries ("What are the key arguments for X?"). VQA needs a dedicated response field (not implicit inside `summary_en`/`summary_zh`) and a query-aware extraction path. Future version can add an `answers` field to the result schema.

**Unsupported options policy:** The API always accepts and stores prompt options regardless of provider (they live in the JSON `options` column). Only LLM providers (mlx, omlx) act on them. The `/config` endpoint exposes capability flags so the frontend hides controls that won't have any effect for the current provider. This avoids API-level rejection, preserves stored options if the server provider changes later, and keeps UX clean.

---

## Changes from v1

| v1 issue | Resolution |
|----------|-----------|
| P2: `detailed`/`concise` sentence counts conflict with hardcoded prompt lengths | Presets now own length guidance via parameterized fields; base prompts use preset values instead of hardcoded counts (Step 1, 4b) |
| P2: Token multiplier only covers `compute_max_tokens()` (single-shot) | Multiplier threaded through `_step_tokens()` and `_chunk_note_tokens()` as well (Step 4d) |
| `current_model` semantics for fallback provider | Returns `null` when `summarizer_provider == "fallback"` (Step 3) |
| P2: Shared `chapter_length` silently changes hierarchical defaults | Split into `chapter_length` (for chapter synthesis, default `"2-4"`) and `single_shot_chapter_length` (for single-shot rules line, default `"3-5"`); see Step 1 note |
| P2: Single-shot schema example has hardcoded sentence counts | Schema example is now parameterized alongside the rules line (Step 4b) |

---

## Step 1: Style Presets Module

**New file: `backend/app/core/style_presets.py`**

Define a `StylePreset` frozen dataclass and a `STYLE_PRESETS` dict registry.

Each preset carries:
- `id`, `label`, `description` — identity and UI display
- `system_suffix` — tone/focus directive appended to system prompts (empty for default)
- `chapter_length` — sentence range for chapter-synthesis and schema-example chapter placeholders (replaces hardcoded "2-4")
- `overall_length` — sentence range for overall-synthesis and schema-example overall placeholders (replaces hardcoded "3-5")
- `single_shot_chapter_length` — sentence range for the single-shot rules line only (replaces hardcoded "3-5" in the rules block). Exists because the current single-shot rules line says "3-5" while the schema example and chapter synthesis both say "2-4" — these are intentionally different defaults that we preserve.
- `max_tokens_multiplier` — float applied to all token budgets

| Preset ID | system_suffix | chapter_length | single_shot_chapter_length | overall_length | multiplier |
|-----------|--------------|----------------|---------------------------|----------------|------------|
| `default` | *(empty)* | `"2-4"` | `"3-5"` | `"3-5"` | 1.0 |
| `detailed` | "Provide thorough summaries with extensive key points covering all major arguments and examples." | `"5-7"` | `"5-7"` | `"5-8"` | 1.5 |
| `concise` | "Keep summaries extremely brief and focused." | `"1-2"` | `"1-2"` | `"2-3"` | 0.6 |
| `technical` | "Focus on technical details, implementation specifics, precise terminology, and quantitative claims. Preserve domain-specific language." | `"3-5"` | `"3-5"` | `"3-5"` | 1.2 |
| `academic` | "Use formal academic tone. Reference specific claims, evidence, and arguments from the content. Note methodological details or citations mentioned." | `"3-5"` | `"3-5"` | `"4-6"` | 1.2 |

**Existing divergence note:** The current codebase has an internal inconsistency in single-shot mode: the schema example says `"2-4 sentence"` for chapters, but the rules line says `"3-5 sentences each"`. Chapter synthesis uses `"2-4"`. The `default` preset preserves this divergence exactly (`chapter_length: "2-4"` for schema example + chapter synthesis, `single_shot_chapter_length: "3-5"` for the rules line). All non-default presets unify the two fields — `chapter_length == single_shot_chapter_length` — so the model receives one consistent sentence-count instruction across schema example, rules, and synthesis prompts.

All presets produce output conforming to the existing JSON schema (`summary_en`/`summary_zh` as prose strings, `key_points` as string arrays). No preset changes structural format.

Standalone module, no app imports. Fully testable in isolation.

---

## Step 2: Backend Schema — `JobOptions` Extension

**Edit: `backend/app/schemas/jobs.py`**

Add three optional fields to `JobOptions`:
```python
focus_hint: Optional[str] = None             # max 500 chars, content emphasis directive
style_preset: Optional[str] = None           # key from STYLE_PRESETS
omlx_model_override: Optional[str] = None    # oMLX-only model name
```

Pydantic validators:
- `style_preset`: must be `None` or a key in `STYLE_PRESETS`
- `focus_hint`: strip whitespace, reject if > 500 chars

No DB migration needed — `options` is a JSON TEXT column, new keys are backward-compatible.

---

## Step 3: `GET /config` Endpoint

**New file: `backend/app/api/config.py`**

Returns server state the frontend needs:
```json
{
  "summarizer_provider": "omlx",
  "current_model": "qwen2.5-32b",
  "model_override_allowed": true,
  "supports_prompt_customization": true,
  "style_presets": [{"id": "default", "label": "Default", "description": "..."}]
}
```

Capability flags:
- `model_override_allowed`: `true` when `summarizer_provider == "omlx"`
- `supports_prompt_customization`: `true` when `summarizer_provider` is `"mlx"` or `"omlx"`. `false` for `"fallback"`.
- `current_model`: `settings.omlx_model` for omlx, `settings.summarizer_model` for mlx, `null` for fallback. Semantics: "the model actively used by the current provider." `null` when there is no model (fallback is rule-based).

**Edit: `backend/app/main.py`** — register the router.

---

## Step 4: Prompt Construction Changes

**Edit: `backend/app/services/summarizer.py`**

### 4a. Preset resolution helper

New helper `_resolve_preset(style_preset_id: str | None) -> StylePreset`:
- Returns `STYLE_PRESETS[style_preset_id]` if set and valid, else `STYLE_PRESETS["default"]`.
- Single source of truth: every prompt path calls this once and uses the result for length guidance, suffix, and token multiplier.

### 4b. Parameterize length guidance in base prompts

Replace **all** hardcoded sentence counts with preset-driven values. Three locations in `build_summarizer_prompt()` need updating, plus the two synthesis prompt builders.

**1. Schema example** (currently lines 44-64 — the JSON example embedded in the system message):

The schema example contains placeholder strings with hardcoded sentence counts. These must be parameterized too, otherwise `detailed`/`concise` presets would still show "2-4" / "3-5" in the example while the rules line says something different.

Before:
```python
"summary_en": "2-4 sentence English summary of this chapter.",
"summary_zh": "2-4 sentence Chinese summary of this chapter.",
...
"summary_en": "3-5 sentence English summary of the entire video.",
"summary_zh": "3-5 sentence Chinese summary of the entire video.",
```

After — `build_summarizer_prompt()` accepts `preset: StylePreset`:
```python
"summary_en": f"{preset.chapter_length} sentence English summary of this chapter.",
"summary_zh": f"{preset.chapter_length} sentence Chinese summary of this chapter.",
...
"summary_en": f"{preset.overall_length} sentence English summary of the entire video.",
"summary_zh": f"{preset.overall_length} sentence Chinese summary of the entire video.",
```

**2. Rules line** (currently line 71):

Before:
```
"- summary_en and summary_zh must be substantive (3-5 sentences each)..."
```

After:
```python
f"- summary_en and summary_zh must be substantive ({preset.single_shot_chapter_length} sentences each)..."
```

Uses `single_shot_chapter_length` (not `chapter_length`) because the current code has an intentional divergence: rules line says "3-5" while the schema example says "2-4". The `default` preset preserves both values exactly.

**3. Style suffix**: If `preset.system_suffix` is non-empty, append it after the rules block.

**Chapter synthesis system prompt** (currently `_CHAPTER_SYNTHESIS_SYSTEM`, line 455-464):

New function `_build_chapter_synthesis_system(preset: StylePreset) -> str`:
```python
f'"summary_en": "<{preset.chapter_length} sentence English summary>",'
f'"summary_zh": "<{preset.chapter_length} sentence Chinese summary>",'
```
Plus `preset.system_suffix` appended if non-empty.

**Overall synthesis system prompt** (currently `_OVERALL_SYNTHESIS_SYSTEM`, line 476-484):

New function `_build_overall_synthesis_system(preset: StylePreset) -> str`:
```python
f'"summary_en": "<{preset.overall_length} sentence English summary of the entire video>",'
f'"summary_zh": "<{preset.overall_length} sentence Chinese summary of the entire video>",'
```
Plus `preset.system_suffix` appended if non-empty.

**Backward compatibility**: With `default` preset, every interpolation produces the exact same text as today:
- Schema example chapters: `"2-4"` (from `chapter_length`)
- Schema example overall: `"3-5"` (from `overall_length`)
- Rules line: `"3-5"` (from `single_shot_chapter_length`)
- Chapter synthesis: `"2-4"` (from `chapter_length`)
- Overall synthesis: `"3-5"` (from `overall_length`)

### 4c. Focus hint placement

Focus hints go in the **user message**, not the system message. This keeps JSON schema enforcement in the system message authoritative and places user-authored text at clearly lower priority.

Update `build_summarizer_prompt()` — if `focus_hint` is non-empty, prepend a delimited section in `user_msg`:
```
Content focus: {focus_hint}
---
Target languages: ...
Metadata: ...
Chapters: ...
```

**Chunk-note prompts** — append focus hint to `_build_chunk_note_user()` output:
```
Chapter: {title}
Chunk 1 of 3:
{chunk_text}
---
Content focus: {focus_hint}
```

**Chapter synthesis and overall synthesis user messages** — same delimited prepend.

### 4d. Token budget — all paths

Thread the preset multiplier through **all** token budget helpers, not just `compute_max_tokens()`.

Current state:
- `compute_max_tokens(settings, chapter_count)` — used by single-shot path only
- `_chunk_note_tokens(self)` — returns `max(512, settings.summarizer_max_tokens // 4)`
- `_step_tokens(self)` — returns `max(1024, settings.summarizer_max_tokens // 2)`

After — all three accept the multiplier:

```python
def compute_max_tokens(settings, chapter_count, multiplier=1.0) -> int:
    base = max(settings.summarizer_max_tokens, 1024 * chapter_count + 1024)
    return int(base * multiplier)

# In MlxQwenSummaryGenerator and OmlxSummaryGenerator:
def _chunk_note_tokens(self, multiplier: float = 1.0) -> int:
    base = max(512, self.settings.summarizer_max_tokens // 4)
    return int(base * multiplier)

def _step_tokens(self, multiplier: float = 1.0) -> int:
    base = max(1024, self.settings.summarizer_max_tokens // 2)
    return int(base * multiplier)
```

The resolved preset's `max_tokens_multiplier` is passed to all three. For `detailed` (1.5x), a hierarchical chapter synthesis step gets `max(1024, 2048 // 2) * 1.5 = 1536` tokens instead of 1024. For `concise` (0.6x), it gets 614.

---

## Step 5: Thread `job_options` Through Pipeline -> Summarizer

**Edit: `backend/app/services/interfaces.py`** — add `job_options: Optional[Dict[str, Any]] = None` to `SummaryGenerator.summarize()`.

**Edit: `backend/app/services/pipeline.py`** (~line 167) — pass `job_options=job_options` to `self.summary_generator.summarize()`.

**Edit: `backend/app/services/summarizer.py`** — all three providers:

Each LLM provider's `summarize()` resolves the preset once and threads the result:
```python
def summarize(self, ..., job_options=None):
    opts = job_options or {}
    preset = _resolve_preset(opts.get("style_preset"))
    focus_hint = opts.get("focus_hint")
    # Pass preset and focus_hint to all prompt builders and token helpers
```

- `MlxQwenSummaryGenerator.summarize()`: extract preset + focus_hint, pass to prompt builders and token helpers. Ignore `omlx_model_override`.
- `OmlxSummaryGenerator.summarize()`: same + extract `omlx_model_override`, thread to `_call_omlx()` which uses it instead of `self.settings.omlx_model` when set.
- `RuleBasedSummaryGenerator.summarize()`: accept `job_options` for protocol compat, ignore it (rule-based output is deterministic).

---

## Step 6: Frontend Types & API Client

**Edit: `frontend/src/types/api.ts`** — add to `JobOptions`:
```typescript
focus_hint?: string;
style_preset?: string;
omlx_model_override?: string;
```

Add new types:
```typescript
export interface StylePresetInfo { id: string; label: string; description: string; }
export interface ServerConfig {
  summarizer_provider: string;
  current_model: string | null;
  model_override_allowed: boolean;
  supports_prompt_customization: boolean;
  style_presets: StylePresetInfo[];
}
```

**Edit: `frontend/src/lib/api.ts`** — add `getConfig()`.

---

## Step 7: Frontend Config Query

**Edit: `frontend/src/App.tsx`** — add `useQuery` for `/config` (staleTime: Infinity, fetch once). Pass `configQuery.data` as `serverConfig` prop to `<JobForm>`.

---

## Step 8: JobForm UI

**Edit: `frontend/src/components/JobForm.tsx`**

Accept `serverConfig?: ServerConfig` prop. Inside the existing `{showOptions && (...)}` block, add below current toggles:

**Capability gating:** The entire "Summarization" sub-section (presets, focus hint, model override) is only rendered when `serverConfig?.supports_prompt_customization` is true. When false (fallback provider), the options panel shows only the existing toggles.

**Controls (when prompt customization is supported):**

1. **Style preset pills** — row of clickable pill buttons for each preset from `serverConfig.style_presets`. State: `useState<string | null>(null)`. `null` means unset (server default). The "Default" pill is visually selected when state is `null`. Selecting "Default" explicitly resets state to `null`.

2. **Focus hint textarea** — labeled "Content focus". Placeholder: "E.g., Emphasize the mathematical proofs and derivations...". State: `useState("")`. Character counter shows `N / 500`. Styled consistently with `.field input` but as a textarea with `min-height: 60px; resize: vertical`.

3. **Model override input** — only rendered when `serverConfig.model_override_allowed` is true (oMLX). Text input with `serverConfig.current_model` as placeholder. State: `useState("")`.

**`buildOptions()` update:**
```typescript
if (serverConfig?.supports_prompt_customization) {
  if (stylePreset !== null) opts.style_preset = stylePreset;
  if (focusHint.trim()) opts.focus_hint = focusHint.trim();
  if (modelOverride.trim()) opts.omlx_model_override = modelOverride.trim();
}
```

**Edit: `frontend/src/styles.css`** — styles for `.options-section-label`, `.preset-row`, `.preset-pill`, `.preset-pill-active`, `.focus-hint-field textarea`, `.char-count`, `.model-override-field`.

---

## Verification

### Backend tests (`python3 -m pytest backend/tests`)

**Style presets** (`test_style_presets.py` — new):
- All presets have required fields (id, label, description, system_suffix, chapter_length, single_shot_chapter_length, overall_length, max_tokens_multiplier)
- `"default"` preset: empty suffix, `"2-4"` chapter_length, `"3-5"` single_shot_chapter_length, `"3-5"` overall_length, 1.0 multiplier
- All multipliers are positive floats
- `chapter_length`, `single_shot_chapter_length`, and `overall_length` are non-empty strings for all presets
- All non-default presets: `chapter_length == single_shot_chapter_length` (no internal contradiction)
- No preset's system_suffix mentions structural format changes

**Schema validation** (extend `test_job_options.py`):
- `focus_hint` accepted when <= 500 chars, rejected when > 500
- `style_preset` accepted for known IDs, rejected for unknown
- `omlx_model_override` accepted as string
- Round-trip: create job with new options -> retrieve -> verify stored

**Prompt construction** (extend `test_summarizer.py`):
- `build_summarizer_prompt` with default preset: schema example contains `"2-4 sentence"` for chapters and `"3-5 sentence"` for overall; rules line contains `"3-5 sentences"` — exact match of current hardcoded output
- `build_summarizer_prompt` with `"detailed"` preset: schema example chapters `"4-6"`, overall `"5-8"`, rules line `"5-7"`
- `build_summarizer_prompt` with `"concise"` preset: schema example chapters `"1-2"`, overall `"2-3"`, rules line `"1-2"`
- `build_summarizer_prompt` with focus_hint: hint appears in user_msg with delimiter, not in system_msg
- `_build_chapter_synthesis_system("concise")`: contains `"1-2 sentence"`, not `"2-4"`
- `_build_overall_synthesis_system("detailed")`: contains `"5-8 sentence"`, not `"3-5"`
- Chunk-note user message includes focus hint when provided, unchanged when `None`
- Chapter-synthesis user message includes focus hint when provided
- Overall-synthesis user message includes focus hint when provided
- `OmlxSummaryGenerator`: `omlx_model_override` in job_options changes the `"model"` field in the HTTP request body
- `MlxQwenSummaryGenerator`: `omlx_model_override` in job_options is ignored (model stays `settings.summarizer_model`)
- `RuleBasedSummaryGenerator`: all prompt options in job_options are ignored
- `compute_max_tokens` with multiplier 1.5: correct scaling
- `_step_tokens` with multiplier 0.6: `int(max(1024, 2048 // 2) * 0.6) == 614`
- `_chunk_note_tokens` with multiplier 1.5: `int(max(512, 2048 // 4) * 1.5) == 768`

**Config endpoint** (`test_config_endpoint.py` — new):
- Returns correct `summarizer_provider`
- `supports_prompt_customization` is `true` for mlx/omlx, `false` for fallback
- `model_override_allowed` is `true` for omlx only
- `current_model` is `null` for fallback, correct model string for mlx/omlx
- `style_presets` list matches `STYLE_PRESETS` registry

### Frontend tests (extend existing Vitest suite)

- `getConfig()` returns parsed `ServerConfig`
- `JobForm` hides prompt controls when `supports_prompt_customization` is `false`
- `JobForm` shows prompt controls when `supports_prompt_customization` is `true`
- `JobForm` hides model override when `model_override_allowed` is `false`
- `JobForm` shows model override when `model_override_allowed` is `true`
- Preset pills: selecting a preset sets state; selecting "Default" resets to `null`
- `buildOptions()` omits `style_preset` when `null` (unset)
- `buildOptions()` omits prompt options entirely when `supports_prompt_customization` is `false`
- Focus hint textarea enforces 500-char display limit

### Smoke test

`scripts/test_video_job.sh` with oMLX provider to verify end-to-end flow.

### Manual UI check

Launch frontend, expand options — verify:
- Fallback provider: only toggles visible, no prompt controls
- oMLX provider: preset pills, focus hint textarea, model override input all visible
- Options flow correctly to backend (check `options` in job status response)

---

## Critical Files

| File | Change |
|------|--------|
| `backend/app/core/style_presets.py` | NEW — preset definitions with length guidance fields |
| `backend/app/schemas/jobs.py` | Add 3 fields to JobOptions + validators |
| `backend/app/api/config.py` | NEW — GET /config endpoint with capability flags |
| `backend/app/main.py` | Register config router |
| `backend/app/services/interfaces.py` | Add job_options to SummaryGenerator protocol |
| `backend/app/services/summarizer.py` | Parameterize prompt templates, thread preset/focus through all paths and token helpers |
| `backend/app/services/pipeline.py` | Pass job_options to summarizer |
| `frontend/src/types/api.ts` | New types (ServerConfig, StylePresetInfo, extended JobOptions) |
| `frontend/src/lib/api.ts` | Add getConfig() |
| `frontend/src/App.tsx` | Config query, pass to JobForm |
| `frontend/src/components/JobForm.tsx` | Capability-gated style pills, focus hint textarea, model input |
| `frontend/src/styles.css` | New component styles |

---

## Design Rationale

- **Presets own length guidance (not layered suffix)**: The base prompts currently hardcode sentence counts in three places: schema example ("2-4" chapters, "3-5" overall), rules line ("3-5"), and synthesis prompts ("2-4" chapter, "3-5" overall). Appending a preset suffix with different counts creates contradictory system-level instructions. Instead, presets provide `chapter_length`, `single_shot_chapter_length`, and `overall_length` fields interpolated into all prompt locations including the schema example. The split between `chapter_length` ("2-4") and `single_shot_chapter_length` ("3-5") preserves the existing divergence where the rules line and schema example use different values. The `default` preset reproduces current behavior byte-for-byte.
- **Token multiplier threaded through all helpers**: `compute_max_tokens()` only covers single-shot. Per-chapter and hierarchical flows use `_step_tokens()` and `_chunk_note_tokens()`. The multiplier must reach all three, otherwise `detailed` gives more budget to single-shot but not to the hierarchical flows that need it most (long videos).
- **Focus hints in user message, style suffix in system**: Style presets are a closed set of curated text — safe for the system role. Focus hints are user-authored and belong at lower priority in the user message with a delimiter, to avoid conflicting with schema enforcement.
- **Focus hints in chunk-note prompts**: In hierarchical mode, chunk notes are the information bottleneck. Focus hints must reach the extraction stage or relevant content gets discarded before synthesis.
- **`null`-as-unset for presets**: Consistent with existing toggles. Only sent when explicitly changed, so server-side default changes propagate.
- **Capability gating via `/config`**: Fallback provider ignores prompt options. UI hides inert controls. API still stores options (no rejection) so provider changes don't invalidate jobs.
- **`current_model` is `null` for fallback**: The field means "model actively used by the current provider." Fallback is rule-based with no model.
- **500-char focus hint limit**: Focus hints are content-emphasis directives, not prompt rewrites or VQA queries. Short limit signals intent and bounds injection surface.
- **VQA deferred**: Needs a dedicated `answers` response field and query-aware extraction path. Future version.
