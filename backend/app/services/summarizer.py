from __future__ import annotations

import json

from backend.app.core.config import Settings
from backend.app.utils.text import chunk_text, split_sentences


class MlxQwenSummaryGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._tokenizer = None

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
    ) -> dict:
        if not self.settings.enable_mlx_summarizer:
            return RuleBasedSummaryGenerator(self.settings).summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )

        try:
            self._ensure_model_loaded()
            prompt = self._build_prompt(source_metadata, chapters, output_languages)

            from mlx_lm import generate  # type: ignore[import-not-found]

            output = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=1200)
            parsed = json.loads(output)
        except Exception:
            return RuleBasedSummaryGenerator(self.settings).summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )
        return parsed

    def _ensure_model_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            from mlx_lm import load  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("mlx-lm is not installed. Run `uv sync --extra mlx` to enable MLX summarization.")
        self._model, self._tokenizer = load(self.settings.summarizer_model)

    def _build_prompt(self, source_metadata: dict, chapters: list[dict], output_languages: list[str]) -> str:
        chapter_blocks = []
        for chapter in chapters:
            text_chunks = chunk_text(chapter["text"], self.settings.summarizer_max_input_chars)
            chapter_blocks.append(
                {
                    "start_s": chapter["start_s"],
                    "end_s": chapter["end_s"],
                    "title_hint": chapter["title_hint"],
                    "text": " ".join(text_chunks[:1]),
                }
            )
        target_languages = ", ".join(output_languages)
        return (
            "You are a multilingual video summarization model.\n"
            "Return valid JSON with keys `chapters` and `overall_summary`.\n"
            f"Target languages: {target_languages}.\n"
            f"Metadata: {json.dumps(source_metadata, ensure_ascii=False)}\n"
            f"Chapters: {json.dumps(chapter_blocks, ensure_ascii=False)}\n"
            "Each chapter item must include start_s, end_s, title, summary_en, summary_zh, and key_points.\n"
            "The overall_summary must include summary_en, summary_zh, and highlights.\n"
        )


class RuleBasedSummaryGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
    ) -> dict:
        chapter_summaries = []
        all_text = " ".join(segment["text"] for segment in transcript_segments)
        for index, chapter in enumerate(chapters, start=1):
            sentences = split_sentences(chapter["text"], limit=2)
            summary_en = " ".join(sentences) if sentences else chapter["title_hint"]
            chapter_summaries.append(
                {
                    "start_s": chapter["start_s"],
                    "end_s": chapter["end_s"],
                    "title": chapter["title_hint"] or f"Chapter {index}",
                    "summary_en": summary_en,
                    "summary_zh": f"第{index}部分：{summary_en}",
                    "key_points": sentences or [chapter["title_hint"]],
                }
            )

        overall_sentences = split_sentences(all_text, limit=3)
        overall_en = " ".join(overall_sentences) if overall_sentences else source_metadata.get("title", "Summary unavailable.")
        return {
            "chapters": chapter_summaries,
            "overall_summary": {
                "summary_en": overall_en,
                "summary_zh": f"整体总结：{overall_en}",
                "highlights": overall_sentences or [source_metadata.get("title", "Untitled video")],
            },
        }
