from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from backend.app.core.config import Settings, resolve_job_setting
from backend.app.models.job import JobStatus

logger = logging.getLogger(__name__)
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.asr import MlxWhisperAsrService
from backend.app.services.chaptering import HeuristicChapterer
from backend.app.services.interfaces import SummaryGenerator, TranscriptProvider, VideoSourceClient
from backend.app.services.normalizer import TranscriptNormalizer
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
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository
        self.video_source = video_source
        self.transcript_provider = transcript_provider
        self.asr_service = asr_service
        self.chapterer = chapterer
        self.summary_generator = summary_generator
        self._settings = settings or Settings()
        self._normalizer = TranscriptNormalizer()

    def process_job(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")

        job_t0 = time.perf_counter()
        logger.info("pipeline START job=%s url=%s", job_id, job.url)

        job_options = getattr(job, "options", None) or {}
        enable_normalization = resolve_job_setting(job_options, "enable_transcript_normalization", self._settings)
        enable_study_pack = resolve_job_setting(job_options, "enable_study_pack", self._settings)

        try:
            logger.info("stage=inspecting_source job=%s", job_id)
            t0 = time.perf_counter()
            inspection = self.video_source.inspect(job.url)
            logger.info(
                "stage=inspecting_source DONE job=%s provider=%s title=%s (%.1fs)",
                job_id, inspection.provider, inspection.metadata.get("title", "?"), time.perf_counter() - t0,
            )
            self.repository.update_job(
                job_id,
                provider=inspection.provider,
                source_metadata=inspection.metadata,
                progress_stage="fetching_captions",
            )

            logger.info("stage=fetching_captions job=%s", job_id)
            t0 = time.perf_counter()
            subtitles = self.video_source.fetch_captions(job_id, job.url, job.output_languages)
            logger.info(
                "stage=fetching_captions DONE job=%s subtitle_files=%d (%.1fs)",
                job_id, len(subtitles), time.perf_counter() - t0,
            )
            caption_artifacts = {"subtitle_paths": [str(subtitle.path) for subtitle in subtitles]}
            self.repository.update_job(job_id, artifacts=caption_artifacts)
            transcript_segments = self.transcript_provider.load(subtitles)
            logger.info("caption segments loaded: %d segments, %d chars",
                        len(transcript_segments),
                        sum(len(s["text"]) for s in transcript_segments))

            if not self._captions_are_usable(transcript_segments):
                logger.info("captions not usable, falling back to ASR")
                self.repository.update_job(job_id, progress_stage="downloading_audio")
                logger.info("stage=downloading_audio job=%s", job_id)
                t0 = time.perf_counter()
                audio = self.video_source.download_audio(job_id, job.url)
                logger.info("stage=downloading_audio DONE job=%s path=%s (%.1fs)",
                            job_id, audio.path, time.perf_counter() - t0)
                latest_job = self.repository.get_job(job_id)
                current_artifacts = latest_job.artifacts if latest_job else {}
                self.repository.update_job(
                    job_id,
                    progress_stage="transcribing_audio",
                    artifacts={**current_artifacts, "audio_path": str(audio.path)},
                )
                logger.info("stage=transcribing_audio job=%s model=%s", job_id, self.asr_service.settings.asr_model)
                t0 = time.perf_counter()
                transcript_segments = self.asr_service.transcribe(audio.path)
                logger.info("stage=transcribing_audio DONE job=%s segments=%d (%.1fs)",
                            job_id, len(transcript_segments), time.perf_counter() - t0)

            self.repository.update_job(job_id, progress_stage="normalizing_transcript")
            detected_language = self._detect_language(transcript_segments)
            logger.info("detected_language=%s total_segments=%d", detected_language, len(transcript_segments))

            raw_segments = transcript_segments
            if enable_normalization:
                logger.info("stage=normalizing_transcript job=%s raw_segments=%d", job_id, len(raw_segments))
                t0 = time.perf_counter()
                transcript_segments, norm_stats = self._normalizer.normalize(raw_segments)
                logger.info(
                    "stage=normalizing_transcript DONE job=%s normalized=%d deduped=%d markup=%d fallback=%s (%.1fs)",
                    job_id, norm_stats.normalized_segment_count,
                    norm_stats.merged_or_deduped_count, norm_stats.cleaned_markup_count,
                    norm_stats.normalization_fallback_used, time.perf_counter() - t0,
                )
            else:
                from backend.app.services.normalizer import NormalizationStats
                norm_stats = NormalizationStats(
                    raw_segment_count=len(raw_segments),
                    normalized_segment_count=len(raw_segments),
                    normalization_applied=False,
                    source_mode=self._detect_source_mode(raw_segments),
                )

            # Persist raw and normalized transcript artifacts.
            latest_job = self.repository.get_job(job_id)
            current_artifacts = latest_job.artifacts if latest_job else {}
            artifact_root = self._settings.artifact_root / job_id
            artifact_root.mkdir(parents=True, exist_ok=True)
            raw_path = artifact_root / "transcript_raw.json"
            norm_path = artifact_root / "transcript_normalized.json"
            raw_path.write_text(json.dumps(raw_segments, ensure_ascii=False), encoding="utf-8")
            norm_path.write_text(json.dumps(transcript_segments, ensure_ascii=False), encoding="utf-8")
            current_artifacts["transcript_raw_path"] = str(raw_path)
            current_artifacts["transcript_normalized_path"] = str(norm_path)

            transcript_stats = {
                "raw_segment_count": norm_stats.raw_segment_count,
                "normalized_segment_count": norm_stats.normalized_segment_count,
                "cleaned_markup_count": norm_stats.cleaned_markup_count,
                "merged_or_deduped_count": norm_stats.merged_or_deduped_count,
                "normalization_applied": norm_stats.normalization_applied,
                "normalization_fallback_used": norm_stats.normalization_fallback_used,
                "source_mode": norm_stats.source_mode,
            }
            current_artifacts["transcript_stats"] = transcript_stats

            self.repository.update_job(
                job_id,
                transcript_segments=transcript_segments,
                detected_language=detected_language,
                artifacts=current_artifacts,
                progress_stage="chaptering",
            )

            logger.info("stage=chaptering job=%s", job_id)
            chapters = self.chapterer.build_chapters(transcript_segments)
            logger.info("stage=chaptering DONE job=%s chapters=%d", job_id, len(chapters))

            self.repository.update_job(job_id, progress_stage="summarizing")
            logger.info("stage=summarizing job=%s", job_id)
            t0 = time.perf_counter()
            latest = self.repository.get_job(job_id)
            source_metadata = latest.source_metadata if latest else {}
            summary_artifact_dir = self._settings.artifact_root / job_id
            summary_payload = self.summary_generator.summarize(
                source_metadata=source_metadata or {},
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=job.output_languages,
                artifact_dir=summary_artifact_dir,
                progress_callback=lambda stage: self.repository.update_job(job_id, progress_stage=stage),
            )
            logger.info("stage=summarizing DONE job=%s (%.1fs)", job_id, time.perf_counter() - t0)

            # Study pack generation (optional, non-fatal).
            if enable_study_pack:
                self.repository.update_job(job_id, progress_stage="generating_study_pack")
                logger.info("stage=generating_study_pack job=%s", job_id)
                t0 = time.perf_counter()
                try:
                    from backend.app.services.study_pack import StudyPackGenerator, render_study_guide_markdown
                    sp_gen = StudyPackGenerator(self._settings)
                    study_pack_data = sp_gen.generate(
                        source_metadata=source_metadata or {},
                        chapters=chapters,
                        chapter_summaries=summary_payload.get("chapters", []),
                        overall_summary=summary_payload.get("overall_summary", {}),
                        artifact_dir=summary_artifact_dir,
                    )
                    if study_pack_data is not None:
                        sp_path = artifact_root / "study_pack.json"
                        sp_path.write_text(
                            json.dumps(study_pack_data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        md_content = render_study_guide_markdown(
                            study_pack_data, source_metadata or {},
                        )
                        md_path = artifact_root / "study_guide.md"
                        md_path.write_text(md_content, encoding="utf-8")
                        latest_job = self.repository.get_job(job_id)
                        current_artifacts = latest_job.artifacts if latest_job else {}
                        current_artifacts["study_pack_path"] = str(sp_path)
                        current_artifacts["study_guide_path"] = str(md_path)
                        self.repository.update_job(job_id, artifacts=current_artifacts)
                        summary_payload["study_pack"] = study_pack_data
                    logger.info(
                        "stage=generating_study_pack DONE job=%s (%.1fs)",
                        job_id, time.perf_counter() - t0,
                    )
                except Exception as exc:
                    logger.warning("study_pack generation failed (non-fatal): %s", exc)

            self.repository.update_job(
                job_id,
                status=JobStatus.COMPLETED,
                progress_stage="completed",
                result_payload=summary_payload,
            )
            logger.info("pipeline COMPLETED job=%s total_time=%.1fs", job_id, time.perf_counter() - job_t0)
        except Exception as exc:
            logger.error("pipeline FAILED job=%s error=%s (%.1fs)", job_id, exc, time.perf_counter() - job_t0)
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

    @staticmethod
    def _detect_source_mode(segments: list[dict]) -> str:
        sources = {seg.get("source", "captions") for seg in segments}
        if sources == {"captions"}:
            return "captions"
        if sources == {"asr"}:
            return "asr"
        return "mixed"
