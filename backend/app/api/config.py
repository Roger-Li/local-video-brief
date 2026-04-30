from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.core.style_presets import STYLE_PRESETS
from backend.app.services.summarizer import build_power_default_brief

router = APIRouter(tags=["config"])


def _mlx_runtime_available() -> bool:
    """Check if the optional mlx-lm package is importable."""
    try:
        import mlx_lm  # type: ignore[import-not-found]  # noqa: F401
        return True
    except ImportError:
        return False


_DEEPSEEK_MODEL_CHOICES = (
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
    {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
)


@router.get("/config")
def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    provider = settings.summarizer_provider

    if provider == "omlx":
        current_model = settings.omlx_model or None
        supports_prompts = True
    elif provider == "deepseek":
        current_model = settings.deepseek_model or None
        supports_prompts = True
    elif provider == "mlx":
        if _mlx_runtime_available():
            current_model = settings.summarizer_model or None
            supports_prompts = True
        else:
            current_model = None
            supports_prompts = False
    else:
        current_model = None
        supports_prompts = False

    available_providers: list[dict] = []
    if settings.omlx_base_url and settings.omlx_model:
        available_providers.append({
            "id": "omlx",
            "label": "Local oMLX",
            "current_model": settings.omlx_model or None,
            "model_override_allowed": True,
        })
    if settings.deepseek_api_key:
        available_providers.append({
            "id": "deepseek",
            "label": "DeepSeek API",
            "current_model": settings.deepseek_model or None,
            "model_override_allowed": False,
            "model_choices": [dict(item) for item in _DEEPSEEK_MODEL_CHOICES],
        })

    return {
        "summarizer_provider": provider,
        "default_summarizer_provider": provider,
        "available_summarizer_providers": available_providers,
        "current_model": current_model,
        "model_override_allowed": provider == "omlx",
        "supports_prompt_customization": supports_prompts,
        "supports_power_mode": supports_prompts,
        "style_presets": [
            {"id": p.id, "label": p.label, "description": p.description}
            for p in STYLE_PRESETS.values()
        ],
    }


@router.get("/config/power-prompt-default")
def get_power_prompt_default(
    style_preset: str | None = None,
    focus_hint: str | None = None,
) -> dict:
    """Return the default editable summary brief for Power mode."""
    return {"default_prompt": build_power_default_brief(style_preset, focus_hint)}
