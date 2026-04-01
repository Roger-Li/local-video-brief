from __future__ import annotations

from backend.app.schemas.jobs import JobResultResponse, TranscriptStats


def test_transcript_stats_in_result_schema() -> None:
    """TranscriptStats should be accepted as a top-level field."""
    stats = TranscriptStats(
        raw_segment_count=100,
        normalized_segment_count=60,
        cleaned_markup_count=5,
        merged_or_deduped_count=35,
        normalization_applied=True,
        normalization_fallback_used=False,
        source_mode="captions",
    )
    result = JobResultResponse(
        job_id="test-1",
        status="completed",
        source_metadata={"title": "Test"},
        transcript_segments=[],
        chapters=[],
        overall_summary={"summary_en": "", "summary_zh": "", "highlights": []},
        artifacts={},
        transcript_stats=stats,
    )
    assert result.transcript_stats is not None
    assert result.transcript_stats.raw_segment_count == 100
    assert result.transcript_stats.normalized_segment_count == 60
    assert result.transcript_stats.source_mode == "captions"


def test_result_schema_without_transcript_stats() -> None:
    """transcript_stats should be optional for backward compat."""
    result = JobResultResponse(
        job_id="test-2",
        status="completed",
        source_metadata={},
        transcript_segments=[],
        chapters=[],
        overall_summary={"summary_en": "", "summary_zh": "", "highlights": []},
        artifacts={},
    )
    assert result.transcript_stats is None
