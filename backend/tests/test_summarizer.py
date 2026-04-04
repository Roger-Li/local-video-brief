from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.services.summarizer import (
    MlxQwenSummaryGenerator,
    OmlxSummaryGenerator,
    RuleBasedSummaryGenerator,
    _choose_strategy,
    _validate_single_shot_payload,
    build_summarizer_prompt,
    compute_max_tokens,
    create_summary_generator,
    extract_json,
    parse_model_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_CHAPTER_SUMMARY = {
    "start_s": 0.0,
    "end_s": 60.0,
    "title": "Introduction",
    "summary_en": "This chapter introduces the topic.",
    "summary_zh": "本章介绍了主题。",
    "key_points": ["Introduction to topic"],
}

VALID_OVERALL_SUMMARY = {
    "summary_en": "A video about testing.",
    "summary_zh": "一个关于测试的视频。",
    "highlights": ["Testing is important"],
}

VALID_SUMMARY = {
    "chapters": [VALID_CHAPTER_SUMMARY],
    "overall_summary": VALID_OVERALL_SUMMARY,
}

SAMPLE_METADATA = {"title": "Test Video", "duration": 120, "channel": "Test Channel"}

SAMPLE_SEGMENTS = [
    {"text": "Hello world. This is a test.", "start_s": 0.0, "end_s": 30.0, "source": "captions"},
    {"text": "Second segment here.", "start_s": 30.0, "end_s": 60.0, "source": "captions"},
]

SAMPLE_CHAPTERS = [
    {
        "start_s": 0.0,
        "end_s": 60.0,
        "title_hint": "Chapter 1",
        "text": "Hello world. This is a test. Second segment here.",
        "segments": SAMPLE_SEGMENTS,
    },
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


def test_parse_model_json_tolerates_literal_newlines_in_strings():
    raw = '{"summary_en": "Line 1\nLine 2", "highlights": ["A"]}'
    assert parse_model_json(raw) == {
        "summary_en": "Line 1\nLine 2",
        "highlights": ["A"],
    }


def test_parse_model_json_tolerates_unescaped_inner_quotes():
    raw = '{"key_points": ["提出“反向 OPI"概念"]}'
    assert parse_model_json(raw) == {"key_points": ['提出“反向 OPI"概念']}


def test_parse_model_json_tolerates_inner_quotes_before_comma():
    raw = '{"key_points": ["she calls it "OPI", then..."], "summary_en": "ok"}'
    assert parse_model_json(raw) == {
        "key_points": ['she calls it "OPI", then...'],
        "summary_en": "ok",
    }


def test_parse_model_json_tolerates_inner_quotes_before_colon():
    raw = '{"key_points": ["term "foo": ..."], "summary_en": "ok"}'
    assert parse_model_json(raw) == {
        "key_points": ['term "foo": ...'],
        "summary_en": "ok",
    }


def test_parse_model_json_keeps_single_array_item_for_multiple_quoted_phrases():
    raw = '{"key_points": ["call it "A", "B", and "C""], "summary_en": "ok"}'
    assert parse_model_json(raw) == {
        "key_points": ['call it "A", "B", and "C"'],
        "summary_en": "ok",
    }


def test_parse_model_json_rejects_repaired_payload_missing_required_keys():
    raw = '{"summary_en": "ok" "summary_zh": "z", "highlights": ["h"]}'
    with pytest.raises(ValueError, match="missing required keys: summary_zh"):
        parse_model_json(raw, required_keys={"summary_en", "summary_zh", "highlights"})


def test_compute_max_tokens_uses_formula():
    settings = Settings()
    assert compute_max_tokens(settings, 3) == max(settings.summarizer_max_tokens, 1024 * 3 + 1024)


# ---------------------------------------------------------------------------
# OmlxSummaryGenerator tests
# ---------------------------------------------------------------------------

class TestOmlxSummaryGenerator:
    def test_success_single_shot(self):
        """Small chapters route to single-shot, combined JSON in 1 call."""
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        with patch.object(gen, "_call_omlx", return_value=json.dumps(VALID_SUMMARY)):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Introduction"
        assert "summary_en" in result["overall_summary"]

    def test_success_with_artifacts(self, tmp_path: Path):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        artifact_dir = tmp_path / "artifacts"
        # Small chapters -> single-shot. Use real _call_omlx with mocked httpx.post.
        single_shot_response = _make_openai_response(json.dumps(VALID_SUMMARY))
        with patch("httpx.post", return_value=single_shot_response):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"], artifact_dir=artifact_dir)
        # Single-shot artifacts in root dir.
        prompt_files = list(artifact_dir.glob("summarizer_*_prompt.txt"))
        assert len(prompt_files) >= 1, "at least one prompt artifact should exist"
        raw_files = list(artifact_dir.glob("summarizer_*_raw_output.txt"))
        assert len(raw_files) >= 1, "at least one raw output artifact should exist"
        strategy_file = artifact_dir / "summarizer_strategy.txt"
        assert strategy_file.exists()
        assert strategy_file.read_text() == "single_shot"

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
        assert isinstance(gen, MlxQwenSummaryGenerator)


# ---------------------------------------------------------------------------
# Hierarchical summarization tests (oMLX provider, mocked _call_omlx)
# ---------------------------------------------------------------------------

# Multi-chunk chapters: 2 chapters, first has 2 chunks, second fits in 1.
MULTI_CHUNK_SEGMENTS_A = [
    {"text": "A" * 10000, "start_s": 0.0, "end_s": 120.0, "source": "captions"},
    {"text": "B" * 10000, "start_s": 120.0, "end_s": 240.0, "source": "captions"},
]
MULTI_CHUNK_SEGMENTS_B = [
    {"text": "C" * 100, "start_s": 240.0, "end_s": 300.0, "source": "captions"},
]
MULTI_CHAPTER_LIST = [
    {
        "start_s": 0.0, "end_s": 240.0, "title_hint": "Long Chapter",
        "text": "A" * 10000 + " " + "B" * 10000,
        "segments": MULTI_CHUNK_SEGMENTS_A,
    },
    {
        "start_s": 240.0, "end_s": 300.0, "title_hint": "Short Chapter",
        "text": "C" * 100,
        "segments": MULTI_CHUNK_SEGMENTS_B,
    },
]

CHAPTER_SUMMARY_A = {
    "start_s": 0.0, "end_s": 240.0, "title": "Long Chapter Summary",
    "summary_en": "Long chapter content.", "summary_zh": "长章节内容。",
    "key_points": ["point A"],
}
CHAPTER_SUMMARY_B = {
    "start_s": 240.0, "end_s": 300.0, "title": "Short Chapter Summary",
    "summary_en": "Short chapter content.", "summary_zh": "短章节内容。",
    "key_points": ["point B"],
}

TWO_SIMPLE_SEGMENTS = [
    {"text": "First chapter sentence one. First chapter sentence two.", "start_s": 0.0, "end_s": 60.0, "source": "captions"},
    {"text": "Second chapter sentence one. Second chapter sentence two.", "start_s": 60.0, "end_s": 120.0, "source": "captions"},
]

TWO_SIMPLE_CHAPTERS = [
    {
        "start_s": 0.0,
        "end_s": 60.0,
        "title_hint": "First Chapter",
        "text": "First chapter sentence one. First chapter sentence two.",
        "segments": [TWO_SIMPLE_SEGMENTS[0]],
    },
    {
        "start_s": 60.0,
        "end_s": 120.0,
        "title_hint": "Second Chapter",
        "text": "Second chapter sentence one. Second chapter sentence two.",
        "segments": [TWO_SIMPLE_SEGMENTS[1]],
    },
]


class TestOmlxHierarchical:
    def test_summarize_chunk_returns_note(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        with patch.object(gen, "_call_omlx", return_value="This is a chunk note."):
            note = gen._summarize_chunk("some text", "Chapter 1", 0, 2)
        assert note == "This is a chunk note."

    def test_synthesize_chapter_parses_json(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        raw_json = json.dumps(VALID_CHAPTER_SUMMARY)
        with patch.object(gen, "_call_omlx", return_value=raw_json):
            result = gen._synthesize_chapter(SAMPLE_CHAPTERS[0], ["note 1", "note 2"])
        assert result["title"] == "Introduction"
        assert "summary_en" in result

    def test_synthesize_chapter_tolerates_literal_newlines(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        raw_json = (
            '{"start_s": 0.0, "end_s": 60.0, "title": "Introduction", '
            '"summary_en": "Line 1\nLine 2", "summary_zh": "第一行\n第二行", '
            '"key_points": ["Introduction to topic"]}'
        )
        with patch.object(gen, "_call_omlx", return_value=raw_json):
            result = gen._synthesize_chapter(SAMPLE_CHAPTERS[0], ["note 1", "note 2"])
        assert result["summary_en"] == "Line 1\nLine 2"
        assert result["summary_zh"] == "第一行\n第二行"

    def test_synthesize_chapter_tolerates_unescaped_inner_quotes(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        raw_json = (
            '{"start_s": 0.0, "end_s": 60.0, "title": "Introduction", '
            '"summary_en": "Topic overview.", "summary_zh": "主题概述。", '
            '"key_points": ["提出“反向 OPI"概念"]}'
        )
        with patch.object(gen, "_call_omlx", return_value=raw_json):
            result = gen._synthesize_chapter(SAMPLE_CHAPTERS[0], ["note 1", "note 2"])
        assert result["key_points"] == ['提出“反向 OPI"概念']

    def test_synthesize_overall_parses_json(self):
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        raw_json = json.dumps(VALID_OVERALL_SUMMARY)
        with patch.object(gen, "_call_omlx", return_value=raw_json):
            result = gen._synthesize_overall(SAMPLE_METADATA, [VALID_CHAPTER_SUMMARY])
        assert "summary_en" in result
        assert "highlights" in result

    def test_per_chapter_skips_chunk_note_for_small_chapters(self):
        """Per-chapter route: single-chunk chapter -> no _summarize_chunk call."""
        # Force per-chapter: total text > 100, each chapter < 100
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="100")
        gen = OmlxSummaryGenerator(settings)
        responses = [
            json.dumps(VALID_CHAPTER_SUMMARY),  # ch0 synthesis
            json.dumps(VALID_CHAPTER_SUMMARY),  # ch1 synthesis
            json.dumps(VALID_OVERALL_SUMMARY),  # overall
        ]
        with patch.object(gen, "_call_omlx", side_effect=responses) as mock_call:
            result = gen.summarize(SAMPLE_METADATA, TWO_SIMPLE_SEGMENTS, TWO_SIMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Introduction"
        # 2 chapter synthesis + 1 overall = 3 calls (no chunk notes).
        assert mock_call.call_count == 3

    def test_multi_chunk_chapter_calls_chunk_notes(self):
        """Multi-chunk chapter should call _summarize_chunk for each chunk."""
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="5000")
        gen = OmlxSummaryGenerator(settings)
        # Chapter A has 2 segments of 10k chars each, max_input=5000 → 2 chunks → 2 chunk notes
        # Chapter B has 1 segment of 100 chars → fits in 1 chunk → no chunk notes
        responses = [
            "Chunk note 0 for chapter A.",       # chunk 0 of ch A
            "Chunk note 1 for chapter A.",       # chunk 1 of ch A
            json.dumps(CHAPTER_SUMMARY_A),       # synthesize ch A
            json.dumps(CHAPTER_SUMMARY_B),       # synthesize ch B (single chunk, no chunk note step)
            json.dumps(VALID_OVERALL_SUMMARY),   # overall
        ]
        with patch.object(gen, "_call_omlx", side_effect=responses) as mock_call:
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, MULTI_CHAPTER_LIST, ["en", "zh-CN"])
        assert len(result["chapters"]) == 2
        assert result["chapters"][0]["title"] == "Long Chapter Summary"
        assert result["chapters"][1]["title"] == "Short Chapter Summary"
        assert "summary_en" in result["overall_summary"]
        # 2 chunk notes + ch A synthesis + ch B synthesis + overall = 5 calls
        assert mock_call.call_count == 5

    def test_multi_chunk_saves_chunk_notes_artifact(self, tmp_path: Path):
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="5000")
        gen = OmlxSummaryGenerator(settings)
        responses = [
            "Note 0.", "Note 1.",
            json.dumps(CHAPTER_SUMMARY_A),
            json.dumps(CHAPTER_SUMMARY_B),
            json.dumps(VALID_OVERALL_SUMMARY),
        ]
        artifact_dir = tmp_path / "artifacts"
        with patch.object(gen, "_call_omlx", side_effect=responses):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, MULTI_CHAPTER_LIST, ["en", "zh-CN"],
                          artifact_dir=artifact_dir)
        chunk_notes_path = artifact_dir / "chunk_notes.json"
        assert chunk_notes_path.exists()
        notes = json.loads(chunk_notes_path.read_text())
        assert "0" in notes  # chapter 0 had multi-chunk
        assert len(notes["0"]) == 2

    def test_fallback_on_json_decode_error_single_shot(self):
        """Single-shot: invalid JSON -> fall back to rule-based."""
        settings = _omlx_settings()
        gen = OmlxSummaryGenerator(settings)
        with patch.object(gen, "_call_omlx", return_value="not json at all"):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Chapter 1"

    def test_partial_chapter_fallback_preserves_successful_llm_output(self):
        """Per-chapter: one chapter fails, others and overall succeed."""
        # Force per-chapter routing
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="100")
        gen = OmlxSummaryGenerator(settings)
        responses = [
            json.dumps(VALID_CHAPTER_SUMMARY),  # ch0 success
            "not json at all",                   # ch1 fails -> rule-based fallback
            json.dumps(VALID_OVERALL_SUMMARY),   # overall success
        ]
        with patch.object(gen, "_call_omlx", side_effect=responses):
            result = gen.summarize(SAMPLE_METADATA, TWO_SIMPLE_SEGMENTS, TWO_SIMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Introduction"
        assert result["chapters"][1]["title"] == "Second Chapter"
        assert result["overall_summary"]["summary_en"] == VALID_OVERALL_SUMMARY["summary_en"]

    def test_invalid_overall_payload_falls_back_to_rule_based_overall(self):
        """Per-chapter: chapter succeeds but overall synthesis fails."""
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="100")
        gen = OmlxSummaryGenerator(settings)
        responses = [
            json.dumps(VALID_CHAPTER_SUMMARY),  # ch0 success
            json.dumps(VALID_CHAPTER_SUMMARY),  # ch1 success
            '{"summary_en": "ok" "summary_zh": "z", "highlights": ["h"]}',  # overall fails
        ]
        with patch.object(gen, "_call_omlx", side_effect=responses):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, TWO_SIMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Introduction"
        assert result["overall_summary"]["summary_zh"]
        assert isinstance(result["overall_summary"]["highlights"], list)

    def test_progress_callback_per_chapter(self):
        """Per-chapter route reports summarizing_chunks + synthesizing_chapters + synthesizing_overall."""
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="100")
        gen = OmlxSummaryGenerator(settings)
        responses = [
            json.dumps(VALID_CHAPTER_SUMMARY),
            json.dumps(VALID_CHAPTER_SUMMARY),
            json.dumps(VALID_OVERALL_SUMMARY),
        ]
        stages: list[str] = []
        with patch.object(gen, "_call_omlx", side_effect=responses):
            gen.summarize(SAMPLE_METADATA, TWO_SIMPLE_SEGMENTS, TWO_SIMPLE_CHAPTERS, ["en", "zh-CN"],
                          progress_callback=stages.append)
        assert "summarizing_chunks" in stages
        assert "synthesizing_chapters" in stages
        assert "synthesizing_overall" in stages


