from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from backend.app.models.job import JobRecord
from backend.app.schemas.jobs import (
    CreateJobRequest,
    CreateJobResponse,
    JobListResponse,
    JobResultResponse,
    JobStatusResponse,
    TranscriptStats,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_status_response(job: JobRecord) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.id,
        url=job.url,
        status=job.status,
        progress_stage=job.progress_stage,
        provider=job.provider,
        detected_language=job.detected_language,
        error=job.error,
        options=job.options or None,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("", response_model=CreateJobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: CreateJobRequest, request: Request) -> CreateJobResponse:
    repository = request.app.state.job_repository
    options_dict = payload.options.model_dump(exclude_none=True) if payload.options else {}
    job = repository.create_job(
        url=str(payload.url),
        output_languages=payload.output_languages,
        mode=payload.mode,
        options=options_dict,
    )
    return CreateJobResponse(job_id=job.id, status=job.status)


@router.get("", response_model=JobListResponse)
def list_jobs(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> JobListResponse:
    repository = request.app.state.job_repository
    jobs = repository.list_recent_jobs(limit=limit)
    return JobListResponse(jobs=[_to_status_response(job) for job in jobs])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, request: Request) -> JobStatusResponse:
    repository = request.app.state.job_repository
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_status_response(job)


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, request: Request) -> JobResultResponse:
    repository = request.app.state.job_repository
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != "completed" or not job.result_payload:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job result is not ready")
    raw_stats = (job.artifacts or {}).get("transcript_stats")
    transcript_stats = TranscriptStats(**raw_stats) if raw_stats else None

    return JobResultResponse(
        job_id=job.id,
        status=job.status,
        source_metadata=job.source_metadata or {},
        transcript_segments=job.transcript_segments,
        chapters=job.result_payload.get("chapters", []),
        overall_summary=job.result_payload.get(
            "overall_summary",
            {"summary_en": "", "summary_zh": "", "highlights": []},
        ),
        artifacts=job.artifacts,
        transcript_stats=transcript_stats,
        study_pack=job.result_payload.get("study_pack"),
        raw_summary_text=job.result_payload.get("raw_summary_text"),
    )
