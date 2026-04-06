# Configurable Prompts v3 — Power Mode

## Context

This is a new spec doc. v2 (`docs/specs/configurable-prompts-v2.md`) is fully implemented and committed. This document describes v3 as an additive layer on top of v2 — nothing in v2 changes unless explicitly stated.

The v2 system provides guided prompt customization: style presets (`default`, `detailed`, `concise`, `technical`, `academic`), content-focus hints, and oMLX model override. These controls are useful but opaque — users pick from a menu and trust the system to construct a good prompt. Advanced users running capable local LLMs (32B+ parameter models on Apple Silicon, or powerful remote models via oMLX) increasingly want to see and edit the summarization brief, skip automatic chapter splitting, and get prose output without JSON schema overhead.

---

## Why v3 Exists

v2 solved "let users influence the prompt." v3 solves "let power users see, edit, and simplify the prompt."

Specific friction points v3 addresses:

1. **Opaque prompts.** Users select `Detailed` + a focus hint but can't see what the model actually receives. When output quality is off, they have no lever to fine-tune beyond switching presets.
2. **Forced chaptering.** The automatic strategy router (`_choose_strategy`) splits long transcripts into chapter→chunk→synthesis pipelines. For models with 32K+ context, a 45-minute lecture often fits in a single shot. Power users want to skip the multi-step pipeline and get a holistic summary.
3. **JSON schema overhead.** The structured output contract (`chapters[]` + `overall_summary` with `summary_en`, `summary_zh`, `key_points`, `highlights`) consumes prompt tokens and constrains what the model can say. When a user just wants "a good summary," the schema is pure overhead.

**Relationship to v2:** v3 is additive. Guided mode (v2) remains the default for all users. Power mode is an opt-in expert path that reuses v2's prompt foundation as a starting point.

### Terminology

- **Guided mode**: The v2 prompt customization system (presets, focus hints, model override). Produces structured JSON output.
- **Power mode**: The v3 opt-in expert path. Produces free-form prose/markdown output. The user edits a "summary brief" — the human-readable instruction portion of the prompt — while the backend controls output format and transcript delivery separately.
- **Summary brief**: The editable text in Power mode. This is _not_ the raw system message. It is a distilled, human-readable instruction derived from the current guided configuration (preset + focus hint), which the user can revise. The backend places it in the user message alongside the transcript.

---

## Product Goals

- Let power users see an editable summary brief derived from their guided configuration, then revise it freely.
- Let power users force single-shot summarization regardless of transcript length.
- Let power users get prose/markdown output instead of structured JSON — simpler prompts, richer output.
- Keep the default experience unchanged. Normal users never see Power mode unless they look for it.
- Minimal complexity increase — this is not a prompt lab or freeform output designer.

## Non-Goals

