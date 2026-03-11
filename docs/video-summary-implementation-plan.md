# Video Summary App Implementation Plan

## Goal

Build a local-first web app for Apple Silicon Macs that accepts a video URL, retrieves captions when possible, falls back to on-device transcription when necessary, and generates bilingual chapter summaries in English and Simplified Chinese.

## Non-Goals

- Multi-user accounts or authentication
- Cloud-hosted inference or managed queues
- OCR, speaker diarization, or video frame analysis
- Chat-based Q&A over summaries in v1

## Architecture

The system is split into a FastAPI backend and a React frontend.

1. The frontend submits a URL and polls for job status.
2. The backend persists a job in SQLite.
3. A local worker claims queued jobs and runs the pipeline:
   - inspect the video provider
   - fetch captions/subtitles with `yt-dlp`
   - download audio and run ASR if captions are missing or weak
   - normalize transcript segments
   - segment transcript into chapters
   - generate structured bilingual summaries
4. The backend stores the final result payload and local artifacts.

## Core Stack

- Python 3.11+
- FastAPI and Pydantic
- SQLite for job persistence
- `yt-dlp` for provider support and media extraction
- `ffmpeg` for audio conversion
- `mlx-whisper` with Whisper `large-v3` or `large-v3-turbo`
- `mlx-lm` with `mlx-community/Qwen3.5-9B-Instruct-4bit`
- React, TypeScript, Vite, and TanStack Query

## Model Defaults

- Summarizer: `mlx-community/Qwen3.5-9B-Instruct-4bit`
- ASR: Whisper `large-v3-turbo`
- Output languages: English and Simplified Chinese
- Ingest mode: `captions_first`

## API Contracts

### `POST /jobs`

Request:

```json
{
  "url": "https://www.youtube.com/watch?v=example",
  "output_languages": ["en", "zh-CN"],
  "mode": "captions_first"
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### `GET /jobs/{job_id}`

Returns job status, stage, provider, detected language, timestamps, and error details if present.

### `GET /jobs/{job_id}/result`

Returns source metadata, transcript segments, chapters, overall summary, and artifact paths.

## Result Shapes

### Transcript Segment

```json
{
  "start_s": 0.0,
  "end_s": 11.2,
  "text": "segment text",
  "language": "en",
  "source": "captions",
  "confidence": 0.98
}
```

### Chapter Summary

```json
{
  "start_s": 0.0,
  "end_s": 420.0,
  "title": "Introduction and problem framing",
  "summary_en": "English summary",
  "summary_zh": "中文总结",
  "key_points": ["point one", "point two"]
}
```

### Overall Summary

```json
{
  "summary_en": "English overall summary",
  "summary_zh": "中文整体总结",
  "highlights": ["highlight one", "highlight two"]
}
```

## Job Lifecycle

- `queued`: accepted and waiting for worker claim
- `running`: active pipeline execution
- `completed`: result available
- `failed`: terminal error with message

Pipeline progress stages:

- `queued`
- `inspecting_source`
- `fetching_captions`
- `downloading_audio`
- `transcribing_audio`
- `normalizing_transcript`
- `chaptering`
- `summarizing`
- `completed`

## Test Matrix

- YouTube video with official subtitles
- bilibili video requiring ASR fallback
- English-only, Chinese-only, and mixed-language videos
- Unsupported URL or extractor failure
- Long-form video over 90 minutes
- Summary response schema validation
- Backend restart recovery for queued/running jobs

## Local Setup Requirements

- Apple Silicon Mac with 16 GB RAM minimum, 32 GB preferred
- Xcode Command Line Tools
- Homebrew
- `ffmpeg`, `yt-dlp`, and `pnpm`
- Python virtual environment managed by `uv`

## Implementation Notes

- The backend exposes internal service boundaries so summarization or ASR backends can be swapped without changing API contracts.
- The summarizer defaults to MLX Qwen but ships with a deterministic fallback summarizer to keep the app operable before model dependencies are installed.
- “Any supported URL” means any provider supported by `yt-dlp`, not arbitrary embedded video pages.

## Current Status

- FastAPI backend, React frontend scaffold, SQLite persistence, and local artifact storage are implemented.
- The backend supports captions-first ingestion with `yt-dlp`, ASR fallback via `mlx-whisper`, heuristic chaptering, and bilingual summary output.
- Real smoke tests have completed successfully for bilibili and YouTube URLs using `scripts/test_video_job.sh`.
- Subtitle fetching is now sequential and priority-based:
  - prefer English subtitles
  - otherwise prefer Chinese subtitles
  - otherwise use other available subtitle languages
  - tolerate partial subtitle-language failures instead of failing the job immediately

## Known Gaps

- VTT cleanup for provider-specific inline markup is still incomplete.
- The MLX summarizer integration is wired but the default smoke-test flow still uses the deterministic fallback summarizer unless `OVS_ENABLE_MLX_SUMMARIZER=true`.
- There is no packaged desktop distribution yet; the app is currently run as local backend plus frontend processes.

