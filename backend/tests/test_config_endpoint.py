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


def test_config_returns_supports_power_mode() -> None:
    with TestClient(app) as client:
        data = client.get("/config").json()
        assert "supports_power_mode" in data
        # For fallback provider, should be False
        if data["summarizer_provider"] == "fallback":
            assert data["supports_power_mode"] is False


def test_config_exposes_default_and_available_providers() -> None:
    with TestClient(app) as client:
        data = client.get("/config").json()
        assert "default_summarizer_provider" in data
        assert data["default_summarizer_provider"] == data["summarizer_provider"]
        assert "available_summarizer_providers" in data
        assert isinstance(data["available_summarizer_providers"], list)


def test_config_omits_deepseek_when_unconfigured(monkeypatch) -> None:
    """When OVS_DEEPSEEK_API_KEY is not set, DeepSeek must not appear in the list."""
    monkeypatch.delenv("OVS_DEEPSEEK_API_KEY", raising=False)
    with TestClient(app) as client:
        data = client.get("/config").json()
        ids = {entry["id"] for entry in data["available_summarizer_providers"]}
        assert "deepseek" not in ids


def test_power_prompt_default_endpoint() -> None:
    with TestClient(app) as client:
        resp = client.get("/config/power-prompt-default")
        assert resp.status_code == 200
        data = resp.json()
        assert "default_prompt" in data
        assert "multilingual video summarization" in data["default_prompt"]


def test_power_prompt_default_with_preset() -> None:
    with TestClient(app) as client:
        resp = client.get("/config/power-prompt-default?style_preset=detailed")
        assert resp.status_code == 200
        data = resp.json()
        assert "thorough" in data["default_prompt"].lower()


def test_power_prompt_default_with_focus_hint() -> None:
    with TestClient(app) as client:
        resp = client.get("/config/power-prompt-default?focus_hint=math%20proofs")
        assert resp.status_code == 200
        data = resp.json()
        assert "Content focus: math proofs" in data["default_prompt"]


def test_power_prompt_default_with_preset_and_focus() -> None:
    with TestClient(app) as client:
        resp = client.get("/config/power-prompt-default?style_preset=concise&focus_hint=algorithms")
        data = resp.json()
        assert "brief" in data["default_prompt"].lower()
        assert "Content focus: algorithms" in data["default_prompt"]
