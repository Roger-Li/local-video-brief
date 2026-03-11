from __future__ import annotations

from pathlib import Path
import re

from backend.app.services.interfaces import SubtitleArtifact
from backend.app.utils.text import detect_language


TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)


def _timecode_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class VttTranscriptProvider:
    def load(self, subtitles: list[SubtitleArtifact]) -> list[dict]:
        segments: list[dict] = []
        for subtitle in subtitles:
            segments.extend(self._parse_vtt(subtitle.path, subtitle.language, subtitle.source))
        segments.sort(key=lambda item: item["start_s"])
        return segments

    def _parse_vtt(self, path: Path, language: str, source: str) -> list[dict]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        blocks = re.split(r"\n\s*\n", content)
        segments: list[dict] = []
        for block in blocks:
            match = TIMECODE_RE.search(block)
            if not match:
                continue
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            text_lines = [line for line in lines if "-->" not in line and line != "WEBVTT" and not line.isdigit()]
            text = " ".join(text_lines).strip()
            if not text:
                continue
            segments.append(
                {
                    "start_s": _timecode_to_seconds(match.group("start")),
                    "end_s": _timecode_to_seconds(match.group("end")),
                    "text": text,
                    "language": language or detect_language(text),
                    "source": source,
                    "confidence": None,
                }
            )
        return segments

