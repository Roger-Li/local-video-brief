from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
from typing import Iterable, List


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip("'").strip('"')
    if not key:
        return None
    return key, value


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def _candidate_env_files() -> Iterable[Path]:
    cwd_env = Path.cwd() / ".env"
    repo_env = Path(__file__).resolve().parents[3] / ".env"
    seen = set()
    for path in (cwd_env, repo_env):
        if path not in seen:
            seen.add(path)
            yield path


for env_file in _candidate_env_files():
    load_env_file(env_file)


def _csv_env(name: str, default: List[str]) -> List[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _resolve_summarizer_provider() -> str:
    explicit = os.getenv("OVS_SUMMARIZER_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in ("fallback", "mlx", "omlx"):
            raise ValueError(f"OVS_SUMMARIZER_PROVIDER must be fallback, mlx, or omlx (got '{explicit}')")
        return explicit
    if os.getenv("OVS_ENABLE_MLX_SUMMARIZER", "false").lower() == "true":
        return "mlx"
    return "fallback"


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("OVS_APP_NAME", "Local Video Brief"))
    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("OVS_DATABASE_PATH", "data/local_video_brief.sqlite3"))
    )
    artifact_root: Path = field(default_factory=lambda: Path(os.getenv("OVS_ARTIFACT_ROOT", "artifacts")))
    worker_poll_interval: int = field(default_factory=lambda: int(os.getenv("OVS_WORKER_POLL_INTERVAL", "2")))
    default_output_languages: List[str] = field(default_factory=list)
    preferred_caption_languages: List[str] = field(default_factory=list)
    summarizer_provider: str = field(default_factory=_resolve_summarizer_provider)
    summarizer_model: str = field(
        default_factory=lambda: os.getenv(
            "OVS_SUMMARIZER_MODEL",
            "mlx-community/Qwen3.5-9B-Instruct-4bit",
        )
    )
    summarizer_max_input_chars: int = field(
        default_factory=lambda: int(os.getenv("OVS_SUMMARIZER_MAX_INPUT_CHARS", "18000"))
    )
    summarizer_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("OVS_SUMMARIZER_MAX_TOKENS", "2048"))
    )
    enable_mlx_summarizer: bool = field(
        default_factory=lambda: os.getenv("OVS_ENABLE_MLX_SUMMARIZER", "false").lower() == "true"
    )
    enable_mlx_asr: bool = field(
        default_factory=lambda: os.getenv("OVS_ENABLE_MLX_ASR", "false").lower() == "true"
    )
    asr_model: str = field(default_factory=lambda: os.getenv("OVS_ASR_MODEL", "large-v3-turbo"))
    max_chapter_minutes: int = field(default_factory=lambda: int(os.getenv("OVS_MAX_CHAPTER_MINUTES", "8")))
    enable_transcript_normalization: bool = field(
        default_factory=lambda: os.getenv("OVS_ENABLE_TRANSCRIPT_NORMALIZATION", "true").lower() == "true"
    )
    omlx_base_url: str = field(default_factory=lambda: os.getenv("OVS_OMLX_BASE_URL", "").rstrip("/"))
    omlx_model: str = field(default_factory=lambda: os.getenv("OVS_OMLX_MODEL", ""))
    omlx_api_key: str = field(default_factory=lambda: os.getenv("OVS_OMLX_API_KEY", ""))
    omlx_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("OVS_OMLX_TIMEOUT_SECONDS", "180"))
    )
    enable_study_pack: bool = field(
        default_factory=lambda: os.getenv("OVS_ENABLE_STUDY_PACK", "false").lower() == "true"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "default_output_languages",
            _csv_env("OVS_DEFAULT_OUTPUT_LANGUAGES", ["en", "zh-CN"]),
        )
        object.__setattr__(
            self,
            "preferred_caption_languages",
            _csv_env("OVS_PREFERRED_CAPTION_LANGUAGES", ["en", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW"]),
        )
        if self.summarizer_provider == "omlx":
            if not self.omlx_base_url:
                raise ValueError("OVS_OMLX_BASE_URL is required when OVS_SUMMARIZER_PROVIDER=omlx")
            if not self.omlx_model:
                raise ValueError("OVS_OMLX_MODEL is required when OVS_SUMMARIZER_PROVIDER=omlx")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
