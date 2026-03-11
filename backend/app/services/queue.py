from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Optional

from backend.app.core.config import Settings
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.pipeline import VideoSummaryPipeline


class JobQueueService:
    def __init__(self, settings: Settings, repository: JobRepository, pipeline: VideoSummaryPipeline) -> None:
        self.settings = settings
        self.repository = repository
        self.pipeline = pipeline
        self._task = None  # type: Optional[asyncio.Task]
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self.repository.reset_running_jobs()
        self._stopped.clear()
        self._task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _worker_loop(self) -> None:
        while not self._stopped.is_set():
            job = await asyncio.to_thread(self.repository.claim_next_queued_job)
            if job is None:
                await asyncio.sleep(self.settings.worker_poll_interval)
                continue
            await asyncio.to_thread(self.pipeline.process_job, job.id)
