from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.jobs import router as jobs_router
from backend.app.core.config import get_settings
from backend.app.db.database import get_connection, initialize_database
from backend.app.repositories.job_repository import JobRepository
from backend.app.services.asr import MlxWhisperAsrService
from backend.app.services.chaptering import HeuristicChapterer
from backend.app.services.pipeline import VideoSummaryPipeline
from backend.app.services.queue import JobQueueService
from backend.app.services.storage import StorageService
from backend.app.services.summarizer import MlxQwenSummaryGenerator
from backend.app.services.transcript import VttTranscriptProvider
from backend.app.services.video_source import YtDlpVideoSourceClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    connection = get_connection(settings.database_path)
    initialize_database(connection)

    storage = StorageService(settings.artifact_root)
    repository = JobRepository(connection)
    video_source = YtDlpVideoSourceClient(storage, settings.preferred_caption_languages)
    transcript_provider = VttTranscriptProvider()
    asr_service = MlxWhisperAsrService(settings)
    chapterer = HeuristicChapterer(settings)
    summary_generator = MlxQwenSummaryGenerator(settings)
    pipeline = VideoSummaryPipeline(
        repository=repository,
        video_source=video_source,
        transcript_provider=transcript_provider,
        asr_service=asr_service,
        chapterer=chapterer,
        summary_generator=summary_generator,
    )
    queue = JobQueueService(settings, repository, pipeline)

    app.state.settings = settings
    app.state.connection = connection
    app.state.job_repository = repository
    app.state.queue = queue

    await queue.start()
    try:
        yield
    finally:
        await queue.stop()
        connection.close()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(jobs_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}
