from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Dict, List, Optional

from backend.app.services.interfaces import AudioArtifact, SourceInspection, SubtitleArtifact
from backend.app.services.storage import StorageService


class VideoSourceError(RuntimeError):
    pass


class YtDlpVideoSourceClient:
    def __init__(self, storage: StorageService, preferred_caption_languages: List[str]) -> None:
        self.storage = storage
        self.preferred_caption_languages = preferred_caption_languages

    def inspect(self, url: str) -> SourceInspection:
        result = self._run_command(["yt-dlp", "--dump-single-json", "--no-warnings", url])
        data = json.loads(result.stdout)
        return SourceInspection(provider=data.get("extractor_key", "unknown"), metadata=data)

    def fetch_captions(self, job_id: str, url: str, languages: List[str]) -> List[SubtitleArtifact]:
        job_dir = self.storage.job_dir(job_id)
        output_template = str(job_dir / "source.%(ext)s")
        ordered_languages = self._ordered_caption_languages(languages)
        for family_name, family_languages in ordered_languages:
            for language in family_languages:
                existing = self._find_subtitles_for_family(job_dir, family_name)
                if existing:
                    return existing
                self._attempt_caption_download(output_template, url, language)
                existing = self._find_subtitles_for_family(job_dir, family_name)
                if existing:
                    return existing
        return self._list_subtitle_artifacts(job_dir)

    def download_audio(self, job_id: str, url: str) -> AudioArtifact:
        job_dir = self.storage.job_dir(job_id)
        output_template = str(job_dir / "audio.%(ext)s")
        self._run_command(
            [
                "yt-dlp",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--output",
                output_template,
                url,
            ]
        )
        matches = sorted(job_dir.glob("audio.*"))
        if not matches:
            raise VideoSourceError("Audio download succeeded but no output file was found.")
        return AudioArtifact(path=matches[0], format=matches[0].suffix.lstrip("."))

    def _run_command(self, args: List[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise VideoSourceError(f"Required command is not installed: {args[0]}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "Unknown extractor failure"
            raise VideoSourceError(stderr) from exc

    def _attempt_caption_download(self, output_template: str, url: str, language: str) -> None:
        try:
            self._run_command(
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-format",
                    "vtt",
                    "--sub-langs",
                    language,
                    "--output",
                    output_template,
                    url,
                ]
            )
        except VideoSourceError:
            return

    def _ordered_caption_languages(self, languages: List[str]) -> List[tuple[str, List[str]]]:
        combined_languages = list(dict.fromkeys(languages + self.preferred_caption_languages))
        english = [language for language in combined_languages if self._language_family(language) == "english"]
        chinese = [language for language in combined_languages if self._language_family(language) == "chinese"]
        other = [language for language in combined_languages if self._language_family(language) == "other"]
        groups: List[tuple[str, List[str]]] = []
        if english:
            groups.append(("english", english))
        if chinese:
            groups.append(("chinese", chinese))
        if other:
            groups.append(("other", other))
        return groups

    def _find_subtitles_for_family(self, job_dir: Path, family_name: str) -> List[SubtitleArtifact]:
        matching_paths = []
        for path in sorted(job_dir.glob("*.vtt")):
            language = self._language_from_subtitle_path(path)
            if family_name == "other":
                if self._language_family(language) == "other":
                    matching_paths.append(path)
            elif self._language_family(language) == family_name:
                matching_paths.append(path)
        return [SubtitleArtifact(path=path, language=self._language_from_subtitle_path(path), source="captions") for path in matching_paths]

    def _list_subtitle_artifacts(self, job_dir: Path) -> List[SubtitleArtifact]:
        artifacts: List[SubtitleArtifact] = []
        for path in sorted(job_dir.glob("*.vtt")):
            artifacts.append(
                SubtitleArtifact(
                    path=path,
                    language=self._language_from_subtitle_path(path),
                    source="captions",
                )
            )
        return artifacts

    def _language_from_subtitle_path(self, path: Path) -> str:
        return path.stem.split(".")[-1] if "." in path.stem else "unknown"

    def _language_family(self, language: str) -> str:
        normalized = language.lower()
        if normalized.startswith("en"):
            return "english"
        if normalized.startswith("zh"):
            return "chinese"
        return "other"
