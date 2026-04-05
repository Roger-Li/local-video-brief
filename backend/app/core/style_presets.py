from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StylePreset:
    id: str
    label: str
    description: str
    system_suffix: str
    chapter_length: str
    single_shot_chapter_length: str
    overall_length: str
    max_tokens_multiplier: float


STYLE_PRESETS: dict[str, StylePreset] = {
    "default": StylePreset(
        id="default",
        label="Default",
        description="Balanced summaries with standard detail level.",
        system_suffix="",
        chapter_length="2-4",
        single_shot_chapter_length="3-5",
        overall_length="3-5",
        max_tokens_multiplier=1.0,
    ),
    "detailed": StylePreset(
        id="detailed",
        label="Detailed",
        description="Thorough summaries with extensive key points.",
        system_suffix="Provide thorough summaries with extensive key points covering all major arguments and examples.",
        chapter_length="5-7",
        single_shot_chapter_length="5-7",
        overall_length="5-8",
        max_tokens_multiplier=1.5,
    ),
    "concise": StylePreset(
        id="concise",
        label="Concise",
        description="Brief, focused summaries.",
        system_suffix="Keep summaries extremely brief and focused.",
        chapter_length="1-2",
        single_shot_chapter_length="1-2",
        overall_length="2-3",
        max_tokens_multiplier=0.6,
    ),
    "technical": StylePreset(
        id="technical",
        label="Technical",
        description="Focus on technical details and precise terminology.",
        system_suffix="Focus on technical details, implementation specifics, precise terminology, and quantitative claims. Preserve domain-specific language.",
        chapter_length="3-5",
        single_shot_chapter_length="3-5",
        overall_length="3-5",
        max_tokens_multiplier=1.2,
    ),
    "academic": StylePreset(
        id="academic",
        label="Academic",
        description="Formal academic tone with evidence and methodology focus.",
        system_suffix="Use formal academic tone. Reference specific claims, evidence, and arguments from the content. Note methodological details or citations mentioned.",
        chapter_length="3-5",
        single_shot_chapter_length="3-5",
        overall_length="4-6",
        max_tokens_multiplier=1.2,
    ),
}
