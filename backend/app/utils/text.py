from __future__ import annotations

import re


CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_language(text: str) -> str:
    if not text.strip():
        return "unknown"
    chinese_count = len(CHINESE_CHAR_RE.findall(text))
    ratio = chinese_count / max(len(text), 1)
    if ratio > 0.1:
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "unknown"


def split_sentences(text: str, limit: int = 2) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", normalized)
    return [part.strip() for part in parts if part.strip()][:limit]


def chunk_segments(segments: list[dict], max_chars: int) -> list[list[dict]]:
    """Group transcript segments into chunks respecting segment boundaries.

    Each chunk is a list of consecutive segments whose total text length
    does not exceed max_chars. Never splits mid-segment.
    If a single segment exceeds max_chars, it becomes its own chunk.
    """
    if not segments:
        return []
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0
    for seg in segments:
        seg_len = len(seg.get("text", ""))
        # Account for the joining space that segments_to_text inserts
        added_len = seg_len + (1 if current else 0)
        if current and current_len + added_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
            added_len = seg_len
        current.append(seg)
        current_len += added_len
    if current:
        chunks.append(current)
    return chunks


def segments_to_text(segments: list[dict]) -> str:
    """Join segment texts with spaces."""
    return " ".join(seg.get("text", "") for seg in segments)


def chunk_text(text: str, max_chars: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        chunks.append(normalized[start:end])
        start = end
    return chunks

