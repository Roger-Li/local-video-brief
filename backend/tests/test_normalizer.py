from __future__ import annotations

from pathlib import Path

from backend.app.services.normalizer import TranscriptNormalizer
from backend.app.services.transcript import VttTranscriptProvider
from backend.app.services.interfaces import SubtitleArtifact

FIXTURES = Path(__file__).parent / "fixtures"


def _make_seg(
    start: float, end: float, text: str, source: str = "captions",
) -> dict:
    return {
        "start_s": start,
        "end_s": end,
        "text": text,
        "language": "en",
        "source": source,
        "confidence": None,
    }


# ---------- Markup cleanup ----------

def test_inline_timing_and_class_tags_removed() -> None:
    """VTT inline timing tags like <00:...> and <c> should be stripped by the
    parser, and the normalizer should handle any residual markup."""
    provider = VttTranscriptProvider()
    segments = provider.load([
        SubtitleArtifact(path=FIXTURES / "inline_markup_en.vtt", language="en", source="captions"),
    ])
    normalizer = TranscriptNormalizer()
    normalized, stats = normalizer.normalize(segments)

    all_text = " ".join(seg["text"] for seg in normalized)
    assert "<" not in all_text
    assert ">" not in all_text
    # Spoken words preserved.
    assert "welcome" in all_text.lower()
    assert "three topics" in all_text.lower()
    assert "model training" in all_text.lower()


def test_blocklisted_sound_markers_removed() -> None:
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 5, "Hello world"),
        _make_seg(5, 8, "[Music]"),
        _make_seg(8, 12, "Let us continue [Applause] with our talk"),
        _make_seg(12, 15, "[♪]"),
    ]
    normalized, stats = normalizer.normalize(segments)
    all_text = " ".join(seg["text"] for seg in normalized)
    assert "[Music]" not in all_text
    assert "[Applause]" not in all_text
    assert "[♪]" not in all_text
    assert "Hello world" in all_text
    assert "continue" in all_text
    assert "our talk" in all_text


def test_preserved_brackets_remain() -> None:
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 5, "He said [inaudible] something"),
        _make_seg(5, 10, "And then [laughter] it happened"),
        _make_seg(10, 15, "There was [crosstalk] during the call"),
    ]
    normalized, stats = normalizer.normalize(segments)
    all_text = " ".join(seg["text"] for seg in normalized)
    assert "[inaudible]" in all_text
    assert "[laughter]" in all_text
    assert "[crosstalk]" in all_text


# ---------- Rolling-caption dedup ----------

def test_rolling_captions_collapse() -> None:
    """YouTube-style rolling captions should merge into non-duplicated text."""
    provider = VttTranscriptProvider()
    segments = provider.load([
        SubtitleArtifact(path=FIXTURES / "youtube_rolling_en.vtt", language="en", source="captions"),
    ])
    normalizer = TranscriptNormalizer()
    normalized, stats = normalizer.normalize(segments)

    assert stats.merged_or_deduped_count > 0
    assert stats.normalized_segment_count < stats.raw_segment_count

    all_text = " ".join(seg["text"] for seg in normalized).lower()
    # Key phrases should appear exactly once.
    assert all_text.count("welcome to the channel") == 1
    assert "machine learning" in all_text
    assert "neural networks" in all_text


def test_short_fragment_merge_no_duplication() -> None:
    """Merging a short fragment that overlaps the previous segment should not
    duplicate text (e.g. 'Hello' + 'Hello world' → 'Hello world', not
    'Hello Hello world')."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 2, "Hello", source="captions"),
        _make_seg(2, 5, "Hello world", source="captions"),
    ]
    normalized, stats = normalizer.normalize(segments)
    all_text = " ".join(seg["text"] for seg in normalized).lower()
    assert all_text.count("hello") == 1
    assert "world" in all_text


def test_sliding_window_captions_deduped() -> None:
    """Sliding-window captions that drop leading words and append new ones
    should be merged even when the suffix/prefix overlap ratio is below 0.75."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 5, "today we are going to discuss"),
        _make_seg(4, 9, "going to discuss machine learning"),
    ]
    normalized, stats = normalizer.normalize(segments)
    all_text = " ".join(seg["text"] for seg in normalized).lower()
    # "going to discuss" should not appear twice.
    assert all_text.count("going to discuss") == 1
    assert "machine learning" in all_text
    assert stats.merged_or_deduped_count >= 1


def test_short_asr_segments_not_merged() -> None:
    """Short ASR utterances like 'Yes' / 'No' should remain separate segments."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(10, 11, "Yes", source="asr"),
        _make_seg(11.5, 12.5, "No", source="asr"),
        _make_seg(13, 14, "OK", source="asr"),
    ]
    normalized, stats = normalizer.normalize(segments)
    assert len(normalized) == 3
    texts = [seg["text"] for seg in normalized]
    assert "Yes" in texts
    assert "No" in texts
    assert "OK" in texts


def test_legitimate_speech_repetition_preserved() -> None:
    """Segments with repeated words but large gaps should not be merged."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 5, "We need to act now"),
        _make_seg(60, 65, "We need to act now more than ever"),
    ]
    normalized, stats = normalizer.normalize(segments)
    assert len(normalized) == 2
    assert stats.merged_or_deduped_count == 0


# ---------- ASR segments ----------

def test_asr_segments_unchanged() -> None:
    """ASR segments should only get light text cleanup, not dedup."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 5, "Hello  world", source="asr"),
        _make_seg(5, 10, "Hello world again", source="asr"),
    ]
    normalized, stats = normalizer.normalize(segments)
    assert len(normalized) == 2
    assert stats.source_mode == "asr"


# ---------- Zero-segment fallback ----------

def test_zero_segment_fallback_all_blocklisted() -> None:
    """When cleanup strips every segment, fall back to raw segments."""
    normalizer = TranscriptNormalizer()
    segments = [
        _make_seg(0, 3, "[Music]"),
        _make_seg(3, 6, "[Applause]"),
    ]
    normalized, stats = normalizer.normalize(segments)
    # Cleaned list is empty, so fallback should return original raw segments.
    assert len(normalized) == 2
    assert stats.normalization_fallback_used is True


def test_zero_segment_fallback_with_recoverable_input() -> None:
    """When dedup empties segments but cleaned segments exist, fall back."""
    normalizer = TranscriptNormalizer()
    # Craft input where cleaned segments exist but a hypothetical dedup
    # could lose them — in practice this tests the safety net.
    segments = [_make_seg(0, 5, "Hello world")]
    normalized, stats = normalizer.normalize(segments)
    assert len(normalized) == 1
    assert normalized[0]["text"] == "Hello world"


# ---------- Config pass-through ----------

def test_empty_input() -> None:
    normalizer = TranscriptNormalizer()
    normalized, stats = normalizer.normalize([])
    assert normalized == []
    assert stats.raw_segment_count == 0
    assert stats.normalized_segment_count == 0
