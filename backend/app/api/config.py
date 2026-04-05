from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.core.style_presets import STYLE_PRESETS

router = APIRouter(tags=["config"])


def _mlx_runtime_available() -> bool:
    """Check if the optional mlx-lm package is importable."""
    try:
        import mlx_lm  # type: ignore[import-not-found]  # noqa: F401
        return True
    except ImportError:
        return False


@router.get("/config")
def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    provider = settings.summarizer_provider

    if provider == "omlx":
        current_model = settings.omlx_model or None
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

    return {
        "summarizer_provider": provider,
        "current_model": current_model,
        "model_override_allowed": provider == "omlx",
        "supports_prompt_customization": supports_prompts,
        "style_presets": [
            {"id": p.id, "label": p.label, "description": p.description}
            for p in STYLE_PRESETS.values()
        ],
    }
