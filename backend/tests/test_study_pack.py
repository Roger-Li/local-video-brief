from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.schemas.jobs import JobResultResponse, StudyPack, StudySection
from backend.app.services.study_pack import StudyPackGenerator, render_study_guide_markdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_chapter_summaries() -> list[dict]:
    return [
        {
            "start_s": 0.0,
            "end_s": 300.0,
            "title": "Introduction to Machine Learning",
            "summary_en": "Overview of ML concepts.",
            "summary_zh": "机器学习概述。",
            "key_points": ["Supervised learning", "Unsupervised learning"],
        },
        {
            "start_s": 300.0,
            "end_s": 600.0,
            "title": "Neural Networks",
            "summary_en": "Deep dive into neural networks.",
            "summary_zh": "深入了解神经网络。",
            "key_points": ["Backpropagation", "Activation functions"],
        },
        {
            "start_s": 600.0,
            "end_s": 900.0,
            "title": "Training Strategies",
            "summary_en": "Methods for training models effectively.",
            "summary_zh": "有效训练模型的方法。",
            "key_points": ["Learning rate scheduling", "Regularization"],
        },
    ]


def _make_overall_summary() -> dict:
    return {
        "summary_en": "A comprehensive introduction to ML.",
        "summary_zh": "全面的机器学习入门。",
        "highlights": [
            "ML fundamentals covered",
            "Neural network architectures explained",
            "Practical training tips provided",
        ],
    }


def _make_settings() -> Settings:
    return Settings(
        summarizer_provider="fallback",
        enable_study_pack=True,
    )


# ---------------------------------------------------------------------------
# StudyPackGenerator tests
# ---------------------------------------------------------------------------

