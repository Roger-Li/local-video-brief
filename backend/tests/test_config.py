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


def test_provider_explicit_omlx(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
    settings = Settings()
    assert settings.summarizer_provider == "omlx"
    assert settings.omlx_base_url == "http://localhost:8080/v1"
    assert settings.omlx_model == "test-model"


def test_provider_explicit_mlx(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "mlx")
    monkeypatch.delenv("OVS_OMLX_BASE_URL", raising=False)
    settings = Settings()
    assert settings.summarizer_provider == "mlx"


def test_provider_explicit_fallback(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "fallback")
    settings = Settings()
    assert settings.summarizer_provider == "fallback"


def test_provider_legacy_mlx_flag(monkeypatch) -> None:
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    monkeypatch.setenv("OVS_ENABLE_MLX_SUMMARIZER", "true")
    settings = Settings()
    assert settings.summarizer_provider == "mlx"


def test_provider_defaults_to_fallback(monkeypatch) -> None:
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    monkeypatch.delenv("OVS_ENABLE_MLX_SUMMARIZER", raising=False)
    settings = Settings()
    assert settings.summarizer_provider == "fallback"


def test_provider_invalid_raises(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "invalid")
    import pytest
    with pytest.raises(ValueError, match="must be fallback, mlx, or omlx"):
        Settings()


def test_omlx_missing_base_url_raises(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.delenv("OVS_OMLX_BASE_URL", raising=False)
    monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
    import pytest
    with pytest.raises(ValueError, match="OVS_OMLX_BASE_URL is required"):
        Settings()


def test_omlx_missing_model_raises(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.delenv("OVS_OMLX_MODEL", raising=False)
    import pytest
    with pytest.raises(ValueError, match="OVS_OMLX_MODEL is required"):
        Settings()


def test_omlx_base_url_trailing_slash_stripped(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1/")
    monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
    settings = Settings()
    assert settings.omlx_base_url == "http://localhost:8080/v1"


def test_omlx_timeout_parsing(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
    monkeypatch.setenv("OVS_OMLX_TIMEOUT_SECONDS", "60")
    settings = Settings()
    assert settings.omlx_timeout_seconds == 60


def test_omlx_timeout_default(monkeypatch) -> None:
    monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
    monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
    monkeypatch.delenv("OVS_OMLX_TIMEOUT_SECONDS", raising=False)
    settings = Settings()
    assert settings.omlx_timeout_seconds == 180


def test_cookies_from_browser_setting(monkeypatch) -> None:
    monkeypatch.setenv("OVS_COOKIES_FROM_BROWSER", "brave")
    monkeypatch.delenv("OVS_COOKIES_FILE", raising=False)
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    settings = Settings()
    assert settings.cookies_from_browser == "brave"
    assert settings.cookies_file == ""


def test_cookies_file_setting(monkeypatch) -> None:
    monkeypatch.delenv("OVS_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.setenv("OVS_COOKIES_FILE", "/tmp/cookies.txt")
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    settings = Settings()
    assert settings.cookies_from_browser == ""
    assert settings.cookies_file == "/tmp/cookies.txt"


def test_cookies_defaults_empty(monkeypatch) -> None:
    monkeypatch.delenv("OVS_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.delenv("OVS_COOKIES_FILE", raising=False)
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    settings = Settings()
    assert settings.cookies_from_browser == ""
    assert settings.cookies_file == ""


def test_client_cookie_args_from_browser(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(StorageService(tmp_path), [], cookies_from_browser="brave")
    assert client._cookie_args == ["--cookies-from-browser", "brave"]


def test_client_cookie_args_from_file(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(StorageService(tmp_path), [], cookies_file="/tmp/cookies.txt")
    assert client._cookie_args == ["--cookies", "/tmp/cookies.txt"]


def test_client_cookie_args_browser_takes_priority(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(
        StorageService(tmp_path), [],
        cookies_from_browser="brave", cookies_file="/tmp/cookies.txt",
    )
    assert client._cookie_args == ["--cookies-from-browser", "brave"]


def test_client_cookie_args_default_empty(tmp_path: Path) -> None:
    client = YtDlpVideoSourceClient(StorageService(tmp_path), [])
    assert client._cookie_args == []


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
