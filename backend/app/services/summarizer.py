from __future__ import annotations

import json
import logging
import re
import time

from backend.app.core.config import Settings
from backend.app.utils.text import chunk_text, split_sentences

logger = logging.getLogger(__name__)


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
            logger.info("MLX summarizer disabled, using rule-based fallback")
            return RuleBasedSummaryGenerator(self.settings).summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )

        try:
            self._ensure_model_loaded()
            system_msg, user_msg = self._build_prompt(source_metadata, chapters, output_languages)
            prompt = self._apply_chat_template(system_msg, user_msg)
            logger.info("prompt built: %d chars, %d chapters", len(prompt), len(chapters))

            from mlx_lm import generate  # type: ignore[import-not-found]

            max_tokens = max(self.settings.summarizer_max_tokens, 512 * len(chapters) + 512)
            logger.info("generating summary (max_tokens=%d, chapters=%d)...", max_tokens, len(chapters))
            t0 = time.perf_counter()
            raw_output = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=max_tokens)
            elapsed = time.perf_counter() - t0
            logger.info("generation complete: %d chars output in %.1fs (%.0f chars/s)",
                        len(raw_output), elapsed, len(raw_output) / elapsed if elapsed > 0 else 0)
            output = self._extract_json(raw_output)
            parsed = json.loads(output)
            logger.info("output parsed successfully: chapters=%d", len(parsed.get("chapters", [])))
        except json.JSONDecodeError as exc:
            logger.warning("LLM output was not valid JSON (%s), falling back to rule-based. Raw output:\n%s",
                           exc, output[:500] if output else "<empty>")
            return RuleBasedSummaryGenerator(self.settings).summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )
        except Exception as exc:
            logger.warning("MLX summarizer failed (%s: %s), falling back to rule-based", type(exc).__name__, exc)
            return RuleBasedSummaryGenerator(self.settings).summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )
        return parsed

    def _ensure_model_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            logger.info("model already loaded: %s", self.settings.summarizer_model)
            return
        try:
            from mlx_lm import load  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("mlx-lm is not installed. Run `uv sync --extra mlx` to enable MLX summarization.")
        logger.info("loading model: %s ...", self.settings.summarizer_model)
        t0 = time.perf_counter()
        self._model, self._tokenizer = load(self.settings.summarizer_model)
        logger.info("model loaded in %.1fs", time.perf_counter() - t0)

    def _build_prompt(self, source_metadata: dict, chapters: list[dict], output_languages: list[str]) -> tuple[str, str]:
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
        brief_metadata = {
            k: source_metadata[k]
            for k in ("title", "description", "duration", "upload_date", "channel", "tags")
            if k in source_metadata
        }
        system_msg = (
            "You are a multilingual video summarization model.\n"
            "Return valid JSON with keys `chapters` and `overall_summary`.\n"
            "Each chapter item must include start_s, end_s, title, summary_en, summary_zh, and key_points.\n"
            "The overall_summary must include summary_en, summary_zh, and highlights.\n"
            "Output ONLY the JSON object. No explanation, no thinking, no markdown fences.\n"
        )
        user_msg = (
            f"Target languages: {target_languages}.\n"
            f"Metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n"
            f"Chapters: {json.dumps(chapter_blocks, ensure_ascii=False)}\n"
            "/no_think"
        )
        return system_msg, user_msg

    def _apply_chat_template(self, system_msg: str, user_msg: str) -> str:
        if hasattr(self._tokenizer, "apply_chat_template"):
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            formatted = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            logger.info("prompt formatted with chat template: %d chars", len(formatted))
            return formatted
        logger.warning("tokenizer lacks apply_chat_template, using raw prompt")
        return system_msg + "\n" + user_msg

    def _extract_json(self, raw: str) -> str:
        # Strip <think>...</think> blocks from thinking models
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        # Find first { to last } as the JSON object
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        if cleaned != raw:
            logger.info("extracted JSON: %d -> %d chars", len(raw), len(cleaned))
        return cleaned


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
