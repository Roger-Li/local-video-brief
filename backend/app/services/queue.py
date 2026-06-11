from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from backend.app.core.config import Settings
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.pipeline import VideoSummaryPipeline

logger = logging.getLogger(__name__)


class JobQueueService:
    def __init__(self, settings: Settings, repository: JobRepository, pipeline: VideoSummaryPipeline) -> None:
        self.settings = settings
        self.repository = repository
        self.pipeline = pipeline
        self._tasks: list[asyncio.Task] = []
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

    async def _worker_loop(self, worker_index: int = 0) -> None:
        while not self._stopped.is_set():
            job = await asyncio.to_thread(self.repository.claim_next_queued_job)
            if job is None:
                await asyncio.sleep(self.settings.worker_poll_interval)
                continue
            try:
                await asyncio.to_thread(self.pipeline.process_job, job.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The pipeline marks job failures itself; anything escaping it
                # must not kill the worker task or the queue stalls forever.
                logger.exception("worker=%d process_job crashed for job %s", worker_index, job.id)