# ---------------------------------------------------------------------------
# extract_json edge cases
# ---------------------------------------------------------------------------

def test_extract_json_unclosed_think_block():
    raw = '<think>still thinking... {"key": "value"}'
    result = extract_json(raw)
    # The unclosed think block should be stripped, but there's no JSON left.
    # Verify it doesn't crash.
    assert isinstance(result, str)


def test_extract_json_empty_string():
    assert extract_json("") == ""


def test_extract_json_nested_braces():
    raw = '{"outer": {"inner": "value"}}'
    assert json.loads(extract_json(raw)) == {"outer": {"inner": "value"}}


def test_rule_based_summarize_overall_uses_transcript_text():
    settings = Settings()
    gen = RuleBasedSummaryGenerator(settings)
    segments = [{"text": "S1. S2. S3.", "start_s": 0.0, "end_s": 9.0, "source": "captions"}]
    chapters = [
        {
            "start_s": 0.0,
            "end_s": 9.0,
            "title_hint": "C1",
            "text": "S1. S2. S3.",
            "segments": segments,
        }
    ]
    result = gen.summarize({"title": "T"}, segments, chapters, ["en"])
    assert result["overall_summary"]["summary_en"] == "S1. S2. S3."
    assert result["overall_summary"]["highlights"] == ["S1.", "S2.", "S3."]


