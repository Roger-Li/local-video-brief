from __future__ import annotations

import os
from pathlib import Path

from backend.app.core.config import Settings, load_env_file
from backend.app.services.asr import resolve_asr_model_name
from backend.app.services.storage import StorageService
from backend.app.services.video_source import YtDlpVideoSourceClient


def test_load_env_file_sets_missing_values_only(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OVS_ENABLE_MLX_ASR=true\nOVS_SUMMARIZER_MODEL=test-model\n",
        encoding="utf-8",
    )

    os.environ.pop("OVS_ENABLE_MLX_ASR", None)
    os.environ["OVS_SUMMARIZER_MODEL"] = "keep-existing"

    load_env_file(env_file)

    assert os.environ["OVS_ENABLE_MLX_ASR"] == "true"
    assert os.environ["OVS_SUMMARIZER_MODEL"] == "keep-existing"


def test_settings_reads_environment_at_instantiation_time() -> None:
    previous = os.environ.get("OVS_ENABLE_MLX_ASR")
    try:
        os.environ["OVS_ENABLE_MLX_ASR"] = "true"
        settings = Settings()
        assert settings.enable_mlx_asr is True
    finally:
        if previous is None:
            os.environ.pop("OVS_ENABLE_MLX_ASR", None)
        else:
            os.environ["OVS_ENABLE_MLX_ASR"] = previous


def test_asr_model_aliases_resolve_to_mlx_repos() -> None:
    assert resolve_asr_model_name("large-v3-turbo") == "mlx-community/whisper-large-v3-turbo"
    assert resolve_asr_model_name("mlx-community/whisper-large-v3") == "mlx-community/whisper-large-v3"


def test_caption_language_priority_prefers_english_then_chinese(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(StorageService(tmp_path), ["zh-Hans", "fr"])
    ordered = client._ordered_caption_languages(["en", "zh-CN", "es"])  # type: ignore[attr-defined]
    assert ordered == [
        ("english", ["en"]),
        ("chinese", ["zh-CN", "zh-Hans"]),
        ("other", ["es", "fr"]),
    ]


def test_find_subtitles_for_family_returns_existing_english_first(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(StorageService(tmp_path), [])
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    (job_dir / "source.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (job_dir / "source.zh-Hans.vtt").write_text("WEBVTT\n", encoding="utf-8")

    english = client._find_subtitles_for_family(job_dir, "english")  # type: ignore[attr-defined]
    chinese = client._find_subtitles_for_family(job_dir, "chinese")  # type: ignore[attr-defined]

    assert [artifact.language for artifact in english] == ["en"]
    assert [artifact.language for artifact in chinese] == ["zh-Hans"]
