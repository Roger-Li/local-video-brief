from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

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
        artifact_dir: Optional[Path] = None,
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

            # Save prompt to artifact for debugging.
            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "summarizer_prompt.txt").write_text(prompt, encoding="utf-8")

            from mlx_lm import generate  # type: ignore[import-not-found]

            max_tokens = max(self.settings.summarizer_max_tokens, 1024 * len(chapters) + 1024)
            logger.info("generating summary (max_tokens=%d, chapters=%d)...", max_tokens, len(chapters))
            t0 = time.perf_counter()
            raw_output = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=max_tokens)
            elapsed = time.perf_counter() - t0
            logger.info("generation complete: %d chars output in %.1fs (%.0f chars/s)",
                        len(raw_output), elapsed, len(raw_output) / elapsed if elapsed > 0 else 0)

            # Save raw LLM output to artifact for debugging.
            if artifact_dir:
                (artifact_dir / "summarizer_raw_output.txt").write_text(raw_output, encoding="utf-8")

            output = self._extract_json(raw_output)
            parsed = json.loads(output)
            logger.info("output parsed successfully: chapters=%d", len(parsed.get("chapters", [])))
        except json.JSONDecodeError as exc:
            logger.warning("LLM output was not valid JSON (%s), falling back to rule-based. Raw output:\n%s",
                           exc, raw_output[:2000] if raw_output else "<empty>")
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
        schema_example = json.dumps(
            {
                "chapters": [
                    {
                        "start_s": 0.0,
                        "end_s": 120.0,
                        "title": "Short descriptive chapter title",
                        "summary_en": "2-4 sentence English summary of this chapter.",
                        "summary_zh": "2-4 sentence Chinese summary of this chapter.",
                        "key_points": ["key point 1", "key point 2"],
                    }
                ],
                "overall_summary": {
                    "summary_en": "3-5 sentence English summary of the entire video.",
                    "summary_zh": "3-5 sentence Chinese summary of the entire video.",
                    "highlights": ["highlight 1", "highlight 2", "highlight 3"],
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        system_msg = (
            "You are a multilingual video summarization model.\n"
            "Output ONLY a single valid JSON object matching this exact schema:\n"
            f"{schema_example}\n\n"
            "Rules:\n"
            "- Return one chapter object per input chapter with start_s, end_s, title, summary_en, summary_zh, key_points.\n"
            "- summary_en and summary_zh must be substantive (3-5 sentences each), not just the first line of the transcript.\n"
            "- key_points should capture the main ideas discussed.\n"
            "- overall_summary should cover the full video.\n"
            "- Output ONLY the JSON object. No explanation, no thinking, no markdown fences, no trailing text.\n"
            "- All strings must use valid JSON escaping (double quotes, escaped newlines).\n"
        )
        user_msg = (
            f"Target languages: {target_languages}.\n"
            f"Metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n"
            f"Chapters: {json.dumps(chapter_blocks, ensure_ascii=False)}\n"
        )
        return system_msg, user_msg

    def _apply_chat_template(self, system_msg: str, user_msg: str) -> str:
        if hasattr(self._tokenizer, "apply_chat_template"):
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            # Pass enable_thinking=False so the template inserts a closed
            # <think></think> block, telling the model to skip thinking and
            # produce the answer directly.
            formatted = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
                enable_thinking=False,
            )
            logger.info("prompt formatted with chat template: %d chars", len(formatted))
            return formatted
        logger.warning("tokenizer lacks apply_chat_template, using raw prompt")
        return system_msg + "\n" + user_msg

    def _extract_json(self, raw: str) -> str:
        # Strip closed <think>...</think> blocks.
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Strip unclosed <think> blocks (model started thinking but never closed).
        cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL).strip()
        # Strip markdown code fences if present.
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        # Use raw_decode to extract the first complete JSON object,
        # ignoring any trailing characters (extra braces, whitespace, etc.).
        start = cleaned.find("{")
        if start != -1:
            try:
                decoder = json.JSONDecoder()
                _, end_idx = decoder.raw_decode(cleaned, start)
                cleaned = cleaned[start:end_idx]
            except json.JSONDecodeError:
                # raw_decode failed — fall back to first-{ to last-} heuristic.
                end = cleaned.rfind("}")
                if end > start:
                    cleaned = cleaned[start : end + 1]
        if cleaned != raw:
            logger.info("extracted JSON: %d -> %d chars", len(raw), len(cleaned))
        return cleaned


class RuleBasedSummaryGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # Maximum characters for a rule-based summary or highlight entry.
    _MAX_SUMMARY_CHARS = 500

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
    ) -> dict:
        chapter_summaries = []
        all_text = " ".join(segment["text"] for segment in transcript_segments)
        for index, chapter in enumerate(chapters, start=1):
            sentences = self._extract_sentences(chapter["text"], limit=2)
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

        overall_sentences = self._extract_sentences(all_text, limit=3)
        overall_en = " ".join(overall_sentences) if overall_sentences else source_metadata.get("title", "Summary unavailable.")
        return {
            "chapters": chapter_summaries,
            "overall_summary": {
                "summary_en": overall_en,
                "summary_zh": f"整体总结：{overall_en}",
                "highlights": overall_sentences or [source_metadata.get("title", "Untitled video")],
            },
        }

    def _extract_sentences(self, text: str, limit: int) -> list[str]:
        """Extract up to *limit* sentences, capping each at _MAX_SUMMARY_CHARS.

        For text without sentence-ending punctuation (common with Chinese
        ASR/captions), fall back to a character-level truncation so the
        rule-based summary never dumps the entire transcript.
        """
        sentences = split_sentences(text, limit=limit)
        # If split_sentences returned a single entry that is just the whole
        # text (no punctuation split happened), truncate it.
        result: list[str] = []
        for s in sentences:
            if len(s) > self._MAX_SUMMARY_CHARS:
                s = s[: self._MAX_SUMMARY_CHARS].rstrip() + "…"
            result.append(s)
        return result
