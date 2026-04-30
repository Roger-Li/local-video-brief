from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, resolve_job_setting
from backend.app.db.database import initialize_database
from backend.app.main import app
from backend.app.repositories.job_repository import JobRepository
import pytest
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


# --- Prompt option schema validation ---

def test_focus_hint_accepted_within_limit() -> None:
    opts = JobOptions(focus_hint="Emphasize math proofs")
    assert opts.focus_hint == "Emphasize math proofs"


def test_focus_hint_rejected_over_500_chars() -> None:
    with pytest.raises(Exception):
        JobOptions(focus_hint="x" * 501)


def test_focus_hint_strips_whitespace() -> None:
    opts = JobOptions(focus_hint="  test hint  ")
    assert opts.focus_hint == "test hint"


def test_focus_hint_empty_becomes_none() -> None:
    opts = JobOptions(focus_hint="   ")
    assert opts.focus_hint is None


def test_style_preset_accepted_for_known_ids() -> None:
    for preset_id in ("default", "detailed", "concise", "technical", "academic"):
        opts = JobOptions(style_preset=preset_id)
        assert opts.style_preset == preset_id


def test_style_preset_rejected_for_unknown() -> None:
    with pytest.raises(Exception):
        JobOptions(style_preset="nonexistent_preset")


def test_omlx_model_override_accepted() -> None:
    opts = JobOptions(omlx_model_override="qwen2.5-32b")
    assert opts.omlx_model_override == "qwen2.5-32b"


# --- Power mode option validation ---

def test_power_mode_accepted() -> None:
    opts = JobOptions(power_mode=True)
    assert opts.power_mode is True


def test_power_prompt_accepted_within_limit() -> None:
    opts = JobOptions(power_prompt="Summarize as bullet points")
    assert opts.power_prompt == "Summarize as bullet points"


def test_power_prompt_rejected_over_2000_chars() -> None:
    with pytest.raises(Exception):
        JobOptions(power_prompt="x" * 2001)


def test_power_prompt_strips_whitespace() -> None:
    opts = JobOptions(power_prompt="  brief text  ")
    assert opts.power_prompt == "brief text"


def test_power_prompt_empty_becomes_none() -> None:
    opts = JobOptions(power_prompt="   ")
    assert opts.power_prompt is None


def test_strategy_override_auto() -> None:
    opts = JobOptions(strategy_override="auto")
    assert opts.strategy_override == "auto"


def test_strategy_override_force_single_shot() -> None:
    opts = JobOptions(strategy_override="force_single_shot")
    assert opts.strategy_override == "force_single_shot"


def test_strategy_override_invalid_rejected() -> None:
    with pytest.raises(Exception):
        JobOptions(strategy_override="invalid_strategy")


def test_power_options_round_trip() -> None:
    repo = _make_repo()
    job = repo.create_job(
        url="https://example.com",
        output_languages=["en"],
        mode="captions_first",
        options={"power_mode": True, "power_prompt": "test brief", "strategy_override": "force_single_shot"},
    )
    fetched = repo.get_job(job.id)
    assert fetched is not None
    assert fetched.options["power_mode"] is True
    assert fetched.options["power_prompt"] == "test brief"
    assert fetched.options["strategy_override"] == "force_single_shot"


def test_provider_override_accepted_for_known_providers() -> None:
    for value in ("omlx", "deepseek"):
        opts = JobOptions(summarizer_provider_override=value)
        assert opts.summarizer_provider_override == value


def test_provider_override_rejected_for_unknown() -> None:
    with pytest.raises(Exception):
        JobOptions(summarizer_provider_override="bogus")


def test_deepseek_model_accepted_for_known_models() -> None:
    for value in ("deepseek-v4-flash", "deepseek-v4-pro"):
        opts = JobOptions(deepseek_model=value)
        assert opts.deepseek_model == value


def test_deepseek_model_rejected_for_unknown() -> None:
    with pytest.raises(Exception):
        JobOptions(deepseek_model="deepseek-v4-ultra")


def test_round_trip_provider_override_options() -> None:
    repo = _make_repo()
    job = repo.create_job(
        url="https://example.com",
        output_languages=["en"],
        mode="captions_first",
        options={"summarizer_provider_override": "deepseek", "deepseek_model": "deepseek-v4-pro"},
    )
    fetched = repo.get_job(job.id)
    assert fetched is not None
    assert fetched.options["summarizer_provider_override"] == "deepseek"
    assert fetched.options["deepseek_model"] == "deepseek-v4-pro"


def test_round_trip_new_options() -> None:
    repo = _make_repo()
    job = repo.create_job(
        url="https://example.com",
        output_languages=["en"],
        mode="captions_first",
        options={"style_preset": "detailed", "focus_hint": "math proofs", "omlx_model_override": "qwen2.5-32b"},
    )
    fetched = repo.get_job(job.id)
    assert fetched is not None
    assert fetched.options["style_preset"] == "detailed"
    assert fetched.options["focus_hint"] == "math proofs"
    assert fetched.options["omlx_model_override"] == "qwen2.5-32b"
