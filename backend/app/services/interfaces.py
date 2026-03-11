from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import Any, Dict, List


@dataclass
class SourceInspection:
    provider: str
    metadata: Dict[str, Any]


@dataclass
class SubtitleArtifact:
    path: Path
    language: str
    source: str


@dataclass
class AudioArtifact:
    path: Path
    format: str


class VideoSourceClient(Protocol):
    def inspect(self, url: str) -> SourceInspection: ...

    def fetch_captions(self, job_id: str, url: str, languages: List[str]) -> List[SubtitleArtifact]: ...

    def download_audio(self, job_id: str, url: str) -> AudioArtifact: ...


class TranscriptProvider(Protocol):
    def load(self, subtitles: List[SubtitleArtifact]) -> List[Dict[str, Any]]: ...


class AsrService(Protocol):
    def transcribe(self, audio_path: Path) -> List[Dict[str, Any]]: ...


class Chapterer(Protocol):
    def build_chapters(self, transcript_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]: ...


class SummaryGenerator(Protocol):
    def summarize(
        self,
        source_metadata: Dict[str, Any],
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]],
        output_languages: List[str],
    ) -> Dict[str, Any]: ...
