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
