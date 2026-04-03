from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    id: str
    url: str
    mode: str
    output_languages: List[str]
    status: str = JobStatus.QUEUED
    progress_stage: str = JobStatus.QUEUED
    provider: Optional[str] = None
    detected_language: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    transcript_segments: List[Dict[str, Any]] = field(default_factory=list)
    result_payload: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
