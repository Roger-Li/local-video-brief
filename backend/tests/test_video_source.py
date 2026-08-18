from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from backend.app.services.storage import StorageService
from backend.app.services.video_source import (
    YOUTUBE_403_FALLBACK_EXTRACTOR_ARGS,
    VideoSourceError,
    YtDlpVideoSourceClient,
)

BILIBILI_URL = "https://www.bilibili.com/video/BV1E8UQBeEzg"
YOUTUBE_URL = "https://www.youtube.com/watch?v=Lk_OQufs1HQ"


def _client(tmp_path: Path, **kwargs) -> YtDlpVideoSourceClient:
    return YtDlpVideoSourceClient(
        storage=StorageService(tmp_path / "artifacts"),
        preferred_caption_languages=["en"],
        **kwargs,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=Lk_OQufs1HQ",
        "https://youtube.com/watch?v=Lk_OQufs1HQ",
        "https://m.youtube.com/watch?v=Lk_OQufs1HQ",
        "https://music.youtube.com/watch?v=Lk_OQufs1HQ",
        "https://youtu.be/Lk_OQufs1HQ",
        "https://www.youtube-nocookie.com/embed/Lk_OQufs1HQ",
    ],
)
def test_cookies_are_not_sent_to_youtube_hosts(tmp_path: Path, url: str) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")

    assert client._cookie_args_for(url) == []


def test_cookies_are_sent_to_non_exempt_hosts(tmp_path: Path) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")

    assert client._cookie_args_for(BILIBILI_URL) == ["--cookies", "/tmp/cookies.txt"]


def test_browser_cookies_are_also_withheld_from_youtube(tmp_path: Path) -> None:
    client = _client(tmp_path, cookies_from_browser="brave")

    assert client._cookie_args_for(YOUTUBE_URL) == []
    assert client._cookie_args_for(BILIBILI_URL) == ["--cookies-from-browser", "brave"]


def test_no_cookie_args_when_nothing_configured(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client._cookie_args_for(BILIBILI_URL) == []
    assert client._cookie_args_for(YOUTUBE_URL) == []


def test_lookalike_host_still_receives_cookies(tmp_path: Path) -> None:
    """notyoutube.com must not match the youtube.com suffix rule."""
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")

    assert client._cookie_args_for("https://notyoutube.com/watch?v=x") == [
        "--cookies",
        "/tmp/cookies.txt",
    ]


def _capture_commands(client: YtDlpVideoSourceClient, monkeypatch, stdout: str = "{}") -> List[List[str]]:
    calls: List[List[str]] = []

    class _Result:
        def __init__(self) -> None:
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args: List[str]):
        calls.append(args)
        return _Result()

    monkeypatch.setattr(client, "_run_command", fake_run)
    return calls


def test_inspect_omits_cookies_for_youtube(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    calls = _capture_commands(client, monkeypatch, stdout=json.dumps({"title": "t", "duration": 1}))

    client.inspect(YOUTUBE_URL)

    assert "--cookies" not in calls[0]


def test_inspect_keeps_cookies_for_bilibili(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    calls = _capture_commands(client, monkeypatch, stdout=json.dumps({"title": "t", "duration": 1}))

    client.inspect(BILIBILI_URL)

    assert calls[0][1:3] == ["--cookies", "/tmp/cookies.txt"]


def test_download_audio_omits_cookies_for_youtube(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    calls = _capture_commands(client, monkeypatch)
    job_dir = client.storage.job_dir("job-1")
    (job_dir / "audio.mp3").write_bytes(b"x")

    client.download_audio("job-1", YOUTUBE_URL)

    assert "--cookies" not in calls[0]


def test_download_audio_retries_youtube_403_with_alternate_clients(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    job_dir = client.storage.job_dir("job-403")
    calls: List[List[str]] = []

    def fake_run(args: List[str]):
        calls.append(args)
        if len(calls) == 1:
            (job_dir / "audio.webm.part").write_bytes(b"partial")
            raise VideoSourceError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        (job_dir / "audio.mp3").write_bytes(b"audio")

    monkeypatch.setattr(client, "_run_command", fake_run)

    audio = client.download_audio("job-403", YOUTUBE_URL)

    assert audio.path == job_dir / "audio.mp3"
    assert len(calls) == 2
    assert "--extractor-args" not in calls[0]
    fallback_index = calls[1].index("--extractor-args")
    assert calls[1][fallback_index + 1] == YOUTUBE_403_FALLBACK_EXTRACTOR_ARGS
    assert "--cookies" not in calls[1]
    assert not (job_dir / "audio.webm.part").exists()


@pytest.mark.parametrize(
    ("url", "error"),
    [
        (YOUTUBE_URL, "ERROR: network connection timed out"),
        (BILIBILI_URL, "ERROR: unable to download video data: HTTP Error 403: Forbidden"),
    ],
)
def test_download_audio_does_not_retry_unrelated_failures(
    tmp_path: Path,
    monkeypatch,
    url: str,
    error: str,
) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    calls: List[List[str]] = []

    def fake_run(args: List[str]):
        calls.append(args)
        raise VideoSourceError(error)

    monkeypatch.setattr(client, "_run_command", fake_run)

    with pytest.raises(VideoSourceError, match="403|timed out"):
        client.download_audio("job-no-retry", url)

    assert len(calls) == 1


def test_caption_download_omits_cookies_for_youtube(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, cookies_file="/tmp/cookies.txt")
    calls = _capture_commands(client, monkeypatch)

    client.fetch_captions("job-2", YOUTUBE_URL, ["en"])

    assert calls, "expected at least one caption download attempt"
    assert all("--cookies" not in call for call in calls)
