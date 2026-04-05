# Roadmap

## Shipped

- **Hierarchical + hybrid summarization routing** — MLX and oMLX providers select single-shot / per-chapter / hierarchical strategy based on content size. Full chapter coverage for long lectures.
- **oMLX remote summarizer** — OpenAI-compatible endpoint support for remote model servers. Non-streaming, with fallback to rule-based on failure.
- **Transcript normalization** — Rolling-caption dedup, sound-marker filtering, short-fragment merge. Runs between caption parsing and chaptering.
- **Deterministic study pack** — Structured study guide from chapter summaries with section refinement for oversized chapters. Behind `OVS_ENABLE_STUDY_PACK` flag.
- **Frontend tabbed result view** — Summary | Study Guide | Transcript tabs with Markdown/HTML export.
- **Per-job options** — `enable_study_pack` and `enable_transcript_normalization` toggleable per job from the frontend UI. Server defaults as fallback.

## Future

### 1. Configurable Prompts and Model Selection from UI

Let users pick specific local models, customize prompt questions (e.g. VQA-style queries against transcripts), and choose summarization styles — all from the frontend. Extends the per-job options infrastructure (Phase D v1).

### 2. Flexible Chunking and Splitting Controls

Expose chunking strategy and context window assumptions to the user. Some local models support long enough context for single-shot summarization + Q&A without chapter splitting. Add overrides for `max_input_chars` and a "force single-shot" toggle.

### 3. Parallel Multi-Video Summarization

Batch processing of multiple videos simultaneously. The current sequential worker is the bottleneck. Needs a worker pool or async queue.

### 4. Podcast and Audio-Only Support

Accept RSS feeds, direct audio files, and podcast URLs — not just YouTube/bilibili. yt-dlp handles some podcasts already; the gap is direct audio file input without a video URL.

### 5. Browser Extension / Desktop App

Detect YouTube/bilibili video pages, trigger summary jobs against the local backend, and display results in a sidebar overlay. Nice-to-have, not urgent.
