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

    def test_generate_learning_objectives_from_chapter_titles(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        objectives = result["learning_objectives"]
        assert len(objectives) == 3
        # Should have action verb prefixes
        assert objectives[0].startswith("Understand ")
        assert "Introduction to Machine Learning" in objectives[0]
        assert objectives[1].startswith("Learn about ")
        assert "Neural Networks" in objectives[1]

    def test_generate_learning_objectives_fallback_to_highlights(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        overall = _make_overall_summary()
        # No chapter titles
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=[{"summary_en": "X", "summary_zh": "Y", "key_points": []}],
            overall_summary=overall,
        )
        assert result is not None
        objectives = result["learning_objectives"]
        # Highlights should get "Understand " prefix
        assert all("Understand " in obj or obj.lower().startswith("understand ") for obj in objectives)

    def test_learning_objectives_no_double_prefix(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter_summaries = [
            {"title": "Understand the basics", "summary_en": "X", "summary_zh": "Y", "key_points": []},
            {"title": "Learn to debug effectively", "summary_en": "X", "summary_zh": "Y", "key_points": []},
            {"title": "Analyze performance bottlenecks", "summary_en": "X", "summary_zh": "Y", "key_points": []},
        ]
        result = gen.generate(
            source_metadata={}, chapters=[], chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        objectives = result["learning_objectives"]
        # None of these should be double-prefixed
        assert objectives[0] == "Understand the basics"
        assert objectives[1] == "Learn to debug effectively"
        assert objectives[2] == "Analyze performance bottlenecks"

    def test_generate_final_takeaways_from_key_points(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # Should be derived from chapter key_points, not highlights
        expected_kps = ["Supervised learning", "Unsupervised learning",
                        "Backpropagation", "Activation functions",
                        "Learning rate scheduling"]
        assert result["final_takeaways"] == expected_kps

    def test_final_takeaways_fallback_to_highlights(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        # Chapters with no key_points
        chapter_summaries = [{"title": "Ch1", "summary_en": "X", "summary_zh": "Y", "key_points": []}]
        overall = _make_overall_summary()
        result = gen.generate(
            source_metadata={}, chapters=[], chapter_summaries=chapter_summaries, overall_summary=overall,
        )
        assert result is not None
        assert result["final_takeaways"] == overall["highlights"][:5]

    def test_objectives_and_takeaways_are_different(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=_make_chapter_summaries(),
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert result["learning_objectives"] != result["final_takeaways"]

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

    def test_objectives_capped_at_five(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        # More than 5 chapters → objectives capped at 5
        chapter_summaries = [
            {"title": f"Chapter {i}", "summary_en": "", "summary_zh": "", "key_points": [f"kp{i}"]}
            for i in range(8)
        ]
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["learning_objectives"]) == 5

    def test_takeaways_capped_at_five(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter_summaries = [
            {"title": f"Ch{i}", "summary_en": "", "summary_zh": "", "key_points": [f"kp{i}a", f"kp{i}b"]}
            for i in range(5)
        ]
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["final_takeaways"]) == 5

    def test_non_list_key_points_ignored(self) -> None:
        """Non-list key_points (e.g. null from LLM) must not crash generation."""
        gen = StudyPackGenerator(_make_settings())
        chapter_summaries = [
            {"title": "Ch1", "summary_en": "X", "summary_zh": "Y", "key_points": None},
            {"title": "Ch2", "summary_en": "X", "summary_zh": "Y", "key_points": "not a list"},
            {"title": "Ch3", "summary_en": "X", "summary_zh": "Y", "key_points": ["valid"]},
        ]
        result = gen.generate(
            source_metadata={},
            chapters=[],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # Only the valid key_point should appear in takeaways
        assert result["final_takeaways"] == ["valid"]
        # Sections should have empty lists for non-list key_points
        assert result["sections"][0]["key_points"] == []
        assert result["sections"][1]["key_points"] == []
        assert result["sections"][2]["key_points"] == ["valid"]


# ---------------------------------------------------------------------------
# Section refinement helpers
# ---------------------------------------------------------------------------

def _make_oversized_segments(word_count: int, num_segments: int, start_s: float = 0.0, duration_s: float = 600.0) -> list[dict]:
    """Create segments totalling approximately *word_count* words over *duration_s* seconds."""
    words_per_seg = max(1, word_count // num_segments)
    seg_duration = duration_s / num_segments
    segments = []
    for i in range(num_segments):
        s_start = start_s + i * seg_duration
        s_end = s_start + seg_duration
        text = " ".join(f"word{i}_{j}" for j in range(words_per_seg))
        # Add sentence endings to some segments so _extract_summary_sentences works.
        if i % 3 == 2:
            text += "."
        segments.append({"start_s": s_start, "end_s": s_end, "text": text})
    return segments


def _make_oversized_chapter(start_s: float = 0.0, end_s: float = 600.0, word_count: int = 600) -> dict:
    """Create a chapter dict with segments exceeding refinement thresholds."""
    segments = _make_oversized_segments(word_count, num_segments=20, start_s=start_s, duration_s=end_s - start_s)
    text = " ".join(seg["text"] for seg in segments)
    return {
        "start_s": start_s,
        "end_s": end_s,
        "title_hint": "Long Chapter",
        "segments": segments,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Section refinement tests
# ---------------------------------------------------------------------------

class TestSectionRefinement:
    def test_oversized_chapter_is_split(self) -> None:
        """Chapter >5 min and >450 words should produce 2-3 sub-sections."""
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter(start_s=0.0, end_s=600.0, word_count=600)
        chapter_summaries = [{
            "title": "Long Topic",
            "summary_en": "Overview of long topic.",
            "summary_zh": "长主题概述。",
            "key_points": ["KP1", "KP2", "KP3"],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        sections = result["sections"]
        assert len(sections) >= 2
        assert len(sections) <= 3
        # All sub-sections share the same chapter_index.
        assert all(s["chapter_index"] == 0 for s in sections)

    def test_refined_section_titles_have_part_labels(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter(start_s=0.0, end_s=600.0, word_count=600)
        chapter_summaries = [{
            "title": "Long Topic",
            "summary_en": "Summary.",
            "summary_zh": "摘要。",
            "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        titles = [s["title"] for s in result["sections"]]
        assert titles[0] == "Long Topic (Part 1)"
        assert titles[1] == "Long Topic (Part 2)"

    def test_refined_first_section_inherits_llm_summary(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter()
        chapter_summaries = [{
            "title": "Topic",
            "summary_en": "LLM produced summary.",
            "summary_zh": "LLM生成的摘要。",
            "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert result["sections"][0]["summary_en"] == "LLM produced summary."
        assert result["sections"][0]["summary_zh"] == "LLM生成的摘要。"

    def test_refined_additional_sections_have_extracted_summary(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter()
        chapter_summaries = [{
            "title": "Topic",
            "summary_en": "LLM summary.",
            "summary_zh": "摘要。",
            "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # Second sub-section should have non-empty extracted summary_en.
        assert result["sections"][1]["summary_en"] != ""
        # summary_zh is empty for extracted sub-sections.
        assert result["sections"][1]["summary_zh"] == ""

    def test_refined_timestamps_are_contiguous(self) -> None:
        """Sub-section timestamps should not overlap and should cover the chapter range."""
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter(start_s=100.0, end_s=700.0)
        chapter_summaries = [{
            "title": "T", "summary_en": "S", "summary_zh": "Z", "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        sections = result["sections"]
        # First section starts at or after chapter start.
        assert sections[0]["start_s"] >= 100.0
        # Last section ends at or before chapter end.
        assert sections[-1]["end_s"] <= 700.0
        # No gaps or overlaps: each section starts where the previous ended or after.
        for i in range(1, len(sections)):
            assert sections[i]["start_s"] >= sections[i - 1]["end_s"]

    def test_key_points_distributed_across_sub_sections(self) -> None:
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter()
        chapter_summaries = [{
            "title": "T", "summary_en": "S", "summary_zh": "Z",
            "key_points": ["A", "B", "C", "D"],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        all_kps = []
        for s in result["sections"]:
            all_kps.extend(s["key_points"])
        # All key_points are preserved.
        assert sorted(all_kps) == sorted(["A", "B", "C", "D"])

    def test_short_chapter_not_refined(self) -> None:
        """Chapters under 5 min or under 450 words should not be split."""
        gen = StudyPackGenerator(_make_settings())
        # 4 min chapter with 500 words — duration too short.
        chapter = _make_oversized_chapter(start_s=0.0, end_s=240.0, word_count=500)
        chapter_summaries = [{
            "title": "Short", "summary_en": "S", "summary_zh": "Z", "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["sections"]) == 1
        assert "(Part" not in result["sections"][0]["title"]

    def test_low_word_count_not_refined(self) -> None:
        """Chapters with enough duration but <450 words should not be split."""
        gen = StudyPackGenerator(_make_settings())
        chapter = _make_oversized_chapter(start_s=0.0, end_s=600.0, word_count=400)
        chapter_summaries = [{
            "title": "Sparse", "summary_en": "S", "summary_zh": "Z", "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["sections"]) == 1

    def test_total_sections_capped_but_trailing_chapters_preserved(self) -> None:
        """Oversized chapters stop splitting at 10, but trailing chapters still get 1 section each."""
        gen = StudyPackGenerator(_make_settings())
        chapters = []
        chapter_summaries = []
        for i in range(6):
            chapters.append(_make_oversized_chapter(
                start_s=i * 700, end_s=(i + 1) * 700, word_count=900,
            ))
            chapter_summaries.append({
                "title": f"Chapter {i + 1}",
                "summary_en": f"Summary {i + 1}.",
                "summary_zh": f"摘要{i + 1}。",
                "key_points": [f"kp{i}"],
            })
        result = gen.generate(
            source_metadata={},
            chapters=chapters,
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # Early chapters get refined (2-3 sections each), later ones fall back to 1.
        # All 6 chapters must be represented — no chapter dropped.
        represented = {s["chapter_index"] for s in result["sections"]}
        assert represented == {0, 1, 2, 3, 4, 5}

    def test_mixed_chapters_only_oversized_refined(self) -> None:
        """Only oversized chapters get split; normal ones pass through as 1 section."""
        gen = StudyPackGenerator(_make_settings())
        small_ch = {"start_s": 0, "end_s": 200, "segments": [], "text": "short"}
        big_ch = _make_oversized_chapter(start_s=200, end_s=900, word_count=700)
        chapters = [small_ch, big_ch]
        chapter_summaries = [
            {"title": "Small", "summary_en": "S", "summary_zh": "Z", "key_points": []},
            {"title": "Big", "summary_en": "B", "summary_zh": "大", "key_points": ["X"]},
        ]
        result = gen.generate(
            source_metadata={},
            chapters=chapters,
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # First section is the small chapter (chapter_index=0), not split.
        assert result["sections"][0]["chapter_index"] == 0
        assert "(Part" not in result["sections"][0]["title"]
        # Remaining sections are from the big chapter (chapter_index=1).
        big_sections = [s for s in result["sections"] if s["chapter_index"] == 1]
        assert len(big_sections) >= 2

    def test_cjk_chapter_refinement(self) -> None:
        """Chinese text (no spaces) should still trigger refinement via CJK char counting."""
        gen = StudyPackGenerator(_make_settings())
        # 500 CJK characters across 10 segments, 10 min duration — should refine.
        segments = []
        for i in range(10):
            text = "这是测试" * 12 + "。"  # 49 chars per segment, ~50 "words" via CJK counting
            segments.append({"start_s": i * 60, "end_s": (i + 1) * 60, "text": text})
        chapter = {
            "start_s": 0.0,
            "end_s": 600.0,
            "title_hint": "中文章节",
            "segments": segments,
            "text": " ".join(seg["text"] for seg in segments),
        }
        chapter_summaries = [{
            "title": "中文主题",
            "summary_en": "Chinese topic summary.",
            "summary_zh": "中文主题摘要。",
            "key_points": ["要点一", "要点二"],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        # CJK counting should recognize this as >450 words, triggering refinement.
        assert len(result["sections"]) >= 2
        assert "(Part" in result["sections"][0]["title"]

    def test_chapter_without_segments_not_refined(self) -> None:
        """If chapter has no segments data, it passes through without refinement."""
        gen = StudyPackGenerator(_make_settings())
        # 10-minute chapter but no segments.
        chapter = {"start_s": 0, "end_s": 600, "text": "no segments"}
        chapter_summaries = [{
            "title": "NoSegs", "summary_en": "S", "summary_zh": "Z", "key_points": [],
        }]
        result = gen.generate(
            source_metadata={},
            chapters=[chapter],
            chapter_summaries=chapter_summaries,
            overall_summary=_make_overall_summary(),
        )
        assert result is not None
        assert len(result["sections"]) == 1


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
                    "start_s": 0.0,
                    "end_s": 300.0,
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

    def test_render_contains_timestamps(self) -> None:
        sp = {
            "learning_objectives": [],
            "sections": [
                {
                    "title": "Introduction",
                    "start_s": 0.0,
                    "end_s": 300.0,
                    "summary_en": "Intro.",
                    "summary_zh": "介绍。",
                    "key_points": [],
                },
                {
                    "title": "Main Content",
                    "start_s": 300.0,
                    "end_s": 3661.0,
                    "summary_en": "Content.",
                    "summary_zh": "内容。",
                    "key_points": [],
                },
            ],
            "final_takeaways": [],
        }
        md = render_study_guide_markdown(sp, {"title": "Test"})
        assert "[00:00\u201305:00]" in md
        assert "[05:00\u201361:01]" in md

    def test_render_section_without_timestamps(self) -> None:
        sp = {
            "learning_objectives": [],
            "sections": [{"title": "No Times", "summary_en": "X", "summary_zh": "Y", "key_points": []}],
            "final_takeaways": [],
        }
        md = render_study_guide_markdown(sp, {"title": "T"})
        assert "### No Times" in md
        assert "[" not in md.split("### No Times")[1].split("\n")[0]

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
