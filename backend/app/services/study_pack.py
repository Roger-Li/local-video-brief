from __future__ import annotations

import logging
import re
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.utils.text import CHINESE_CHAR_RE

logger = logging.getLogger(__name__)

# Section refinement thresholds.
_MIN_DURATION_FOR_SPLIT_S = 300  # 5 minutes
_MIN_WORDS_FOR_SPLIT = 450
_TARGET_WORDS_PER_SECTION = 300  # ~250-350
_MAX_TOTAL_SECTIONS = 10


def _count_words(text: str) -> int:
    """Count words in a CJK-safe way.

    Each CJK character counts as one word. Non-CJK tokens are counted
    via whitespace splitting (after stripping CJK chars to avoid
    double-counting).
    """
    cjk_count = len(CHINESE_CHAR_RE.findall(text))
    non_cjk = CHINESE_CHAR_RE.sub("", text)
    space_tokens = len(non_cjk.split()) if non_cjk.strip() else 0
    return cjk_count + space_tokens


class StudyPackGenerator:
    """Deterministic study-pack generator (v1, no LLM calls).

    Transforms existing chapter summaries and overall summary into a
    structured study pack.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        source_metadata: dict,
        chapters: list[dict],
        chapter_summaries: list[dict],
        overall_summary: dict,
        artifact_dir: Path | None = None,
    ) -> dict | None:
        """Generate study pack deterministically. Returns dict or None on failure. Never raises."""
        try:
            learning_objectives = self._derive_learning_objectives(
                overall_summary, chapter_summaries,
            )
            sections = self._build_sections(chapters, chapter_summaries)
            final_takeaways = self._derive_final_takeaways(
                overall_summary, chapter_summaries,
            )

            return {
                "version": 1,
                "format": "lecture_study_guide",
                "learning_objectives": learning_objectives,
                "sections": sections,
                "final_takeaways": final_takeaways,
            }
        except Exception as exc:
            logger.warning("study_pack generation failed: %s", exc)
            if artifact_dir is not None:
                try:
                    artifact_dir.mkdir(parents=True, exist_ok=True)
                    (artifact_dir / "study_pack_error.txt").write_text(
                        str(exc), encoding="utf-8",
                    )
                except Exception:
                    pass
            return None

    _OBJECTIVE_PREFIXES = [
        "Understand ",
        "Learn about ",
        "Explore ",
        "Examine ",
        "Discover ",
    ]

    # Broader set of action verb stems used to detect titles that are
    # already phrased as imperatives, so we don't double-prefix them.
    _ACTION_VERB_STEMS = (
        "understand ", "learn ", "explore ", "examine ", "discover ",
        "explain ", "analyze ", "compare ", "describe ", "identify ",
        "apply ", "evaluate ", "review ", "discuss ", "demonstrate ",
        "define ", "outline ", "summarize ", "investigate ",
    )

    def _derive_learning_objectives(
        self,
        overall_summary: dict,
        chapter_summaries: list[dict],
    ) -> list[str]:
        # Build objectives from chapter titles using action verb prefixes.
        titles = [cs.get("title", "") for cs in chapter_summaries if cs.get("title")]
        if titles:
            objectives = []
            for i, title in enumerate(titles[:5]):
                prefix = self._OBJECTIVE_PREFIXES[i % len(self._OBJECTIVE_PREFIXES)]
                # Avoid double-prefixing if title already starts with an action verb.
                if title.lower().startswith(self._ACTION_VERB_STEMS):
                    objectives.append(title)
                else:
                    objectives.append(f"{prefix}{title}")
            return objectives
        # Fallback: use highlights with action prefix.
        highlights = overall_summary.get("highlights", [])
        if highlights:
            return [
                h if h.lower().startswith(self._ACTION_VERB_STEMS) else f"Understand {h}"
                for h in highlights[:5]
            ]
        return []

    def _build_sections(
        self, chapters: list[dict], chapter_summaries: list[dict],
    ) -> list[dict]:
        sections: list[dict] = []
        # Budget: how many more sections we can emit before hitting the cap.
        budget = _MAX_TOTAL_SECTIONS

        for i, cs in enumerate(chapter_summaries):
            ch = chapters[i] if i < len(chapters) else {}
            start_s = ch.get("start_s", cs.get("start_s", 0.0))
            end_s = ch.get("end_s", cs.get("end_s", 0.0))
            title = cs.get("title", ch.get("title_hint", f"Chapter {i + 1}"))
            key_points = cs.get("key_points", []) if isinstance(cs.get("key_points"), list) else []

            segments = ch.get("segments", [])
            if budget >= 2 and self._should_refine(start_s, end_s, segments):
                sub_sections = self._refine_chapter(
                    i, start_s, end_s, title, cs, key_points, segments, budget,
                )
                sections.extend(sub_sections)
                budget -= len(sub_sections)
            else:
                # Single section per chapter (always emitted, even at budget 0,
                # so trailing chapters are never dropped from the study guide).
                sections.append({
                    "chapter_index": i,
                    "start_s": start_s,
                    "end_s": end_s,
                    "title": title,
                    "summary_en": cs.get("summary_en", ""),
                    "summary_zh": cs.get("summary_zh", ""),
                    "key_points": key_points,
                })
                budget -= 1
        return sections

    @staticmethod
    def _should_refine(start_s: float, end_s: float, segments: list[dict]) -> bool:
        """Return True if this chapter exceeds both duration and word thresholds."""
        duration = end_s - start_s
        if duration < _MIN_DURATION_FOR_SPLIT_S:
            return False
        word_count = sum(_count_words(seg.get("text", "")) for seg in segments)
        return word_count >= _MIN_WORDS_FOR_SPLIT

    def _refine_chapter(
        self,
        chapter_index: int,
        start_s: float,
        end_s: float,
        title: str,
        chapter_summary: dict,
        key_points: list[str],
        segments: list[dict],
        budget: int,
    ) -> list[dict]:
        """Split an oversized chapter into 2-3 sub-sections by word budget."""
        total_words = sum(_count_words(seg.get("text", "")) for seg in segments)
        target_parts = min(3, max(2, round(total_words / _TARGET_WORDS_PER_SECTION)))
        target_parts = min(target_parts, budget)  # respect global cap
        words_per_part = total_words / target_parts

        # Partition segments into sub-section groups.
        groups: list[list[dict]] = []
        current_group: list[dict] = []
        current_words = 0
        for seg in segments:
            seg_words = _count_words(seg.get("text", ""))
            current_group.append(seg)
            current_words += seg_words
            if current_words >= words_per_part and len(groups) < target_parts - 1:
                groups.append(current_group)
                current_group = []
                current_words = 0
        if current_group:
            groups.append(current_group)

        # Distribute key_points round-robin across sub-sections.
        kp_buckets: list[list[str]] = [[] for _ in range(len(groups))]
        for kp_idx, kp in enumerate(key_points):
            kp_buckets[kp_idx % len(groups)].append(kp)

        sub_sections: list[dict] = []
        for part_idx, group in enumerate(groups):
            g_start = group[0]["start_s"] if group else start_s
            g_end = group[-1]["end_s"] if group else end_s
            part_label = f" (Part {part_idx + 1})"
            if part_idx == 0:
                # First sub-section inherits the LLM-produced summary.
                sub_sections.append({
                    "chapter_index": chapter_index,
                    "start_s": g_start,
                    "end_s": g_end,
                    "title": title + part_label,
                    "summary_en": chapter_summary.get("summary_en", ""),
                    "summary_zh": chapter_summary.get("summary_zh", ""),
                    "key_points": kp_buckets[part_idx],
                })
            else:
                # Additional sub-sections: extract sentences from transcript slice.
                slice_text = " ".join(seg.get("text", "") for seg in group)
                summary_en = self._extract_summary_sentences(slice_text)
                sub_sections.append({
                    "chapter_index": chapter_index,
                    "start_s": g_start,
                    "end_s": g_end,
                    "title": title + part_label,
                    "summary_en": summary_en,
                    "summary_zh": "",
                    "key_points": kp_buckets[part_idx],
                })
        return sub_sections

    @staticmethod
    def _extract_summary_sentences(text: str, limit: int = 3) -> str:
        """Extract up to *limit* sentences from text for sub-section summaries."""
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return ""
        parts = re.split(r"(?<=[.!?。！？])\s+", normalized)
        sentences = [p.strip() for p in parts if p.strip()][:limit]
        if sentences:
            return " ".join(sentences)
        # No sentence boundaries: truncate to ~350 chars.
        if len(normalized) > 350:
            return normalized[:350].rstrip() + "…"
        return normalized

    def _derive_final_takeaways(
        self, overall_summary: dict, chapter_summaries: list[dict],
    ) -> list[str]:
        """Derive actionable takeaways from chapter key_points, falling back to highlights."""
        # Collect unique key_points across all chapters, preserving order.
        seen: set[str] = set()
        key_points: list[str] = []
        for cs in chapter_summaries:
            kps = cs.get("key_points", [])
            if not isinstance(kps, list):
                kps = []
            for kp in kps:
                if kp not in seen:
                    seen.add(kp)
                    key_points.append(kp)
        if key_points:
            return key_points[:5]
        # Fallback to highlights if no key_points available.
        return overall_summary.get("highlights", [])[:5]


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS."""
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def render_study_guide_markdown(study_pack: dict, source_metadata: dict) -> str:
    """Pure string formatting — no LLM. Returns standalone Markdown."""
    lines: list[str] = []

    title = source_metadata.get("title", "Study Guide")
    lines.append(f"# {title}")
    lines.append("")

    # Learning objectives
    objectives = study_pack.get("learning_objectives", [])
    if objectives:
        lines.append("## Learning Objectives")
        lines.append("")
        for obj in objectives:
            lines.append(f"- {obj}")
        lines.append("")

    # Sections
    sections = study_pack.get("sections", [])
    if sections:
        lines.append("## Sections")
        lines.append("")
        for section in sections:
            section_title = section.get("title", "Untitled")
            start_s = section.get("start_s")
            end_s = section.get("end_s")
            if isinstance(start_s, (int, float)) and isinstance(end_s, (int, float)):
                ts = f"[{_format_timestamp(start_s)}\u2013{_format_timestamp(end_s)}]"
                lines.append(f"### {section_title} {ts}")
            else:
                lines.append(f"### {section_title}")
            lines.append("")
            summary_en = section.get("summary_en", "")
            if summary_en:
                lines.append(summary_en)
                lines.append("")
            summary_zh = section.get("summary_zh", "")
            if summary_zh:
                lines.append(summary_zh)
                lines.append("")
            key_points = section.get("key_points", [])
            if key_points:
                lines.append("**Key Points:**")
                lines.append("")
                for kp in key_points:
                    lines.append(f"- {kp}")
                lines.append("")

    # Final takeaways
    takeaways = study_pack.get("final_takeaways", [])
    if takeaways:
        lines.append("## Final Takeaways")
        lines.append("")
        for ta in takeaways:
            lines.append(f"- {ta}")
        lines.append("")

    return "\n".join(lines)
