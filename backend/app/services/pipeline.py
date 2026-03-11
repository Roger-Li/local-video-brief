from __future__ import annotations

from backend.app.models.job import JobStatus
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.asr import MlxWhisperAsrService
from backend.app.services.chaptering import HeuristicChapterer
from backend.app.services.interfaces import SummaryGenerator, TranscriptProvider, VideoSourceClient
from backend.app.utils.text import detect_language


class VideoSummaryPipeline:
    def __init__(
        self,
        repository: JobRepository,
        video_source: VideoSourceClient,
        transcript_provider: TranscriptProvider,
        asr_service: MlxWhisperAsrService,
        chapterer: HeuristicChapterer,
        summary_generator: SummaryGenerator,
    ) -> None:
        self.repository = repository
        self.video_source = video_source
        self.transcript_provider = transcript_provider
        self.asr_service = asr_service
        self.chapterer = chapterer
        self.summary_generator = summary_generator

    def process_job(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")

        try:
            inspection = self.video_source.inspect(job.url)
            self.repository.update_job(
                job_id,
                provider=inspection.provider,
                source_metadata=inspection.metadata,
                progress_stage="fetching_captions",
            )

            subtitles = self.video_source.fetch_captions(job_id, job.url, job.output_languages)
            caption_artifacts = {"subtitle_paths": [str(subtitle.path) for subtitle in subtitles]}
            self.repository.update_job(job_id, artifacts=caption_artifacts)
            transcript_segments = self.transcript_provider.load(subtitles)

            if not self._captions_are_usable(transcript_segments):
                self.repository.update_job(job_id, progress_stage="downloading_audio")
                audio = self.video_source.download_audio(job_id, job.url)
                latest_job = self.repository.get_job(job_id)
                current_artifacts = latest_job.artifacts if latest_job else {}
                self.repository.update_job(
                    job_id,
                    progress_stage="transcribing_audio",
                    artifacts={**current_artifacts, "audio_path": str(audio.path)},
                )
                transcript_segments = self.asr_service.transcribe(audio.path)

            self.repository.update_job(job_id, progress_stage="normalizing_transcript")
            detected_language = self._detect_language(transcript_segments)
            self.repository.update_job(
                job_id,
                transcript_segments=transcript_segments,
                detected_language=detected_language,
                progress_stage="chaptering",
            )

            chapters = self.chapterer.build_chapters(transcript_segments)
            self.repository.update_job(job_id, progress_stage="summarizing")
            latest = self.repository.get_job(job_id)
            source_metadata = latest.source_metadata if latest else {}
            summary_payload = self.summary_generator.summarize(
                source_metadata=source_metadata or {},
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=job.output_languages,
            )
            self.repository.update_job(
                job_id,
                status=JobStatus.COMPLETED,
                progress_stage="completed",
                result_payload=summary_payload,
            )
        except Exception as exc:
            self.repository.update_job(
                job_id,
                status=JobStatus.FAILED,
                progress_stage="failed",
                error=str(exc),
            )

    def _captions_are_usable(self, transcript_segments: list[dict]) -> bool:
        character_count = sum(len(segment["text"]) for segment in transcript_segments)
        return len(transcript_segments) >= 3 and character_count >= 120

    def _detect_language(self, transcript_segments: list[dict]) -> str:
        combined = " ".join(segment["text"] for segment in transcript_segments[:50])
        return detect_language(combined)