# ---------------------------------------------------------------------------
# Routing strategy tests
# ---------------------------------------------------------------------------

class TestChooseStrategy:
    def test_small_total_returns_single_shot(self):
        chapters = [
            {"text": "A" * 100, "segments": []},
            {"text": "B" * 100, "segments": []},
        ]
        assert _choose_strategy(chapters, 18000) == "single_shot"

    def test_total_exceeds_but_chapters_fit_returns_per_chapter(self):
        chapters = [
            {"text": "A" * 10000, "segments": []},
            {"text": "B" * 10000, "segments": []},
        ]
        assert _choose_strategy(chapters, 18000) == "per_chapter"

    def test_chapter_exceeds_returns_hierarchical(self):
        chapters = [
            {"text": "A" * 20000, "segments": []},
            {"text": "B" * 100, "segments": []},
        ]
        assert _choose_strategy(chapters, 18000) == "hierarchical"

    def test_at_utilisation_boundary_returns_single_shot(self):
        # 12600 chars = 18000 * 0.7 exactly -> should be single_shot
        chapters = [{"text": "A" * 12600, "segments": []}]
        assert _choose_strategy(chapters, 18000) == "single_shot"

    def test_just_over_utilisation_boundary_routes_per_chapter(self):
        # 12601 chars > 18000 * 0.7 -> should NOT be single_shot
        chapters = [{"text": "A" * 12601, "segments": []}]
        assert _choose_strategy(chapters, 18000) != "single_shot"

    def test_empty_chapters_returns_single_shot(self):
        assert _choose_strategy([], 18000) == "single_shot"

    def test_missing_text_field(self):
        chapters = [{"segments": []}]
        assert _choose_strategy(chapters, 18000) == "single_shot"


