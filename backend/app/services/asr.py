from __future__ import annotations

from pathlib import Path

from backend.app.core.config import Settings
from backend.app.utils.text import detect_language

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

        result = transcribe(
            str(audio_path),
            path_or_hf_repo=resolve_asr_model_name(self.settings.asr_model),
        )
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
        return segments
