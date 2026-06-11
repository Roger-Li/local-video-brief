from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from backend.app.core.config import Settings
from backend.app.models.job import JobStatus
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.pipeline import VideoSummaryPipeline

logger = logging.getLogger(__name__)


class JobQueueService:
    def __init__(self, settings: Settings, repository: JobRepository, pipeline: VideoSummaryPipeline) -> None:
        self.settings = settings
        self.repository = repository
        self.pipeline = pipeline
        self._tasks: list[asyncio.Task] = []
        self._inflight: set[asyncio.Future] = set()
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self.repository.reset_running_jobs()
        self._stopped.clear()
        worker_count = self.settings.worker_concurrency
        logger.info("starting %d worker task(s)", worker_count)
        self._tasks = [
            asyncio.create_task(self._worker_loop(index)) for index in range(worker_count)
        ]

    async def stop(self) -> None:
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        # Drain pipeline threads that were mid-job when their worker was
        # cancelled — cancellation doesn't stop a to_thread thread, and the
        # database is closed right after stop() returns.
        inflight = [future for future in self._inflight if not future.done()]
        if inflight:
            logger.info("waiting for %d in-flight job(s) to finish", len(inflight))
            await asyncio.gather(*inflight, return_exceptions=True)

    async def _worker_loop(self, worker_index: int = 0) -> None:
        while not self._stopped.is_set():
            job = await asyncio.to_thread(self.repository.claim_next_queued_job)
            if job is None:
                await asyncio.sleep(self.settings.worker_poll_interval)
                continue
            inner = asyncio.ensure_future(asyncio.to_thread(self.pipeline.process_job, job.id))
            self._inflight.add(inner)
            inner.add_done_callback(self._inflight.discard)
            try:
                # Shielded so cancellation at shutdown interrupts the worker
                # without abandoning the thread; stop() awaits _inflight.
                await asyncio.shield(inner)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The pipeline marks its own failures; anything escaping it
                # would otherwise leave the job running forever and must not
                # kill the worker task.
                logger.exception("worker=%d process_job crashed for job %s", worker_index, job.id)
                self._mark_job_failed(job.id, exc)

    def _mark_job_failed(self, job_id: str, exc: Exception) -> None:
        try:
            self.repository.update_job(
                job_id,
                status=JobStatus.FAILED,
                progress_stage="failed",
                error=f"worker error: {exc}",
            )
        except Exception:
            logger.exception("could not mark job %s as failed", job_id)