- Exposing the raw multi-part system messages (single-shot, chunk-note, chapter-synthesis, overall-synthesis are internal implementation details).
- Freeform output schema editing (users don't define their own JSON structures).
- Multi-turn prompt chains or prompt versioning/history.
- Streaming output display.
- Changing the v2 guided mode behavior in any way.
- Supporting Power mode for the `fallback` (rule-based) provider — it has no LLM to prompt.
- Replacing the existing summarizer architecture or removing chaptering/hierarchical support.

---

## User Experience Design

### Mode Switching

The options panel gains a mode toggle below the existing summarization controls:

```
┌─────────────────────────────────────────────────┐
│ Video URL: [____________________________________]│
│                                                  │
│ [Options]                                        │
│ ┌──────────────────────────────────────────────┐ │
│ │ ☑ Generate study guide                       │ │
│ │ ☑ Normalize transcript                       │ │
│ │                                              │ │
│ │ Summarization                                │ │
│ │ [Default] [Detailed] [Concise] ...           │ │
│ │ Content focus: [________________________]    │ │
│ │ Model override: [______]                     │ │
│ │                                              │ │
│ │ ── Mode ──────────────────────────────────── │ │
│ │ ( Guided )  ( Power )                        │ │
│ │                                              │ │
│ └──────────────────────────────────────────────┘ │
│ [Create summary job]                             │
└─────────────────────────────────────────────────┘
```

- **Guided** (default): Current v2 behavior. No changes.
- **Power**: Reveals the power mode panel described below.

The mode toggle is only visible when `supports_power_mode` is `true` in the server config (LLM providers only).

### Power Mode Panel

When Power mode is selected:

```
┌──────────────────────────────────────────────────┐
│ ── Mode ──────────────────────────────────────── │
│ ( Guided )  (•Power )                            │
│                                                  │
│ Strategy: (•Auto) ( Single-shot )                │
│                                                  │
│ Summarization prompt:                            │
│ ┌──────────────────────────────────────────────┐ │
│ │ You are a multilingual video summarization   │ │
│ │ model. Summarize the provided transcript in  │ │
│ │ a clear, well-structured format. Cover the   │ │
│ │ main topics, key arguments, and important    │ │
│ │ details. Use both English and Chinese.       │ │
│ │                                              │ │
│ │ Provide thorough summaries with extensive    │ │
│ │ key points covering all major arguments and  │ │
│ │ examples.                                    │ │
│ │                                              │ │
│ │ Content focus: Emphasize the mathematical    │ │
│ │ proofs and derivations.                      │ │
│ │                                              │ │
│ │                                    [Reset]   │ │
│ └──────────────────────────────────────────────┘ │
│ 312 / 2000 chars                                 │
│                                                  │
│ ⓘ Output will be free-form text. The model's     │
│   response is displayed as-is (no structured     │
│   chapter cards).                                │
└──────────────────────────────────────────────────┘
```

Key UX behaviors:

1. **Summary brief textarea is pre-populated from the backend.** When the user switches to Power mode, the frontend calls `GET /config/power-prompt-default` (see Backend Design) with the current guided state (preset, focus hint). The backend returns the default summary brief text, which the textarea displays. This is the starting point, not a blank canvas. The backend is the single source of truth for prompt derivation — the frontend never assembles prompt text itself.

2. **Guided controls remain visible and functional above.** Changing the preset or focus hint in guided controls re-fetches the default brief from the backend. If the user has edited the brief, a confirmation asks whether to overwrite ("Reset brief to match guided settings?") or keep edits.

3. **Reset button** re-fetches and restores the textarea to the current guided-derived default.

4. **Strategy toggle**: `Auto` (default) uses the existing `_choose_strategy` routing. `Single-shot` forces the single-shot path regardless of transcript length.

5. **Character limit**: 2000 chars for the editable brief. This is the instruction text only — the backend controls output format rules and transcript delivery separately.

6. **Info line** clarifies that Power mode output is free-form text, not structured chapter cards. This sets expectations.

### Output Display

When a job completes with Power mode:

- The result view shows the model's final prose output in a single panel, rendered as markdown.
- The Summary tab displays the prose. Chapter cards and key-points lists are absent.
- The Study Guide tab is hidden (study pack is not generated for power mode jobs).
- The Transcript tab works as usual.

---

## Backend Design

### New `JobOptions` Fields

**Edit: `backend/app/schemas/jobs.py`**

```python
class JobOptions(BaseModel):
    # ... existing v2 fields ...
    power_mode: Optional[bool] = None            # enable power mode
    power_prompt: Optional[str] = None           # user-edited summary brief
    strategy_override: Optional[str] = None      # "auto" | "force_single_shot"
```

Validators:
- `power_prompt`: strip whitespace, reject if > 2000 chars, `None` if empty.
- `strategy_override`: must be `None`, `"auto"`, or `"force_single_shot"`.
- `power_mode: false` or `None` → all power fields ignored (guided mode).

No DB migration needed — `options` is a JSON TEXT column.

### New Result Field

**Edit: `backend/app/schemas/jobs.py`**

```python
class JobResultResponse(BaseModel):
    # ... existing fields ...
    raw_summary_text: Optional[str] = None   # power mode prose output
```

When `raw_summary_text` is present, `chapters` and `overall_summary` are populated with empty stubs (`[]` and `{"summary_en": "", "summary_zh": "", "highlights": []}`) for schema compatibility. The frontend checks `raw_summary_text` first and renders prose when present.

### `GET /config` Extension

**Edit: `backend/app/api/config.py`**

Add to the existing response:

```python
"supports_power_mode": supports_prompts,  # same gate as prompt customization
```

Power mode requires an LLM provider. Same condition as `supports_prompt_customization` — `true` for `mlx`/`omlx` with runtime available, `false` for `fallback`.

### `GET /config/power-prompt-default` — Server-Side Default Brief

**New endpoint in: `backend/app/api/config.py`**

The backend is the single source of truth for how guided settings translate into a default summary brief. This avoids the frontend needing to approximate prompt text from preset descriptions.

```python
@router.get("/config/power-prompt-default")
def get_power_prompt_default(
    style_preset: str | None = None,
    focus_hint: str | None = None,
) -> dict:
    """Return the default editable summary brief for Power mode,
    derived from the given guided configuration."""
    return {"default_prompt": build_power_default_brief(style_preset, focus_hint)}
```

**`build_power_default_brief()`** lives in `summarizer.py` alongside the other prompt builders. It composes a human-readable brief from the preset's `system_suffix` and the focus hint:

```python
def build_power_default_brief(
    style_preset_id: str | None = None,
    focus_hint: str | None = None,
) -> str:
    """Derive a human-readable summary brief from guided settings.

    This is what pre-populates the Power mode textarea. It uses the
    preset's actual system_suffix (not the UI description), so the
    user sees the real instruction text that guided mode would apply.
    """
    preset = _resolve_preset(style_preset_id)

    parts = [
        "You are a multilingual video summarization model. "
        "Summarize the provided transcript clearly and thoroughly. "
        "Cover the main topics, key arguments, and important details. "
        "Produce output in both English and Chinese."
    ]

    if preset.system_suffix:
        parts.append(preset.system_suffix)

    if focus_hint and focus_hint.strip():
        parts.append(f"Content focus: {focus_hint.strip()}")

    return "\n\n".join(parts)
```

Key design decisions:
- Uses `preset.system_suffix` (the actual instruction text), not `preset.description` (the UI label). This means the user sees "Provide thorough summaries with extensive key points covering all major arguments and examples." — the real guided instruction — not the abbreviated "Thorough summaries with extensive key points."
- The brief is strategy-agnostic. Guided mode has different prompts per strategy (single-shot, chunk-note, chapter-synthesis, overall-synthesis), but the brief captures the user's _intent_ — tone, focus, depth — not the internal routing mechanics. The backend still controls how the brief is woven into the actual LLM call for each strategy path.
- The base text is a simplified version of the core instruction that appears in all guided strategy paths, without JSON schema rules or sentence-count directives (those don't apply to prose output).

### Pipeline Changes

**Edit: `backend/app/services/pipeline.py`**

The pipeline continues to call `self.summary_generator.summarize()` unconditionally — the same single entry point as today (`pipeline.py:167`, `interfaces.py:48`). It passes `job_options` as it already does. Power mode branching happens inside the provider classes, not in the pipeline.

When the summarizer returns a result with `raw_summary_text`, the pipeline:
1. Skips study pack generation (study pack depends on structured `chapters` data).
2. Stores the result as-is. The `raw_summary_text` field flows through to the API response.
3. Artifacts (`summarizer_prompt.txt`, `summarizer_raw_output.txt`, `summarizer_strategy.txt`) are still saved by the summarizer for debugging.

### Summarizer Changes

**Edit: `backend/app/services/summarizer.py`**

The `SummaryGenerator` protocol and `summarize()` signature remain unchanged. Each LLM provider's `summarize()` checks `job_options.get("power_mode")` internally and branches:

```python
def summarize(self, ..., job_options=None) -> dict:
    opts = job_options or {}

    if opts.get("power_mode"):
        return self._summarize_power(
            source_metadata, transcript_segments, chapters,
            output_languages, artifact_dir, progress_callback, opts,
        )

    # ... existing guided-mode logic (unchanged) ...
```

**`_summarize_power()`** is a private method on `MlxQwenSummaryGenerator` and `OmlxSummaryGenerator`. It:
1. Resolves `power_prompt` (fall back to `build_power_default_brief()` if empty).
2. Resolves `strategy_override` (`"auto"` or `"force_single_shot"`).
3. Resolves `omlx_model_override` from `job_options` — same as guided mode (`summarizer.py:994`). Power mode honors per-job model override for oMLX. MLX ignores it, same as guided mode.
4. Builds the system message (protected format rules — see Prompt-Building Architecture).
5. Builds the user message (summary brief + transcript — see Prompt-Building Architecture).
6. Routes based on strategy, calling the LLM for prose output. Threads `model_override` to `_call_omlx()` / `_call_llm()`.
7. Returns `{"raw_summary_text": <final_prose>, "chapters": [], "overall_summary": {...stub...}}`.

**`RuleBasedSummaryGenerator`**: `power_mode` is ignored — `summarize()` runs its normal rule-based path. The frontend hides the Power mode toggle for the fallback provider via `supports_power_mode: false` in `/config`. If an API caller sends `power_mode: true` to a fallback provider, the option is silently ignored and structured output is returned as usual.

This preserves the current service boundary: the pipeline only knows about `summarize()`, and provider-specific logic stays inside the summarizer classes.

---

## Frontend Design

### State Management

**Edit: `frontend/src/components/JobForm.tsx`**

New state:
```typescript
const [powerMode, setPowerMode] = useState(false);
const [powerPrompt, setPowerPrompt] = useState("");
const [powerPromptDirty, setPowerPromptDirty] = useState(false);  // user has edited the brief
const [strategyOverride, setStrategyOverride] = useState<"auto" | "force_single_shot">("auto");
```

### Default Brief Derivation (Server-Side)

The frontend does **not** assemble prompt text. It fetches the default summary brief from the backend:

**Edit: `frontend/src/lib/api.ts`**

Uses the existing `request()` helper which handles `VITE_API_BASE_URL` and error checking:

```typescript
interface PowerPromptDefaultResponse {
  default_prompt: string;
}

export async function getPowerPromptDefault(
  stylePreset?: string | null,
  focusHint?: string,
): Promise<string> {
  const params = new URLSearchParams();
  if (stylePreset) params.set("style_preset", stylePreset);
  if (focusHint?.trim()) params.set("focus_hint", focusHint.trim());
  const data = await request<PowerPromptDefaultResponse>(
    `/config/power-prompt-default?${params}`,
  );
  return data.default_prompt;
}
```

When `powerMode` toggles to `true`, call `getPowerPromptDefault()` with the current guided state and populate `powerPrompt`. Track whether the user has edited the brief with `powerPromptDirty`.

When guided controls (preset, focus hint) change while `powerMode` is `true`:
- If `powerPromptDirty` is `false`: silently re-fetch and update `powerPrompt`.
- If `powerPromptDirty` is `true`: show confirmation ("Reset brief to match guided settings?"). If accepted, re-fetch and set `powerPromptDirty = false`. If declined, keep the user's edits.

### `buildOptions()` Update

```typescript
if (powerMode && supportsPowerMode) {
  opts.power_mode = true;
  if (powerPrompt.trim()) opts.power_prompt = powerPrompt.trim();
  if (strategyOverride !== "auto") opts.strategy_override = strategyOverride;
}
```

When power mode is on, guided prompt fields (`style_preset`, `focus_hint`) are still sent — they serve as metadata context and as the fallback if `power_prompt` is empty.

### Result Display

**Edit: `frontend/src/components/ResultView.tsx`**

```typescript
// Presence check, not truthy — an empty string "" from a power mode job
// should still render the power mode UI (not fall through to structured stubs).
const isPowerResult = result.raw_summary_text != null;  // !== undefined && !== null

if (isPowerResult) {
  // Render raw_summary_text as markdown in a single panel — no chapter cards, no key points.
  // If raw_summary_text is "", show an empty-state message ("No summary content was generated.").
} else {
  // Existing structured rendering (unchanged)
}
```

Study Guide tab hidden when `raw_summary_text` is present and `study_pack` is null. The existing tab-hiding logic (`hidden: !hasStudyPack`) already handles this — study pack will be `null` for power mode jobs.

### Type Changes

**Edit: `frontend/src/types/api.ts`**

```typescript
export interface JobOptions {
  // ... existing ...
  power_mode?: boolean;
  power_prompt?: string;
  strategy_override?: "auto" | "force_single_shot";
}

export interface JobResultResponse {
  // ... existing ...
  raw_summary_text?: string | null;
}

export interface ServerConfig {
  // ... existing ...
  supports_power_mode: boolean;
}
```

---

## Prompt-Building Architecture

### Protected vs. Editable Boundary

Power mode separates the prompt into two message roles with different trust levels:

```
┌─ SYSTEM MESSAGE (protected, backend-controlled) ──┐
│                                                     │
│ "You are a video summarization assistant.            │
│  Output your response as clear, well-structured     │
│  text using markdown formatting. Use headings and   │
│  bullet points where appropriate.                   │
│  Do NOT output JSON. Do NOT wrap your response in   │
│  code fences."                                      │
│                                                     │
└─────────────────────────────────────────────────────┘

┌─ USER MESSAGE (editable brief + transcript data) ──┐
│                                                     │
│ "Summarization instructions:                        │
│  Summarize the provided transcript clearly and      │
│  thoroughly. Cover the main topics, key arguments,  │
│  and important details. Produce output in both      │
│  English and Chinese.                               │
│                                                     │
│  Provide thorough summaries with extensive key      │
│  points covering all major arguments and examples.  │
│                                                     │
│  Content focus: mathematical proofs and derivations. │
│  ---                                                │
│  Video metadata: {...}                              │
│                                                     │
│  Transcript:                                        │
│  [0s - 120s] Introduction                           │
│  ..."                                               │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Why this split matters:** Placing the user-edited brief in the **user message** and the non-negotiable format rules in the **system message** gives the format rules higher priority in the model's attention. If the user's brief accidentally contradicts the format rules (e.g., "output as JSON"), the system message takes precedence. This is the same pattern v2 uses for focus hints (user message) vs. JSON schema enforcement (system message).

The user cannot override the system message. The system message is short, fixed, and never exposed to the UI.

### Concrete System Message

```python
_POWER_MODE_SYSTEM = (
    "You are a video summarization assistant. "
    "Output your response as clear, well-structured text using markdown formatting. "
    "Use headings and bullet points where appropriate. "
    "Do NOT output JSON. Do NOT wrap your response in code fences."
)
```

This is a constant. It does not vary by preset, focus hint, or user input.

### User Message Construction

```python
def _build_power_user_msg(
    power_prompt: str,
    source_metadata: dict,
    chapters: list[dict],
) -> str:
    brief_metadata = {
        k: source_metadata[k]
        for k in ("title", "description", "duration", "upload_date", "channel", "tags")
        if k in source_metadata
    }
    transcript_text = "\n\n".join(
        f"[{ch['start_s']:.0f}s - {ch['end_s']:.0f}s] {ch.get('title_hint', '')}\n{ch['text']}"
        for ch in chapters
    )
    return (
        f"Summarization instructions:\n{power_prompt}\n"
        f"---\n"
        f"Video metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n\n"
        f"Transcript:\n{transcript_text}"
    )
```

The user's editable brief is placed at the top of the user message, clearly delimited from the transcript data. No JSON schema example, no rules block, no output contract.

### Fallback When `power_prompt` Is Empty

If `power_mode` is `True` but `power_prompt` is `None`/empty, the backend calls `build_power_default_brief()` with the job's guided settings (`style_preset`, `focus_hint`) to produce a usable brief. This ensures every power mode job has a meaningful instruction even if the frontend sends an empty string.

---

## Strategy / Routing Behavior

### `auto` (Default)

Uses the existing `_choose_strategy()` logic (`summarizer.py:440`). In Power mode with `auto`, the three-way router still applies, but each stage uses power-specific prompt builders instead of the structured JSON prompts.

#### Single-shot path

One call, full transcript. `_build_power_user_msg()` constructs the user message with the brief + all chapter text. `raw_summary_text` is the model's output verbatim.

#### Per-chapter path

When chapters individually fit within `max_input_chars` but the total exceeds the single-shot threshold:

1. **Per-chapter prose calls.** Each chapter gets its own LLM call. The system message is `_POWER_MODE_SYSTEM` (same constant). The user message is built by a new helper:

    ```python
    def _build_power_chapter_user_msg(
        power_prompt: str,
        chapter: dict,
        chapter_index: int,
        total_chapters: int,
    ) -> str:
        return (
            f"Summarization instructions:\n{power_prompt}\n"
            f"---\n"
            f"Chapter {chapter_index + 1} of {total_chapters}: "
            f"{chapter.get('title_hint', 'Untitled')}\n"
            f"Time range: {chapter['start_s']:.0f}s - {chapter['end_s']:.0f}s\n\n"
            f"{chapter['text']}"
        )
    ```

    The user's brief is included in every chapter call so the model follows the user's instructions consistently.

2. **Overall synthesis call.** After all chapter prose is collected, a final call synthesizes them. The system message is `_POWER_MODE_SYSTEM`. The user message:

    ```python
    def _build_power_overall_user_msg(
        power_prompt: str,
        source_metadata: dict,
        chapter_proses: list[str],
    ) -> str:
        chapters_block = "\n\n".join(
            f"[Chapter {i+1}]\n{prose}" for i, prose in enumerate(chapter_proses)
        )
        brief_metadata = {k: source_metadata[k] for k in (...) if k in source_metadata}
        return (
            f"Summarization instructions:\n{power_prompt}\n\n"
            f"Below are per-chapter summaries. Synthesize them into a single "
            f"overall summary of the entire video.\n"
            f"---\n"
            f"Video metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n\n"
            f"Chapter summaries:\n{chapters_block}"
        )
    ```

3. **`raw_summary_text`** in the API response is the **final overall synthesis only**. Intermediate chapter prose is saved as artifacts (`artifacts/<job-id>/ch<N>/power_chapter_prose.txt`) for debugging but not included in the response.

#### Hierarchical path

When any single chapter exceeds `max_input_chars`:

1. **Chunk condensation stays internal and fixed.** The existing `_CHUNK_NOTE_SYSTEM` prompt and `_build_chunk_note_user()` helper are reused as-is from the guided path. These produce plain-text notes (not JSON), so they are compatible with power mode without modification. The user's brief is **not** injected into chunk notes — chunk condensation is a mechanical compression step, not a summarization instruction point. The user's brief influences the chapter synthesis and overall synthesis stages.

2. **Chapter synthesis** uses `_build_power_chapter_user_msg()` (above), but with the chunk notes concatenated as the chapter text instead of raw transcript. Same system message (`_POWER_MODE_SYSTEM`).

3. **Overall synthesis** proceeds as in the per-chapter path.

#### Failure handling in multi-step power paths

- **Per-chapter call fails:** Fall back to `RuleBasedSummaryGenerator.summarize_chapter()` to produce a compact rule-based summary for that chapter, then format it as prose (e.g., title + summary_en + key points as bullet list). This matches the guided path's fallback (`summarizer.py:748`, `summarizer.py:1057`) and keeps the overall-synthesis input bounded — using raw transcript text would blow up the synthesis context on exactly the long chapters where this path triggers. Log a warning. Continue to the next chapter.
- **Overall synthesis fails:** Concatenate all chapter prose with headings as the final `raw_summary_text`. This is a degraded but usable result. Log a warning.
- **Chunk-note call fails:** Use raw chunk text as the note (same as guided path at `summarizer.py:733-741`).

This preserves the pipeline's ability to handle very long transcripts that exceed context limits, while giving the user prompt control.

### `force_single_shot`

**This is the primary power-user path.** Bypasses `_choose_strategy()` inside the summarizer — no chapter-based routing, no chunking, no multi-step pipeline within the summarizer. (Chaptering itself still runs in the pipeline before `summarize()` is called at `pipeline.py:157-158`, but `force_single_shot` ignores the chapter boundaries and sends all chapter text as a single flat transcript.) The user's edited brief and the full transcript go to the LLM in a single call. The model's complete output is stored verbatim as `raw_summary_text`. Nothing is parsed, validated, or post-processed.

The user accepts the risk that:
- Very long transcripts may be truncated by the model's context window.
- The single call may time out for extremely long content.

The backend logs a warning when `force_single_shot` is used with transcript length exceeding `summarizer_max_input_chars`, but **never blocks the request**. Note: the existing `_SINGLE_SHOT_UTILISATION` factor (0.7) was calibrated for structured JSON prompt overhead. Power mode's lighter prompt shape means this threshold is too conservative. For the warning in power mode, compare against `summarizer_max_input_chars` directly (utilisation factor = 1.0), or introduce a separate `_POWER_SINGLE_SHOT_UTILISATION = 0.9` to account for the smaller system message overhead.

### Token Budget

Power mode uses the preset's `max_tokens_multiplier` applied to `compute_max_tokens()`. Since there's no JSON overhead, the default token budget is generally sufficient. `force_single_shot` with `detailed` preset on a long video may need the full budget — the existing cap (`base + summarizer_max_tokens`) still applies.

---

## Safeguards and Failure Modes

| Scenario | Behavior |
|----------|----------|
| `power_mode: true` with `fallback` provider | Backend ignores `power_mode`, runs normal rule-based summarization. Frontend hides the toggle. |
| `power_prompt` exceeds 2000 chars | Pydantic validator rejects with 422. |
| `strategy_override` is invalid value | Pydantic validator rejects with 422. |
| `power_prompt` is empty/null with `power_mode: true` | Backend uses server-side guided-derived default prompt. |
| Model returns empty output in Power mode | Store empty `raw_summary_text`, mark job completed. No fallback to structured mode — the user chose power mode deliberately. |
| Model times out in `force_single_shot` | Normal error handling. Job fails with timeout error. User can retry with `auto` strategy or shorter content. |
| `force_single_shot` with transcript > context window | Model truncates or errors. Logged as warning. User sees partial or failed result. |
| Guided controls changed after Power prompt edited | Frontend prompts "Reset prompt to match guided settings?" — user can accept or keep edits. |
| Job submitted with `power_mode: true` + `enable_study_pack: true` | Study pack generation skipped silently. `study_pack: null` in response. |

---

## Manual Testing Plan

### Test Matrix

| # | Mode | Strategy | Prompt | Video Length | What to verify |
|---|------|----------|--------|-------------|----------------|
| 1 | Guided | auto | Default preset, no focus | Short (<10 min) | Baseline: structured JSON output, chapter cards render. Unchanged from v2. |
| 2 | Guided | auto | Detailed + focus hint | Medium (20-30 min) | Structured output with detailed style. Unchanged from v2. |
| 3 | Power | auto | Default power prompt (unedited) | Short (<10 min) | Prose output in `raw_summary_text`. No chapter cards. Markdown renders cleanly. |
| 4 | Power | auto | Edited prompt ("Summarize as a bullet-point outline") | Short (<10 min) | Model follows edited instruction. Output is bullet points, not paragraphs. |
| 5 | Power | force_single_shot | Default power prompt | Medium (20-30 min) | Single LLM call. Prose output covers full video. No per-chapter pipeline artifacts. |
| 6 | Power | force_single_shot | Edited prompt + Detailed preset | Long lecture (45-60 min) | Single call with full transcript. Verify timeout handling if model is slow. Check that output is substantive. |
| 7 | Power | auto | Default power prompt | Long lecture (45-60 min) | Auto routes to multi-step path (per-chapter or hierarchical depending on chapter sizes). `raw_summary_text` is the final overall synthesis only. Intermediate chapter artifacts exist under `artifacts/<job-id>/ch<N>/`. |
| 8 | Power | auto | Default power prompt, then switch back to Guided | Short | Verify mode switch: result is structured JSON again, chapter cards render. |
| 9 | Guided | auto | Any preset | Any | Verify Power mode toggle is hidden when `supports_power_mode` is `false` (fallback provider). |
| 10 | Power | force_single_shot | Default power prompt + study pack enabled | Medium | Study pack is `null`. No error. Job completes normally. |

### Smoke Test Script

Extend `scripts/test_video_job.sh` to accept `OVS_TEST_POWER_MODE=true` and `OVS_TEST_STRATEGY_OVERRIDE=force_single_shot`:

```bash
# Power mode, auto strategy
OVS_TEST_POWER_MODE=true ./scripts/test_video_job.sh "https://youtu.be/..."

# Power mode, force single-shot
OVS_TEST_POWER_MODE=true OVS_TEST_STRATEGY_OVERRIDE=force_single_shot ./scripts/test_video_job.sh "https://youtu.be/..."
```

The script should verify that `raw_summary_text` is present and non-empty in the result JSON.

---

## Acceptance Criteria

### Backend
- [ ] `JobOptions` accepts `power_mode`, `power_prompt`, `strategy_override` with validation.
- [ ] `JobResultResponse` includes `raw_summary_text` field.
- [ ] `GET /config` returns `supports_power_mode` flag.
- [ ] `GET /config/power-prompt-default` returns a default brief derived from preset + focus hint.
- [ ] `build_power_default_brief()` uses `preset.system_suffix` (not `preset.description`).
- [ ] Power mode jobs produce `raw_summary_text` (prose). `chapters` and `overall_summary` are empty stubs.
- [ ] `force_single_shot` bypasses `_choose_strategy()` and makes a single LLM call.
- [ ] `auto` strategy in Power mode routes correctly. `raw_summary_text` is the final overall synthesis; intermediate chapter prose saved as artifacts.
- [ ] Power mode with fallback provider silently ignores `power_mode` and returns structured output.
- [ ] Power prompt empty/null → `build_power_default_brief()` used as fallback.
- [ ] Study pack generation is skipped for power mode jobs.
- [ ] Artifacts saved: `summarizer_prompt.txt`, `summarizer_raw_output.txt`, `summarizer_strategy.txt`.
- [ ] `GET /jobs/{id}/result` maps `raw_summary_text` from `result_payload` (explicit field mapping in `jobs.py:60-73`).
- [ ] Power mode branches inside `summarize()`, not via a separate protocol method. `SummaryGenerator` interface unchanged.
- [ ] Power mode honors `omlx_model_override` — the per-job model override is threaded to `_call_omlx()` in power paths, same as guided mode.

### Frontend
- [ ] Mode toggle (Guided / Power) visible only when `supports_power_mode` is `true`.
- [ ] Switching to Power mode fetches default brief from `GET /config/power-prompt-default`.
- [ ] Strategy radio buttons: Auto / Single-shot.
- [ ] Reset button re-fetches default brief from backend.
- [ ] `powerPromptDirty` tracking: guided control changes re-fetch silently if not dirty, prompt to confirm if dirty.
- [ ] Character counter (N / 2000).
- [ ] Info line about free-form output.
- [ ] `buildOptions()` sends `power_mode`, `power_prompt`, `strategy_override` correctly.
- [ ] Result view: `raw_summary_text` renders as markdown in a single panel. No chapter cards.
- [ ] Study Guide tab hidden when `raw_summary_text` is present and `study_pack` is null.
- [ ] Guided mode result rendering is unchanged.

### Tests
- [ ] Backend unit tests for new `JobOptions` validators.
- [ ] Backend unit tests for `build_power_default_brief()` with various preset/focus combinations.
- [ ] Backend unit tests for `_build_power_user_msg()` (brief in user message, not system).
- [ ] Backend unit tests for `_build_power_chapter_user_msg()` and `_build_power_overall_user_msg()`.
- [ ] Backend unit tests for power mode dispatch inside `summarize()`.
- [ ] Backend unit tests for per-chapter failure fallback (`RuleBasedSummaryGenerator.summarize_chapter()` formatted as prose) and overall synthesis failure fallback (concatenated chapter prose with headings).
- [ ] Backend test: `_POWER_MODE_SYSTEM` does not contain user-editable text.
- [ ] Frontend tests for mode toggle visibility gating.
- [ ] Frontend tests for `getPowerPromptDefault()` API call.
- [ ] Smoke test passes with `OVS_TEST_POWER_MODE=true`.

---

## File Touchpoints

| File | Change |
|------|--------|
| `backend/app/schemas/jobs.py` | Add `power_mode`, `power_prompt`, `strategy_override` to `JobOptions`; add `raw_summary_text` to `JobResultResponse` |
| `backend/app/api/jobs.py` | Map `raw_summary_text` from `result_payload` in `GET /jobs/{id}/result` handler (currently maps fields explicitly at line 60-73 and would drop the new field) |
| `backend/app/api/config.py` | Add `supports_power_mode` to config response; add `GET /config/power-prompt-default` endpoint |
| `backend/app/services/summarizer.py` | Add `_POWER_MODE_SYSTEM`, `build_power_default_brief()`, `_build_power_user_msg()`, `_build_power_chapter_user_msg()`, `_build_power_overall_user_msg()`, `_summarize_power()` as private method on MLX and oMLX classes; branch in `summarize()` |
| `backend/app/services/pipeline.py` | Skip study pack when result contains `raw_summary_text`; pass `raw_summary_text` through to result |
| `backend/app/services/interfaces.py` | **No changes.** `SummaryGenerator` protocol unchanged — power mode branches inside `summarize()` |
| `frontend/src/types/api.ts` | Extend `JobOptions`, `JobResultResponse`, `ServerConfig` |
| `frontend/src/lib/api.ts` | Add `getPowerPromptDefault()` |
| `frontend/src/components/JobForm.tsx` | Mode toggle, strategy radio, power prompt textarea with dirty tracking, reset button |
| `frontend/src/components/ResultView.tsx` | Conditional rendering for `raw_summary_text` (markdown panel) vs structured view |
| `frontend/src/styles.css` | Styles for mode toggle, power prompt textarea, strategy radio |
| `scripts/test_video_job.sh` | Support `OVS_TEST_POWER_MODE` and `OVS_TEST_STRATEGY_OVERRIDE` env vars |

---

## Open Questions / Future Extensions

1. **Prompt templates library.** Users may want to save and reuse edited prompts across jobs. Out of scope for v3 — can be added as a frontend-only feature (localStorage) in a follow-up.

2. **Per-chapter power mode.** Currently Power mode with `auto` strategy produces per-chapter prose internally but returns only the final overall synthesis. A future version could let users provide different instructions per chapter, or surface intermediate per-chapter outputs in the UI before final synthesis.

3. **Structured power mode.** v3 is freeform-only. A future "Power Structured" mode could let users edit the summarization instructions while keeping the JSON output contract. This would sit between Guided and Power Freeform in complexity.

4. **Output format selector.** Instead of hardcoding prose/markdown, let users choose: markdown, bullet points, table, Q&A format. Could be a simple dropdown rather than full prompt editing.

5. **Token/context budget visibility.** Show the user how much of the model's context window the transcript will consume, so they can make informed decisions about `force_single_shot` vs `auto`.

6. **Prompt diff view.** Show what changed between the guided default and the user's edited prompt. Useful for understanding what customization was applied when reviewing past jobs.

7. **Language flexibility in Power mode.** The default brief hardcodes "Produce output in both English and Chinese" because the frontend always submits `output_languages: ["en", "zh-CN"]`. If the API is opened to other language combinations, the default brief should derive its language instruction from the `output_languages` field. For v3, the hardcoded bilingual default is fine — users can edit the brief to change language instructions anyway.
