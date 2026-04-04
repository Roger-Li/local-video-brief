from __future__ import annotations

import logging
from pathlib import Path

from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


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
        sections = []
        for i, cs in enumerate(chapter_summaries):
            # Use authoritative chapter data for timestamps/title,
            # fall back to LLM summary values only if chapter data is missing.
            ch = chapters[i] if i < len(chapters) else {}
            sections.append({
                "chapter_index": i,
                "start_s": ch.get("start_s", cs.get("start_s", 0.0)),
                "end_s": ch.get("end_s", cs.get("end_s", 0.0)),
                "title": cs.get("title", ch.get("title_hint", f"Chapter {i + 1}")),
                "summary_en": cs.get("summary_en", ""),
                "summary_zh": cs.get("summary_zh", ""),
                "key_points": cs.get("key_points", []) if isinstance(cs.get("key_points"), list) else [],
            })
        return sections

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
