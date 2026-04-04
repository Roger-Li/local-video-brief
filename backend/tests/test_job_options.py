from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, resolve_job_setting
from backend.app.db.database import initialize_database
from backend.app.main import app
from backend.app.repositories.job_repository import JobRepository
from backend.app.schemas.jobs import CreateJobRequest, JobOptions, JobStatusResponse


# --- resolve_job_setting ---

def test_resolve_job_setting_uses_override() -> None:
    settings = Settings()
    result = resolve_job_setting({"enable_study_pack": True}, "enable_study_pack", settings)
    assert result is True


def test_resolve_job_setting_falls_back_to_global() -> None:
    settings = Settings()
    result = resolve_job_setting({}, "enable_study_pack", settings)
    assert result == settings.enable_study_pack


def test_resolve_job_setting_empty_options() -> None:
    settings = Settings()
    result = resolve_job_setting({}, "enable_transcript_normalization", settings)
    assert result == settings.enable_transcript_normalization


def test_resolve_job_setting_false_override() -> None:
    settings = Settings()
    result = resolve_job_setting({"enable_transcript_normalization": False}, "enable_transcript_normalization", settings)
    assert result is False


# --- JobOptions schema ---

def test_job_options_all_none_by_default() -> None:
    opts = JobOptions()
    assert opts.enable_study_pack is None
    assert opts.enable_transcript_normalization is None


def test_job_options_exclude_none() -> None:
    opts = JobOptions(enable_study_pack=True)
    dumped = opts.model_dump(exclude_none=True)
    assert dumped == {"enable_study_pack": True}
    assert "enable_transcript_normalization" not in dumped


def test_create_job_request_without_options() -> None:
    req = CreateJobRequest(url="https://www.youtube.com/watch?v=test")
    assert req.options is None


def test_create_job_request_with_options() -> None:
    req = CreateJobRequest(
        url="https://www.youtube.com/watch?v=test",
        options=JobOptions(enable_study_pack=True),
    )
    assert req.options is not None
    assert req.options.enable_study_pack is True


# --- Repository ---

def _make_repo() -> JobRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_database(conn)
    return JobRepository(conn)


def test_create_job_without_options_defaults_to_empty() -> None:
    repo = _make_repo()
    job = repo.create_job(url="https://example.com", output_languages=["en"], mode="captions_first")
    assert job.options == {}


def test_create_job_with_options_stores_correctly() -> None:
    repo = _make_repo()
    job = repo.create_job(
        url="https://example.com",
        output_languages=["en"],
        mode="captions_first",
        options={"enable_study_pack": True},
    )
    assert job.options == {"enable_study_pack": True}
    fetched = repo.get_job(job.id)
    assert fetched is not None
    assert fetched.options == {"enable_study_pack": True}


def test_create_job_with_normalization_option() -> None:
    repo = _make_repo()
    job = repo.create_job(
        url="https://example.com",
        output_languages=["en"],
        mode="captions_first",
        options={"enable_transcript_normalization": False},
    )
    fetched = repo.get_job(job.id)
    assert fetched is not None
    assert fetched.options == {"enable_transcript_normalization": False}


# --- API ---

def test_api_create_job_without_options_returns_201() -> None:
    with TestClient(app) as client:
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "output_languages": ["en"],
            "mode": "captions_first",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data


def test_api_create_job_with_options_returns_201() -> None:
    with TestClient(app) as client:
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "output_languages": ["en"],
            "mode": "captions_first",
            "options": {"enable_study_pack": True},
        })
        assert resp.status_code == 201


def test_get_job_status_includes_options() -> None:
    with TestClient(app) as client:
        create_resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "output_languages": ["en"],
            "mode": "captions_first",
            "options": {"enable_study_pack": True},
        })
        job_id = create_resp.json()["job_id"]
        status_resp = client.get(f"/jobs/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["options"] == {"enable_study_pack": True}


def test_get_job_status_options_null_when_empty() -> None:
    with TestClient(app) as client:
        create_resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "output_languages": ["en"],
            "mode": "captions_first",
        })
        job_id = create_resp.json()["job_id"]
        status_resp = client.get(f"/jobs/{job_id}")
        data = status_resp.json()
        # Empty dict from repository → None echoed in response
        assert data.get("options") is None


# --- JobStatusResponse schema ---

def test_job_status_response_accepts_options() -> None:
    resp = JobStatusResponse(
        job_id="test",
        url="https://example.com",
        status="queued",
        progress_stage="queued",
        options={"enable_study_pack": True},
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert resp.options == {"enable_study_pack": True}


def test_job_status_response_options_default_none() -> None:
    resp = JobStatusResponse(
        job_id="test",
        url="https://example.com",
        status="queued",
        progress_stage="queued",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert resp.options is None