class TestStudyPackGenerator:
    def test_generate_produces_valid_structure(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={"title": "Test Lecture"},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert result["version"] == 1
        assert result["format"] == "lecture_study_guide"
        assert "learning_objectives" in result
        assert "sections" in result
        assert "final_takeaways" in result

    def test_generate_one_section_per_chapter(self) -> None:
        chapter_summaries = _make_chapter_summaries()
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["sections"]) == len(chapter_summaries)

    def test_section_chapter_indices_sequential(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        indices = [s["chapter_index"] for s in result["sections"]]
        assert indices == [0, 1, 2]

    def test_section_fields_from_chapter_summary(self) -> None:
        chapter_summaries = _make_chapter_summaries()
        chapters = [
            {"start_s": 0.0, "end_s": 300.0, "title_hint": "Ch1"},
            {"start_s": 300.0, "end_s": 600.0, "title_hint": "Ch2"},
            {"start_s": 600.0, "end_s": 900.0, "title_hint": "Ch3"},
        ]
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=chapters,
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        s0 = result["sections"][0]
        cs0 = chapter_summaries[0]
        # Timestamps from authoritative chapters, summaries from LLM output
        assert s0["start_s"] == chapters[0]["start_s"]
        assert s0["end_s"] == chapters[0]["end_s"]
        assert s0["title"] == cs0["title"]
        assert s0["summary_en"] == cs0["summary_en"]
        assert s0["summary_zh"] == cs0["summary_zh"]
        assert s0["key_points"] == cs0["key_points"]

    def test_section_timestamps_from_authoritative_chapters(self) -> None:
        """Authoritative chapter timestamps override LLM-produced values."""
        chapter_summaries = [
            {
                "start_s": 10.0,  # LLM rounded/hallucinated
                "end_s": 295.0,
                "title": "Intro",
                "summary_en": "Summary.",
                "summary_zh": "摘要。",
                "key_points": ["A"],
            },
        ]
        chapters = [
            {"start_s": 5.2, "end_s": 300.8, "title_hint": "Chapter 1"},
        ]
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=chapters,
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        s0 = result["sections"][0]
        assert s0["start_s"] == 5.2   # from chapters, not 10.0
        assert s0["end_s"] == 300.8   # from chapters, not 295.0
        assert s0["title"] == "Intro"  # title from LLM summary

    def test_generate_learning_objectives_from_highlights(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        overall = _make_overall_summary()
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=overall,
        )
        assert result is not None
        assert result["learning_objectives"] == overall["highlights"][:5]

    def test_generate_learning_objectives_fallback_to_titles(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        overall = {"summary_en": "", "summary_zh": "", "highlights": []}
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=overall,
        )
        assert result is not None
        assert result["learning_objectives"] == [
            "Introduction to Machine Learning",
            "Neural Networks",
            "Training Strategies",
        ]

    def test_generate_final_takeaways_from_highlights(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        overall = _make_overall_summary()
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=overall,
        )
        assert result is not None
        assert result["final_takeaways"] == overall["highlights"]

    def test_generate_returns_none_on_failure(self, tmp_path: Path) -> None:
        """Given completely broken input, generate returns None and writes error artifact."""
        gen = StudyPackGenerator(_make_settings())
        # Pass a non-dict overall_summary to trigger an error inside _derive_learning_objectives
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries="not a list",  # type: ignore[arg-type]
            overall_summary={"highlights": ["ok"]},
            artifact_dir=tmp_path,
        )
        assert result is None
        assert (tmp_path / "study_pack_error.txt").exists()

    def test_generate_empty_chapters(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=[],
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert result["sections"] == []

    def test_highlights_capped_at_five(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        overall = {
            "summary_en": "",
            "summary_zh": "",
            "highlights": [f"h{i}" for i in range(10)],
        }
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=[],
            overall_summary=overall,
        )
        assert result is not None
        assert len(result["learning_objectives"]) == 5


# ---------------------------------------------------------------------------
# Markdown renderer tests
# ---------------------------------------------------------------------------

class TestRenderMarkdown:
    def test_render_contains_title(self) -> None:
        sp = {
            "learning_objectives": ["Learn X"],
            "sections": [],
            "final_takeaways": ["Remember X"],
        }
        md = render_study_guide_markdown(sp, {"title": "My Lecture"})
        assert "# My Lecture" in md

    def test_render_contains_sections(self) -> None:
        sp = {
            "learning_objectives": [],
            "sections": [
                {
                    "title": "Intro",
                    "summary_en": "English summary.",
                    "summary_zh": "中文摘要。",
                    "key_points": ["Point A"],
                },
            ],
            "final_takeaways": [],
        }
        md = render_study_guide_markdown(sp, {"title": "Test"})
        assert "### Intro" in md
        assert "English summary." in md
        assert "中文摘要。" in md
        assert "- Point A" in md

    def test_render_contains_objectives_and_takeaways(self) -> None:
        sp = {
            "learning_objectives": ["Obj 1", "Obj 2"],
            "sections": [],
            "final_takeaways": ["Take 1"],
        }
        md = render_study_guide_markdown(sp, {"title": "T"})
        assert "## Learning Objectives" in md
        assert "- Obj 1" in md
        assert "## Final Takeaways" in md
        assert "- Take 1" in md

    def test_render_fallback_title(self) -> None:
        sp = {"learning_objectives": [], "sections": [], "final_takeaways": []}
        md = render_study_guide_markdown(sp, {})
        assert "# Study Guide" in md


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemaCompatibility:
    def test_study_pack_schema_optional(self) -> None:
        """JobResultResponse validates with and without study_pack."""
        base = {
            "job_id": "test-1",
            "status": "completed",
            "source_metadata": {},
            "transcript_segments": [],
            "chapters": [],
            "overall_summary": {"summary_en": "", "summary_zh": "", "highlights": []},
            "artifacts": {},
        }
        # Without study_pack
        resp_none = JobResultResponse(**base)
        assert resp_none.study_pack is None

        # With study_pack
        sp = {
            "version": 1,
            "format": "lecture_study_guide",
            "learning_objectives": ["Learn X"],
            "sections": [
                {
                    "chapter_index": 0,
                    "start_s": 0.0,
                    "end_s": 60.0,
                    "title": "Intro",
                    "summary_en": "Intro.",
                    "summary_zh": "介绍。",
                    "key_points": ["A"],
                }
            ],
            "final_takeaways": ["Remember X"],
        }
        resp_with = JobResultResponse(**{**base, "study_pack": sp})
        assert resp_with.study_pack is not None
        assert resp_with.study_pack.version == 1
        assert len(resp_with.study_pack.sections) == 1

    def test_study_section_model(self) -> None:
        section = StudySection(
            chapter_index=0,
            start_s=0.0,
            end_s=120.0,
            title="Test",
            summary_en="En.",
            summary_zh="Zh.",
            key_points=["A", "B"],
        )
        assert section.chapter_index == 0
        assert section.key_points == ["A", "B"]

    def test_study_pack_model_defaults(self) -> None:
        sp = StudyPack(
            learning_objectives=["X"],
            sections=[],
            final_takeaways=["Y"],
        )
        assert sp.version == 1
        assert sp.format == "lecture_study_guide"


# ---------------------------------------------------------------------------
# Config test
# ---------------------------------------------------------------------------

def test_study_pack_flag_defaults_false(monkeypatch) -> None:
    monkeypatch.delenv("OVS_ENABLE_STUDY_PACK", raising=False)
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    monkeypatch.delenv("OVS_ENABLE_MLX_SUMMARIZER", raising=False)
    settings = Settings()
    assert settings.enable_study_pack is False


def test_study_pack_flag_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OVS_ENABLE_STUDY_PACK", "true")
    monkeypatch.delenv("OVS_SUMMARIZER_PROVIDER", raising=False)
    monkeypatch.delenv("OVS_ENABLE_MLX_SUMMARIZER", raising=False)
    settings = Settings()
    assert settings.enable_study_pack is True
