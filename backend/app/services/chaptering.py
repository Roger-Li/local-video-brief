from __future__ import annotations

import logging

from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class HeuristicChapterer:
    def __init__(self, settings: Settings) -> None:
        self.max_chapter_seconds = settings.max_chapter_minutes * 60

    def build_chapters(self, transcript_segments: list[dict]) -> list[dict]:
        if not transcript_segments:
            return []

        logger.info("building chapters: %d segments, max_chapter_seconds=%d",
                     len(transcript_segments), self.max_chapter_seconds)

        chapters: list[dict] = []
        current_segments: list[dict] = []
        chapter_start = transcript_segments[0]["start_s"]

        for segment in transcript_segments:
            if not current_segments:
                current_segments.append(segment)
                chapter_start = segment["start_s"]
                continue

            prev_segment = current_segments[-1]
            duration = segment["end_s"] - chapter_start
            gap = segment["start_s"] - prev_segment["end_s"]
            if gap >= 45 or duration >= self.max_chapter_seconds:
                reason = "gap" if gap >= 45 else "duration"
                logger.debug("chapter break at %.1fs: gap=%.1fs duration=%.1fs reason=%s",
                             segment["start_s"], gap, duration, reason)
                chapters.append(self._build_chapter(current_segments))
                current_segments = [segment]
                chapter_start = segment["start_s"]
            else:
                current_segments.append(segment)

        if current_segments:
            chapters.append(self._build_chapter(current_segments))

        # Second pass: density-aware repartitioning for dense single-chapter outputs.
        if len(chapters) == 1:
            chapters = self._density_repartition(chapters, transcript_segments)

        if chapters:
            logger.info("built %d chapters spanning %.0fs-%.0fs",
                         len(chapters), chapters[0]["start_s"], chapters[-1]["end_s"])
        return chapters

    def _density_repartition(
        self,
        chapters: list[dict],
        segments: list[dict],
    ) -> list[dict]:
        """Split a single dense chapter into multiple chapters by word budget."""
        if not segments:
            return chapters

        total_duration = segments[-1]["end_s"] - segments[0]["start_s"]
        total_words = sum(len(seg["text"].split()) for seg in segments)

        if total_duration < 180 or total_words < 300:
            return chapters

        target_chapters = min(4, max(2, round(total_words / 220)))
        words_per_chapter = total_words / target_chapters

        logger.info(
            "density repartition: duration=%.0fs words=%d target_chapters=%d words_per_chapter=%.0f",
            total_duration, total_words, target_chapters, words_per_chapter,
        )

        new_chapters: list[dict] = []
        current_segments: list[dict] = []
        current_words = 0

        for seg in segments:
            seg_words = len(seg["text"].split())
            current_segments.append(seg)
            current_words += seg_words

            if current_words >= words_per_chapter and len(new_chapters) < target_chapters - 1:
                new_chapters.append(self._build_chapter(current_segments))
                current_segments = []
                current_words = 0

        if current_segments:
            new_chapters.append(self._build_chapter(current_segments))

        return new_chapters

    def _build_chapter(self, segments: list[dict]) -> dict:
        start_s = segments[0]["start_s"]
        end_s = segments[-1]["end_s"]
        text = " ".join(segment["text"] for segment in segments)
        title = text[:60].strip() or f"Chapter starting at {start_s:.0f}s"
        return {
            "start_s": start_s,
            "end_s": end_s,
            "title_hint": title,
            "segments": segments,
            "text": text,
        }

