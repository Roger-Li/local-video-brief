# Local Video Brief

Local-first video summarization for Apple Silicon Macs. The app ingests YouTube, bilibili, and other `yt-dlp`-compatible video URLs, prefers platform captions, falls back to local ASR, and produces bilingual English/Chinese chapter summaries.

## Stack

- Backend: FastAPI, SQLite, subprocess adapters for `yt-dlp` and `ffmpeg`
- Frontend: React, TypeScript, Vite
- ASR: `mlx-whisper` with Whisper `large-v3` or `large-v3-turbo`
- Summarization: `mlx-lm` with Qwen3.5 (default `Qwen3.5-9B-Instruct-4bit`, tested with `Qwen3.5-27B-6bit`)

## Repo Layout

- `docs/video-summary-implementation-plan.md`: implementation contract
- `backend/`: FastAPI app, job worker, persistence, and pipeline services
- `frontend/`: React UI for job submission and result inspection

## Local Setup

### Prerequisites

1. Apple Silicon Mac
2. Python 3.11+
3. Node 20+
4. `uv`
5. `pnpm`
6. `ffmpeg`
7. `yt-dlp`

Install macOS dependencies:

```bash
brew install ffmpeg yt-dlp pnpm
```

### Backend

```bash
uv sync
uv run uvicorn backend.app.main:app --reload
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

## Environment

Copy `.env.example` to `.env` and adjust paths or model identifiers as needed. The backend now auto-loads `.env` from the repo root when started from this project.

For real bilibili tests that need ASR fallback:

```bash
uv sync --extra mlx
```

Then set:

```bash
OVS_ENABLE_MLX_ASR=true
OVS_ENABLE_MLX_SUMMARIZER=true
```

For a real end-to-end smoke test against the bilibili URL used during development:

```bash
./scripts/test_video_job.sh
```

That script starts an isolated backend on port `8010`, forces `OVS_ENABLE_MLX_ASR=true`, submits the test URL, polls until completion, and saves the result JSON under `artifacts/test-runs/`.

You can also pass a different URL or use an external Python environment:

```bash
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=Lk_OQufs1HQ"

# Use a different Python env and enable MLX summarization
OVS_TEST_PYTHON=$HOME/ml-env/bin/python \
OVS_TEST_ENABLE_MLX_SUMMARIZER=true \
./scripts/test_video_job.sh "https://www.youtube.com/watch?v=oeqPrUmVz-o"
```

## Current Workflow

1. Submit a URL through the frontend or `POST /jobs`.
2. The backend inspects the provider with `yt-dlp`.
3. Caption retrieval is attempted one language at a time (English first, then Chinese, then others).
4. If no usable captions are found, the pipeline downloads audio and runs `mlx-whisper`.
5. Transcript normalization deduplicates rolling captions, strips markup, and merges short fragments.
6. Chaptering splits by gaps/duration, with a density-aware second pass for dense single-chapter transcripts.
7. The MLX summarizer generates bilingual chapter summaries and an overall summary.
8. Results, transcripts, and debug artifacts are stored in SQLite plus local artifact directories.

## Smoke Test Outputs

- Successful end-to-end summaries from `scripts/test_video_job.sh` are written to `artifacts/test-runs/<job-id>-result.json`.
- Per-job artifacts are written to `artifacts/<job-id>/`:
  - `transcript_raw.json` and `transcript_normalized.json` (before/after normalization)
  - `summarizer_prompt.txt` and `summarizer_raw_output.txt` (LLM debugging)
  - `source.*.vtt` (downloaded subtitle files)
- The isolated backend log is written to `artifacts/test-runs/backend-8010.log`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OVS_ENABLE_MLX_ASR` | `false` | Enable local Whisper ASR for captionless videos |
| `OVS_ENABLE_MLX_SUMMARIZER` | `false` | Enable MLX LLM summarization (requires `mlx-lm`) |
| `OVS_ENABLE_TRANSCRIPT_NORMALIZATION` | `true` | Enable transcript dedup/cleanup before chaptering |
| `OVS_SUMMARIZER_MODEL` | `Qwen3.5-9B-Instruct-4bit` | MLX model repo for summarization |
| `OVS_ASR_MODEL` | `large-v3-turbo` | Whisper model (alias or full MLX repo id) |
| `OVS_MAX_CHAPTER_MINUTES` | `8` | Max chapter duration before forced split |
| `OVS_SUMMARIZER_MAX_TOKENS` | `2048` | Base max tokens for LLM generation |

## Known Limitations

- The fallback summarizer is intentionally simple and mainly exists to validate the pipeline without requiring `mlx-lm`.
- Caption availability and rate limits are source-dependent; the pipeline tolerates partial subtitle-language failures, but providers can still block requests entirely.
- Transcript normalization handles most rolling-caption patterns but may leave residual duplication in edge cases.
- The summarizer worker processes jobs sequentially; concurrent submissions queue up.

## Notes

- If captions are unavailable and `mlx-whisper` is not installed, the job fails with an actionable error.
- If `mlx-lm` is unavailable, the app falls back to a deterministic summarizer so the rest of the pipeline remains testable.
- `OVS_ASR_MODEL` should be an MLX Whisper repo id such as `mlx-community/whisper-large-v3-turbo`. Short aliases like `large-v3-turbo` are also accepted by the app.
