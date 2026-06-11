from __future__ import annotations

import asyncio
import sqlite3
import threading

import pytest

from backend.app.core.config import Settings
from backend.app.db.database import initialize_database
from backend.app.models.job import JobStatus
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.queue import JobQueueService


def _make_repo() -> JobRepository:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    initialize_database(conn)
    return JobRepository(conn)


def _make_settings(monkeypatch: pytest.MonkeyPatch, concurrency: str) -> Settings:
    monkeypatch.setenv("OVS_WORKER_CONCURRENCY", concurrency)
    monkeypatch.setenv("OVS_WORKER_POLL_INTERVAL", "0")
    return Settings()


def _create_jobs(repo: JobRepository, count: int) -> list[str]:
    return [
        repo.create_job(url=f"https://example.com/video-{i}", output_languages=["en"], mode="captions_first").id
        for i in range(count)
    ]


# --- claim_next_queued_job ---

def test_claim_marks_running_and_sets_stage() -> None:
    repo = _make_repo()
    created = _create_jobs(repo, 1)[0]
    claimed = repo.claim_next_queued_job()
    assert claimed is not None
    assert claimed.id == created
    assert claimed.status == JobStatus.RUNNING
    assert claimed.progress_stage == "inspecting_source"


def test_claim_returns_none_when_no_queued_jobs() -> None:
    repo = _make_repo()
    assert repo.claim_next_queued_job() is None


def test_claim_orders_by_created_at() -> None:
    repo = _make_repo()
    first, second = _create_jobs(repo, 2)
    assert repo.claim_next_queued_job().id == first
    assert repo.claim_next_queued_job().id == second
    assert repo.claim_next_queued_job() is None


def test_claim_is_atomic_under_concurrent_threads() -> None:
    repo = _make_repo()
    job_ids = _create_jobs(repo, 20)
    claimed: list[str] = []
    claimed_lock = threading.Lock()

    def worker() -> None:
        while True:
            job = repo.claim_next_queued_job()
            if job is None:
                return
            with claimed_lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(claimed) == len(job_ids), "every job claimed exactly once"
    assert sorted(claimed) == sorted(job_ids)


# --- list_recent_jobs ---

def test_list_recent_jobs_orders_newest_first() -> None:
    repo = _make_repo()
    ids = _create_jobs(repo, 3)
    listed = [job.id for job in repo.list_recent_jobs()]
    assert listed == list(reversed(ids))


def test_list_recent_jobs_respects_limit() -> None:
    repo = _make_repo()
    _create_jobs(repo, 5)
    assert len(repo.list_recent_jobs(limit=2)) == 2


# --- worker pool ---

class _BarrierPipeline:
    """Completes jobs only if `parties` of them are in flight simultaneously."""

    def __init__(self, repo: JobRepository, parties: int) -> None:
        self._repo = repo
        self._barrier = threading.Barrier(parties, timeout=10)

    def process_job(self, job_id: str) -> None:
        self._barrier.wait()
        self._repo.update_job(job_id, status=JobStatus.COMPLETED, progress_stage="completed")


class _FlakyPipeline:
    """Raises on the first job, completes the rest."""

    def __init__(self, repo: JobRepository) -> None:
        self._repo = repo
        self.calls = 0

    def process_job(self, job_id: str) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        self._repo.update_job(job_id, status=JobStatus.COMPLETED, progress_stage="completed")


async def _wait_until(predicate, attempts: int = 200, delay: float = 0.05) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(delay)
    raise AssertionError("condition not reached within timeout")


def test_worker_pool_runs_two_jobs_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(monkeypatch, "2")
    repo = _make_repo()
    _create_jobs(repo, 2)
    queue = JobQueueService(settings, repo, _BarrierPipeline(repo, parties=2))

    async def scenario() -> None:
        await queue.start()
        try:
            # The barrier only releases if both jobs are processed at the same
            # time, so completion proves true overlap.
            await _wait_until(
                lambda: all(job.status == JobStatus.COMPLETED for job in repo.list_recent_jobs())
            )
        finally:
            await queue.stop()

    asyncio.run(scenario())


def test_worker_pool_spawns_configured_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(monkeypatch, "3")
    repo = _make_repo()
    queue = JobQueueService(settings, repo, _BarrierPipeline(repo, parties=1))

    async def scenario() -> None:
        await queue.start()
        assert len(queue._tasks) == 3
        await queue.stop()

    asyncio.run(scenario())


def test_stop_cancels_all_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(monkeypatch, "2")
    repo = _make_repo()
    queue = JobQueueService(settings, repo, _BarrierPipeline(repo, parties=1))

    async def scenario() -> None:
        await queue.start()
        tasks = list(queue._tasks)
        await queue.stop()
        assert queue._tasks == []
        assert all(task.done() for task in tasks)

    asyncio.run(scenario())


def test_worker_survives_pipeline_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(monkeypatch, "1")
    repo = _make_repo()
    first, second = _create_jobs(repo, 2)
    pipeline = _FlakyPipeline(repo)
    queue = JobQueueService(settings, repo, pipeline)

    async def scenario() -> None:
        await queue.start()
        try:
            await _wait_until(lambda: repo.get_job(second).status == JobStatus.COMPLETED)
        finally:
            await queue.stop()

    asyncio.run(scenario())
    # The crashing first job stays claimed (the real pipeline marks its own
    # failures); the worker kept running and finished the second job.
    assert repo.get_job(first).status == JobStatus.RUNNING
    assert pipeline.calls == 2
