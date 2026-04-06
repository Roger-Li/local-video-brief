# Roadmap

## Shipped

- **Hierarchical + hybrid summarization routing** — MLX and oMLX providers select single-shot / per-chapter / hierarchical strategy based on content size. Full chapter coverage for long lectures.
- **oMLX remote summarizer** — OpenAI-compatible endpoint support for remote model servers. Non-streaming, with fallback to rule-based on failure.
- **Transcript normalization** — Rolling-caption dedup, sound-marker filtering, short-fragment merge. Runs between caption parsing and chaptering.
- **Deterministic study pack** — Structured study guide from chapter summaries with section refinement for oversized chapters. Behind `OVS_ENABLE_STUDY_PACK` flag.
- **Frontend tabbed result view** — Summary | Study Guide | Transcript tabs with Markdown/HTML export.
- **Per-job options** — `enable_study_pack` and `enable_transcript_normalization` toggleable per job from the frontend UI. Server defaults as fallback.
- **Configurable prompts and model selection** — Style presets (default, detailed, concise, technical, academic), content-focus hints, and oMLX model override from the frontend. `GET /config` endpoint with capability flags gates UI controls per provider. Token budgets clamped to avoid exceeding provider limits.
- **Power mode (v3)** — Opt-in expert path: editable summary brief, force single-shot toggle, and free-form prose/markdown output. `GET /config/power-prompt-default` derives the brief from guided settings. Multi-step paths (per-chapter, hierarchical) produce prose through power-specific prompts. Study pack skipped for power mode. Spec: `docs/specs/configurable-prompts-v3-power-mode.md`.

## Future

### 1. Flexible Chunking and Splitting Controls

Expose chunking strategy and context window assumptions to the user. Some local models support long enough context for single-shot summarization + Q&A without chapter splitting. Add overrides for `max_input_chars` and a "force single-shot" toggle. (Note: Power mode's `force_single_shot` strategy already addresses part of this.)

### 2. Parallel Multi-Video Summarization

Batch processing of multiple videos simultaneously. The current sequential worker is the bottleneck. Needs a worker pool or async queue.

### 3. Podcast and Audio-Only Support

Accept RSS feeds, direct audio files, and podcast URLs — not just YouTube/bilibili. yt-dlp handles some podcasts already; the gap is direct audio file input without a video URL.

### 4. Browser Extension / Desktop App

Detect YouTube/bilibili video pages, trigger summary jobs against the local backend, and display results in a sidebar overlay. Nice-to-have, not urgent.
