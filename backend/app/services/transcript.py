from __future__ import annotations

import logging
from pathlib import Path
import re

from backend.app.services.interfaces import SubtitleArtifact
from backend.app.utils.text import detect_language

logger = logging.getLogger(__name__)


TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


def _timecode_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class VttTranscriptProvider:
    def load(self, subtitles: list[SubtitleArtifact]) -> list[dict]:
        logger.info("loading %d subtitle file(s)", len(subtitles))
        segments: list[dict] = []
        for subtitle in subtitles:
            segments.extend(self._parse_vtt(subtitle.path, subtitle.language, subtitle.source))
        segments.sort(key=lambda item: item["start_s"])
        logger.info("loaded %d segments, %d total chars",
                     len(segments), sum(len(s["text"]) for s in segments))
        return segments

    def _parse_vtt(self, path: Path, language: str, source: str) -> list[dict]:
        logger.info("parsing VTT: path=%s language=%s source=%s", path.name, language, source)
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
            text = VTT_TAG_RE.sub("", text)
            text = re.sub(r"\s+", " ", text).strip()
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
        if segments:
            time_span = segments[-1]["end_s"] - segments[0]["start_s"]
            logger.info("parsed %s: %d blocks -> %d segments, %.0fs span",
                         path.name, len(blocks), len(segments), time_span)
        else:
            logger.warning("no usable segments from %s", path.name)
        return segments

