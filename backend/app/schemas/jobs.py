from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl
from typing import Any, Dict, List, Optional


class CreateJobRequest(BaseModel):
    url: HttpUrl
    output_languages: List[str] = Field(default_factory=lambda: ["en", "zh-CN"])
    mode: str = "captions_first"


class CreateJobResponse(BaseModel):
    job_id: str
    status: str


class TranscriptSegment(BaseModel):
    start_s: float
    end_s: float
    text: str
    language: str
    source: str
    confidence: Optional[float] = None


class ChapterSummary(BaseModel):
    start_s: float
    end_s: float
    title: str
    summary_en: str
    summary_zh: str
    key_points: List[str]


class OverallSummary(BaseModel):
    summary_en: str
    summary_zh: str
    highlights: List[str]


class JobStatusResponse(BaseModel):
    job_id: str
    url: str
    status: str
    progress_stage: str
    provider: Optional[str] = None
    detected_language: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class TranscriptStats(BaseModel):
    raw_segment_count: int = 0
    normalized_segment_count: int = 0
    cleaned_markup_count: int = 0
    merged_or_deduped_count: int = 0
    normalization_applied: bool = True
    normalization_fallback_used: bool = False
    source_mode: str = "captions"


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    source_metadata: Dict[str, Any]
    transcript_segments: List[TranscriptSegment]
    chapters: List[ChapterSummary]
    overall_summary: OverallSummary
    artifacts: Dict[str, Any]
    transcript_stats: Optional[TranscriptStats] = None