# ---------------------------------------------------------------------------
# Omlx single-shot tests
# ---------------------------------------------------------------------------

class TestOmlxSingleShot:
    def test_single_shot_route_uses_one_call(self):
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        response_json = json.dumps(VALID_SUMMARY)
        with patch.object(gen, "_call_omlx", return_value=response_json) as mock_call:
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert mock_call.call_count == 1
        assert result["chapters"][0]["title"] == "Introduction"
        assert "summary_en" in result["overall_summary"]

    def test_single_shot_saves_strategy_artifact(self, tmp_path: Path):
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        artifact_dir = tmp_path / "artifacts"
        response_json = json.dumps(VALID_SUMMARY)
        with patch.object(gen, "_call_omlx", return_value=response_json):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"],
                          artifact_dir=artifact_dir)
        strategy_file = artifact_dir / "summarizer_strategy.txt"
        assert strategy_file.exists()
        assert strategy_file.read_text() == "single_shot"

    def test_per_chapter_saves_strategy_artifact(self, tmp_path: Path):
        big_chapters = [
            {
                "start_s": 0.0, "end_s": 60.0, "title_hint": "Ch1",
                "text": "A" * 10000,
                "segments": [{"text": "A" * 10000, "start_s": 0.0, "end_s": 60.0, "source": "captions"}],
            },
            {
                "start_s": 60.0, "end_s": 120.0, "title_hint": "Ch2",
                "text": "B" * 10000,
                "segments": [{"text": "B" * 10000, "start_s": 60.0, "end_s": 120.0, "source": "captions"}],
            },
        ]
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        artifact_dir = tmp_path / "artifacts"
        responses = [
            json.dumps(VALID_CHAPTER_SUMMARY),
            json.dumps(VALID_CHAPTER_SUMMARY),
            json.dumps(VALID_OVERALL_SUMMARY),
        ]
        with patch.object(gen, "_call_omlx", side_effect=responses):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, big_chapters, ["en", "zh-CN"],
                          artifact_dir=artifact_dir)
        strategy_file = artifact_dir / "summarizer_strategy.txt"
        assert strategy_file.exists()
        assert strategy_file.read_text() == "per_chapter"

    def test_single_shot_fallback_on_bad_json(self):
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        with patch.object(gen, "_call_omlx", return_value="not json"):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Chapter 1"  # rule-based

    def test_single_shot_progress_callback(self):
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        response_json = json.dumps(VALID_SUMMARY)
        stages: list[str] = []
        with patch.object(gen, "_call_omlx", return_value=response_json):
            gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"],
                          progress_callback=stages.append)
        assert "summarizing_single_shot" in stages
        assert "summarizing_chunks" not in stages

    def test_single_shot_rejects_malformed_chapter(self):
        """Single-shot with chapter missing required keys falls back to rule-based."""
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        # Chapter missing summary_zh and key_points
        bad_payload = {
            "chapters": [{"start_s": 0, "end_s": 60, "title": "T", "summary_en": "X"}],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        with patch.object(gen, "_call_omlx", return_value=json.dumps(bad_payload)):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        # Should have fallen back to rule-based
        assert result["chapters"][0]["title"] == "Chapter 1"

    def test_single_shot_rejects_malformed_overall(self):
        """Single-shot with overall missing required keys falls back to rule-based."""
        settings = _omlx_settings(OVS_SUMMARIZER_MAX_INPUT_CHARS="18000")
        gen = OmlxSummaryGenerator(settings)
        bad_payload = {
            "chapters": [VALID_CHAPTER_SUMMARY],
            "overall_summary": {"summary_en": "X"},  # missing summary_zh and highlights
        }
        with patch.object(gen, "_call_omlx", return_value=json.dumps(bad_payload)):
            result = gen.summarize(SAMPLE_METADATA, SAMPLE_SEGMENTS, SAMPLE_CHAPTERS, ["en", "zh-CN"])
        assert result["chapters"][0]["title"] == "Chapter 1"


# ---------------------------------------------------------------------------
# Single-shot payload validation unit tests
# ---------------------------------------------------------------------------

class TestValidateSingleShotPayload:
    def test_valid_payload_passes(self):
        result = _validate_single_shot_payload(VALID_SUMMARY)
        assert result is VALID_SUMMARY

    def test_missing_chapter_key_raises(self):
        bad = {
            "chapters": [{"start_s": 0, "end_s": 60, "title": "T"}],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        with pytest.raises(ValueError, match="missing keys"):
            _validate_single_shot_payload(bad)

    def test_missing_overall_key_raises(self):
        bad = {
            "chapters": [VALID_CHAPTER_SUMMARY],
            "overall_summary": {"summary_en": "X"},
        }
        with pytest.raises(ValueError, match="missing keys"):
            _validate_single_shot_payload(bad)

    def test_chapter_not_dict_raises(self):
        bad = {
            "chapters": ["not a dict"],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        with pytest.raises(ValueError, match="not a dict"):
            _validate_single_shot_payload(bad)

    def test_chapter_count_mismatch_raises(self):
        """LLM merging/dropping chapters must be rejected."""
        payload = {
            "chapters": [VALID_CHAPTER_SUMMARY],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        # Expect 2 but got 1
        with pytest.raises(ValueError, match="expected 2"):
            _validate_single_shot_payload(payload, expected_chapters=2)

    def test_chapter_count_match_passes(self):
        payload = {
            "chapters": [VALID_CHAPTER_SUMMARY],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        result = _validate_single_shot_payload(payload, expected_chapters=1)
        assert result is payload

    def test_chapter_count_none_skips_check(self):
        """Without expected_chapters, any count is accepted (backward compat)."""
        payload = {
            "chapters": [VALID_CHAPTER_SUMMARY, VALID_CHAPTER_SUMMARY],
            "overall_summary": VALID_OVERALL_SUMMARY,
        }
        result = _validate_single_shot_payload(payload)
        assert len(result["chapters"]) == 2


# ---------------------------------------------------------------------------
# Routing with utilisation factor
# ---------------------------------------------------------------------------

class TestRoutingUtilisation:
    def test_near_threshold_routes_to_per_chapter(self):
        """Text near threshold should NOT route to single_shot due to overhead margin."""
        # 16000 chars is > 18000 * 0.7 = 12600, so should NOT be single_shot
        chapters = [{"text": "A" * 16000, "segments": []}]
        assert _choose_strategy(chapters, 18000) != "single_shot"

    def test_well_under_threshold_routes_to_single_shot(self):
        """Text well under threshold should route to single_shot."""
        # 5000 chars < 18000 * 0.7 = 12600
        chapters = [{"text": "A" * 5000, "segments": []}]
        assert _choose_strategy(chapters, 18000) == "single_shot"
