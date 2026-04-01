from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.services.summarizer import (
    OmlxSummaryGenerator,
    RuleBasedSummaryGenerator,
    build_summarizer_prompt,
    compute_max_tokens,
    create_summary_generator,
    extract_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SUMMARY = {
    "chapters": [
        {
            "start_s": 0.0,
            "end_s": 60.0,
            "title": "Introduction",
            "summary_en": "This chapter introduces the topic.",
            "summary_zh": "本章介绍了主题。",
            "key_points": ["Introduction to topic"],
        }
    ],
    "overall_summary": {
        "summary_en": "A video about testing.",
        "summary_zh": "一个关于测试的视频。",
        "highlights": ["Testing is important"],
    },
}

SAMPLE_METADATA = {"title": "Test Video", "duration": 120, "channel": "Test Channel"}

SAMPLE_SEGMENTS = [
    {"text": "Hello world. This is a test.", "start_s": 0.0, "end_s": 30.0, "source": "captions"},
    {"text": "Second segment here.", "start_s": 30.0, "end_s": 60.0, "source": "captions"},
]

SAMPLE_CHAPTERS = [
    {"start_s": 0.0, "end_s": 60.0, "title_hint": "Chapter 1", "text": "Hello world. This is a test. Second segment here."},
]


def _omlx_settings(**overrides) -> Settings:
    env = {
        "OVS_SUMMARIZER_PROVIDER": "omlx",
        "OVS_OMLX_BASE_URL": "http://localhost:8080/v1",
        "OVS_OMLX_MODEL": "test-model",
    }
    env.update(overrides)
    saved = {}
    for k, v in env.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return Settings()
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _make_openai_response(content: str, status_code: int = 200) -> httpx.Response:
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "http://localhost:8080/v1/chat/completions"),
    )


# ---------------------------------------------------------------------------
# Shared helper tests
# ---------------------------------------------------------------------------

def test_build_summarizer_prompt_returns_system_and_user():
    settings = Settings()
    system_msg, user_msg = build_summarizer_prompt(settings, SAMPLE_METADATA, SAMPLE_CHAPTERS, ["en", "zh-CN"])
    assert "multilingual video summarization" in system_msg
    assert "Target languages" in user_msg
    assert "Test Video" in user_msg


def test_extract_json_strips_think_blocks():
    raw = '<think>reasoning</think>{"key": "value"}'
    assert json.loads(extract_json(raw)) == {"key": "value"}


def test_extract_json_strips_markdown_fences():
    raw = '```json\n{"key": "value"}\n```'
    assert json.loads(extract_json(raw)) == {"key": "value"}


def test_extract_json_handles_trailing_chars():
    raw = '{"key": "value"}extra stuff'
    assert json.loads(extract_json(raw)) == {"key": "value"}


def test_compute_max_tokens_uses_formula():
    settings = Settings()
    assert compute_max_tokens(settings, 3) == max(settings.summarizer_max_tokens, 1024 * 3 + 1024)


# ---------------------------------------------------------------------------
# OmlxSummaryGenerator tests
# ---------------------------------------------------------------------------

class TestOmlxSummaryGenerator:
    def test_success(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        response = _make_openai_response(json.dumps(VALID_SUMMARY))
        with patch("httpx.post", return_value=response):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Introduction"
        assert "summary_en" in result["overall_summary"]

    def test_success_with_artifacts(self, tmp_path: Path):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        response = _make_openai_response(json.dumps(VALID_SUMMARY))
        artifact_dir = tmp_path / "artifacts"
        with patch("httpx.post", return_value=response):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"], artifact_dir=artifact_dir)
        assert (artifact_dir / "summarizer_prompt.txt").exists()
        assert (artifact_dir / "summarizer_request.json").exists()
        assert (artifact_dir / "summarizer_raw_output.txt").exists()
        # Verify request.json does not contain auth headers.
        request_data = json.loads((artifact_dir / "summarizer_request.json").read_text())
        assert "Authorization" not in json.dumps(request_data)
        assert request_data["model"] == "test-model"

    def test_fallback_on_timeout(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        with patch("httpx.post", side_effect=httpx.ReadTimeout("timed out")):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        # Should return rule-based output, not raise.
        assert "chapters" in result
        assert result["chapters"][0]["title"] == "Chapter 1"

    def test_fallback_on_connection_error(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert "chapters" in result

    def test_fallback_on_401(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        response = httpx.Response(
            status_code=401,
            text="Unauthorized",
            request=httpx.Request("POST", "http://localhost:8080/v1/chat/completions"),
        )
        with patch("httpx.post", return_value=response):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert "chapters" in result

    def test_fallback_on_500(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("POST", "http://localhost:8080/v1/chat/completions"),
        )
        with patch("httpx.post", return_value=response):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert "chapters" in result

    def test_fallback_on_malformed_response(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        # Response with unexpected JSON structure (no choices).
        response = httpx.Response(
            status_code=200,
            json={"result": "unexpected"},
            request=httpx.Request("POST", "http://localhost:8080/v1/chat/completions"),
        )
        with patch("httpx.post", return_value=response):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert "chapters" in result

    def test_fallback_on_bad_model_json(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        response = _make_openai_response("This is not JSON at all")
        with patch("httpx.post", return_value=response):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert "chapters" in result
        # Rule-based fallback uses title_hint.
        assert result["chapters"][0]["title"] == "Chapter 1"


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

class TestFactory:
    def test_factory_fallback(self, monkeypatch):
        monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "fallback")
        monkeypatch.delenv("OVS_OMLX_BASE_URL", raising=False)
        settings = Settings()
        gen = create_summary_generator(settings)
        assert isinstance(gen, RuleBasedSummaryGenerator)

    def test_factory_omlx(self, monkeypatch):
        monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "omlx")
        monkeypatch.setenv("OVS_OMLX_BASE_URL", "http://localhost:8080/v1")
        monkeypatch.setenv("OVS_OMLX_MODEL", "test-model")
        settings = Settings()
        gen = create_summary_generator(settings)
        assert isinstance(gen, OmlxSummaryGenerator)

    def test_factory_mlx(self, monkeypatch):
        monkeypatch.setenv("OVS_SUMMARIZER_PROVIDER", "mlx")
        monkeypatch.delenv("OVS_OMLX_BASE_URL", raising=False)
        settings = Settings()
        gen = create_summary_generator(settings)
        from backend.app.services.summarizer import MlxQwenSummaryGenerator
        assert isinstance(gen, MlxQwenSummaryGenerator)
