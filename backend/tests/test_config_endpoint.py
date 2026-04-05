from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core.style_presets import STYLE_PRESETS
from backend.app.main import app


def test_config_returns_provider() -> None:
    with TestClient(app) as client:
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "summarizer_provider" in data


def test_config_fallback_provider_flags() -> None:
    """With default settings (fallback), prompt customization is off."""
    with TestClient(app) as client:
        data = client.get("/config").json()
        if data["summarizer_provider"] == "fallback":
            assert data["supports_prompt_customization"] is False
            assert data["model_override_allowed"] is False
            assert data["current_model"] is None


def test_config_style_presets_match_registry() -> None:
    with TestClient(app) as client:
        data = client.get("/config").json()
        preset_ids = {p["id"] for p in data["style_presets"]}
        assert preset_ids == set(STYLE_PRESETS.keys())
        for p in data["style_presets"]:
            assert "label" in p
            assert "description" in p


def test_config_mlx_without_runtime_disables_prompts() -> None:
    """When provider is mlx but mlx_lm is not installed, prompt customization should be off."""
    with TestClient(app) as client:
        data = client.get("/config").json()
        if data["summarizer_provider"] == "mlx":
            with patch("backend.app.api.config._mlx_runtime_available", return_value=False):
                data = client.get("/config").json()
                assert data["supports_prompt_customization"] is False
                assert data["current_model"] is None
