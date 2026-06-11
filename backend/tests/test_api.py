from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_create_job_and_fetch_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "output_languages": ["en", "zh-CN"],
                "mode": "captions_first",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "queued"

        status_response = client.get(f"/jobs/{payload['job_id']}")
        assert status_response.status_code == 200
        assert status_response.json()["job_id"] == payload["job_id"]


def test_list_jobs_endpoint_includes_created_job() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "output_languages": ["en"],
                "mode": "captions_first",
            },
        )
        job_id = response.json()["job_id"]

        list_response = client.get("/jobs")
        assert list_response.status_code == 200
        jobs = list_response.json()["jobs"]
        # Membership, not equality: the TestClient runs against the dev DB.
        match = next((job for job in jobs if job["job_id"] == job_id), None)
        assert match is not None
        assert match["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert {"status", "progress_stage", "created_at", "updated_at"} <= match.keys()


def test_list_jobs_endpoint_rejects_bad_limit() -> None:
    with TestClient(app) as client:
        assert client.get("/jobs?limit=0").status_code == 422
        assert client.get("/jobs?limit=999").status_code == 422
