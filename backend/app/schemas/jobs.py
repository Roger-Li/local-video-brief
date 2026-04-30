from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Any, Dict, List, Optional

from backend.app.core.style_presets import STYLE_PRESETS


_VALID_PROVIDER_OVERRIDES = ("omlx", "deepseek")
_VALID_DEEPSEEK_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")


class JobOptions(BaseModel):
    enable_study_pack: Optional[bool] = None
    enable_transcript_normalization: Optional[bool] = None
    focus_hint: Optional[str] = None
    style_preset: Optional[str] = None
    omlx_model_override: Optional[str] = None
    power_mode: Optional[bool] = None
    power_prompt: Optional[str] = None
    strategy_override: Optional[str] = None
    summarizer_provider_override: Optional[str] = None
    deepseek_model: Optional[str] = None

    @field_validator("style_preset")
    @classmethod
    def validate_style_preset(cls, v: str | None) -> str | None:
        if v is not None and v not in STYLE_PRESETS:
            raise ValueError(f"Unknown style preset: {v!r}. Must be one of: {', '.join(sorted(STYLE_PRESETS))}")
        return v

    @field_validator("summarizer_provider_override")
    @classmethod
    def validate_provider_override(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_PROVIDER_OVERRIDES:
            raise ValueError(
                "summarizer_provider_override must be one of "
                f"{', '.join(_VALID_PROVIDER_OVERRIDES)} (got {v!r})"
            )
        return v

    @field_validator("deepseek_model")
    @classmethod
    def validate_deepseek_model(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_DEEPSEEK_MODELS:
            raise ValueError(
                "deepseek_model must be one of "
                f"{', '.join(_VALID_DEEPSEEK_MODELS)} (got {v!r})"
            )
        return v

    @field_validator("focus_hint")
    @classmethod
    def validate_focus_hint(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 500:
                raise ValueError("focus_hint must be 500 characters or fewer")
            return v if v else None
        return v

    @field_validator("power_prompt")
    @classmethod
    def validate_power_prompt(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 2000:
                raise ValueError("power_prompt must be 2000 characters or fewer")
            return v if v else None
        return v

    @field_validator("strategy_override")
    @classmethod
    def validate_strategy_override(cls, v: str | None) -> str | None:
        if v is not None and v not in ("auto", "force_single_shot"):
            raise ValueError(f"strategy_override must be 'auto' or 'force_single_shot', got {v!r}")
        return v


class CreateJobRequest(BaseModel):
    url: HttpUrl
    output_languages: List[str] = Field(default_factory=lambda: ["en", "zh-CN"])
    mode: str = "captions_first"
    options: Optional[JobOptions] = None


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
    options: Optional[Dict[str, Any]] = None
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


class StudySection(BaseModel):
    chapter_index: int
    start_s: float
    end_s: float
    title: str
    summary_en: str
    summary_zh: str
    key_points: List[str]


class StudyPack(BaseModel):
    version: int = 1
    format: str = "lecture_study_guide"
    learning_objectives: List[str]
    sections: List[StudySection]
    final_takeaways: List[str]


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    source_metadata: Dict[str, Any]
    transcript_segments: List[TranscriptSegment]
    chapters: List[ChapterSummary]
    overall_summary: OverallSummary
    artifacts: Dict[str, Any]
    transcript_stats: Optional[TranscriptStats] = None
    study_pack: Optional[StudyPack] = None
    raw_summary_text: Optional[str] = None
