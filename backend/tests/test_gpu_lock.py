from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.services.asr import MlxWhisperAsrService
from backend.app.services.summarizer import MlxQwenSummaryGenerator


class _IntervalRecorder:
    """Records (start, end) wall-clock intervals of fake GPU calls."""

    def __init__(self) -> None:
        self.intervals: list[tuple[float, float]] = []
        self._lock = threading.Lock()

    def record(self, duration: float = 0.05) -> None:
        start = time.perf_counter()
        time.sleep(duration)
        end = time.perf_counter()
        with self._lock:
            self.intervals.append((start, end))


def _any_overlap(intervals: list[tuple[float, float]]) -> bool:
    ordered = sorted(intervals)
    return any(
        previous[1] > current[0]
        for previous, current in zip(ordered, ordered[1:])
    )


def _fake_mlx_lm(recorder: _IntervalRecorder | None = None, load_calls: list[str] | None = None):
    def load(model_name: str):
        if load_calls is not None:
            time.sleep(0.05)
            load_calls.append(model_name)
        return object(), object()

    def generate(model, tokenizer, prompt=None, max_tokens=None):
        if recorder is not None:
            recorder.record()
        return "fake output"

    return types.SimpleNamespace(load=load, generate=generate)


def _run_threads(targets) -> None:
    threads = [threading.Thread(target=target) for target in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)


def test_concurrent_mlx_generate_calls_do_not_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _IntervalRecorder()
    monkeypatch.setitem(sys.modules, "mlx_lm", _fake_mlx_lm(recorder=recorder))
    generator = MlxQwenSummaryGenerator(Settings())

    def call() -> None:
        generator._call_llm("system", "user", max_tokens=16)

    _run_threads([call, call])

    assert len(recorder.intervals) == 2
    assert not _any_overlap(recorder.intervals)


def test_asr_and_mlx_summarizer_share_gpu_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _IntervalRecorder()

    def fake_transcribe(audio_path, path_or_hf_repo=None):
        recorder.record()
        return {"language": "en", "segments": []}

    monkeypatch.setitem(sys.modules, "mlx_whisper", types.SimpleNamespace(transcribe=fake_transcribe))
    monkeypatch.setitem(sys.modules, "mlx_lm", _fake_mlx_lm(recorder=recorder))
    monkeypatch.setenv("OVS_ENABLE_MLX_ASR", "true")
    settings = Settings()

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake audio")
    asr = MlxWhisperAsrService(settings)
    generator = MlxQwenSummaryGenerator(settings)

    _run_threads([
        lambda: asr.transcribe(audio_path),
        lambda: generator._call_llm("system", "user", max_tokens=16),
    ])

    assert len(recorder.intervals) == 2
    assert not _any_overlap(recorder.intervals)


def test_ensure_model_loaded_loads_once_under_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    load_calls: list[str] = []
    monkeypatch.setitem(sys.modules, "mlx_lm", _fake_mlx_lm(load_calls=load_calls))
    generator = MlxQwenSummaryGenerator(Settings())

    _run_threads([generator._ensure_model_loaded, generator._ensure_model_loaded])

    assert load_calls == [Settings().summarizer_model]
