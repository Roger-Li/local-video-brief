from __future__ import annotations

from backend.app.core.config import Settings


class HeuristicChapterer:
    def __init__(self, settings: Settings) -> None:
        self.max_chapter_seconds = settings.max_chapter_minutes * 60

    def build_chapters(self, transcript_segments: list[dict]) -> list[dict]:
        if not transcript_segments:
            return []

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
                chapters.append(self._build_chapter(current_segments))
                current_segments = [segment]
                chapter_start = segment["start_s"]
            else:
                current_segments.append(segment)

        if current_segments:
            chapters.append(self._build_chapter(current_segments))
        return chapters

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

