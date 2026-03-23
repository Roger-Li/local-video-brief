from __future__ import annotations

import logging
import time
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.utils.text import detect_language

logger = logging.getLogger(__name__)

ASR_MODEL_ALIASES = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large": "mlx-community/whisper-large",
    "large-v2": "mlx-community/whisper-large-v2",
    "large-v3": "mlx-community/whisper-large-v3",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MissingAsrDependencyError(RuntimeError):
    pass


def resolve_asr_model_name(model_name: str) -> str:
    return ASR_MODEL_ALIASES.get(model_name, model_name)


class MlxWhisperAsrService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio_path: Path) -> list[dict]:
        if not self.settings.enable_mlx_asr:
            raise MissingAsrDependencyError(
                "ASR fallback requires mlx-whisper. Set OVS_ENABLE_MLX_ASR=true after installing optional MLX dependencies."
            )

        try:
            from mlx_whisper import transcribe  # type: ignore[import-not-found]
        except ImportError as exc:
            raise MissingAsrDependencyError(
                "mlx-whisper is not installed. Run `uv sync --extra mlx` and set OVS_ENABLE_MLX_ASR=true."
            ) from exc

        model_name = resolve_asr_model_name(self.settings.asr_model)
        audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info("ASR start: model=%s audio=%s (%.1f MB)", model_name, audio_path.name, audio_size_mb)
        t0 = time.perf_counter()
        result = transcribe(
            str(audio_path),
            path_or_hf_repo=model_name,
        )
        elapsed = time.perf_counter() - t0
        logger.info("ASR transcription complete in %.1fs, language=%s", elapsed, result.get("language", "?"))

        segments: list[dict] = []
        for segment in result.get("segments", []):
            text = segment.get("text", "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start_s": float(segment.get("start", 0.0)),
                    "end_s": float(segment.get("end", 0.0)),
                    "text": text,
                    "language": result.get("language") or detect_language(text),
                    "source": "asr",
                    "confidence": None,
                }
            )
        total_chars = sum(len(s["text"]) for s in segments)
        duration_s = segments[-1]["end_s"] if segments else 0
        logger.info("ASR result: %d segments, %d chars, %.0fs audio duration", len(segments), total_chars, duration_s)
        return segments
