from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

from backend.app.core.config import Settings
from backend.app.core.style_presets import STYLE_PRESETS, StylePreset
from backend.app.utils.text import chunk_segments, chunk_text, segments_to_text, split_sentences

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resolve_preset(style_preset_id: str | None) -> StylePreset:
    """Return the preset for the given ID, falling back to default."""
    if style_preset_id and style_preset_id in STYLE_PRESETS:
        return STYLE_PRESETS[style_preset_id]
    return STYLE_PRESETS["default"]


# ---------------------------------------------------------------------------
# Power mode constants and helpers
# ---------------------------------------------------------------------------

_POWER_MODE_SYSTEM = (
    "You are a video summarization assistant. "
    "Output your response as clear, well-structured text using markdown formatting. "
    "Use headings and bullet points where appropriate. "
    "Do NOT output JSON. Do NOT wrap your response in code fences."
)

_POWER_SINGLE_SHOT_UTILISATION = 0.9


def build_power_default_brief(
    style_preset_id: str | None = None,
    focus_hint: str | None = None,
) -> str:
    """Derive a human-readable summary brief from guided settings.

    This is what pre-populates the Power mode textarea. It uses the
    preset's actual system_suffix (not the UI description), so the
    user sees the real instruction text that guided mode would apply.
    """
    preset = _resolve_preset(style_preset_id)

    parts = [
        "You are a multilingual video summarization model. "
        "Summarize the provided transcript clearly and thoroughly. "
        "Cover the main topics, key arguments, and important details. "
        "Produce output in both English and Chinese."
    ]

    if preset.system_suffix:
        parts.append(preset.system_suffix)

    if focus_hint and focus_hint.strip():
        parts.append(f"Content focus: {focus_hint.strip()}")

    return "\n\n".join(parts)


def _build_power_user_msg(
    power_prompt: str,
    source_metadata: dict,
    chapters: list[dict],
) -> str:
    brief_metadata = {
        k: source_metadata[k]
        for k in ("title", "description", "duration", "upload_date", "channel", "tags")
        if k in source_metadata
    }
    transcript_text = "\n\n".join(
        f"[{ch['start_s']:.0f}s - {ch['end_s']:.0f}s] {ch.get('title_hint', '')}\n{ch['text']}"
        for ch in chapters
    )
    return (
        f"Summarization instructions:\n{power_prompt}\n"
        f"---\n"
        f"Video metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n\n"
        f"Transcript:\n{transcript_text}"
    )


def _build_power_chapter_user_msg(
    power_prompt: str,
    chapter: dict,
    chapter_index: int,
    total_chapters: int,
) -> str:
    return (
        f"Summarization instructions:\n{power_prompt}\n"
        f"---\n"
        f"Chapter {chapter_index + 1} of {total_chapters}: "
        f"{chapter.get('title_hint', 'Untitled')}\n"
        f"Time range: {chapter['start_s']:.0f}s - {chapter['end_s']:.0f}s\n\n"
        f"{chapter['text']}"
    )


def _build_power_overall_user_msg(
    power_prompt: str,
    source_metadata: dict,
    chapter_proses: list[str],
) -> str:
    chapters_block = "\n\n".join(
        f"[Chapter {i+1}]\n{prose}" for i, prose in enumerate(chapter_proses)
    )
    brief_metadata = {
        k: source_metadata[k]
        for k in ("title", "description", "duration", "upload_date", "channel", "tags")
        if k in source_metadata
    }
    return (
        f"Summarization instructions:\n{power_prompt}\n\n"
        f"Below are per-chapter summaries. Synthesize them into a single "
        f"overall summary of the entire video.\n"
        f"---\n"
        f"Video metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n\n"
        f"Chapter summaries:\n{chapters_block}"
    )


def _power_stub_result(raw_text: str) -> dict:
    """Wrap power mode prose into the standard result envelope."""
    return {
        "raw_summary_text": raw_text,
        "chapters": [],
        "overall_summary": {
            "summary_en": "",
            "summary_zh": "",
            "highlights": [],
        },
    }


def _format_rule_based_chapter_as_prose(ch_summary: dict) -> str:
    """Format a rule-based chapter summary dict as readable prose for power mode fallback."""
    title = ch_summary.get("title", "Untitled")
    summary = ch_summary.get("summary_en", "")
    key_points = ch_summary.get("key_points", [])
    parts = [f"## {title}", summary]
    if key_points:
        parts.append("\n".join(f"- {pt}" for pt in key_points))
    return "\n\n".join(parts)


def build_summarizer_prompt(
    settings: Settings,
    source_metadata: dict,
    chapters: list[dict],
    output_languages: list[str],
    preset: StylePreset | None = None,
    focus_hint: str | None = None,
) -> tuple[str, str]:
    """Return (system_msg, user_msg) for summarization."""
    if preset is None:
        preset = STYLE_PRESETS["default"]
    chapter_blocks = []
    for chapter in chapters:
        text_chunks = chunk_text(chapter["text"], settings.summarizer_max_input_chars)
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
                    "summary_en": f"{preset.chapter_length} sentence English summary of this chapter.",
                    "summary_zh": f"{preset.chapter_length} sentence Chinese summary of this chapter.",
                    "key_points": ["key point 1", "key point 2"],
                }
            ],
            "overall_summary": {
                "summary_en": f"{preset.overall_length} sentence English summary of the entire video.",
                "summary_zh": f"{preset.overall_length} sentence Chinese summary of the entire video.",
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
        f"- summary_en and summary_zh must be substantive ({preset.single_shot_chapter_length} sentences each), not just the first line of the transcript.\n"
        "- key_points should capture the main ideas discussed.\n"
        "- overall_summary should cover the full video.\n"
        "- Output ONLY the JSON object. No explanation, no thinking, no markdown fences, no trailing text.\n"
        "- All strings must use valid JSON escaping (double quotes, escaped newlines).\n"
    )
    if preset.system_suffix:
        system_msg += f"\n{preset.system_suffix}\n"
    user_msg_parts = []
    if focus_hint:
        user_msg_parts.append(f"Content focus: {focus_hint}\n---")
    user_msg_parts.append(f"Target languages: {target_languages}.")
    user_msg_parts.append(f"Metadata: {json.dumps(brief_metadata, ensure_ascii=False)}")
    user_msg_parts.append(f"Chapters: {json.dumps(chapter_blocks, ensure_ascii=False)}")
    user_msg = "\n".join(user_msg_parts) + "\n"
    return system_msg, user_msg


def extract_json(raw: str) -> str:
    """Extract the first complete JSON object from model output."""
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
            decoder = json.JSONDecoder(strict=False)
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


def _next_non_whitespace_index(raw: str, start: int) -> int:
    while start < len(raw) and raw[start] in " \t\r\n":
        start += 1
    return start


def _literal_has_boundary(raw: str, start: int, literal: str) -> bool:
    if not raw.startswith(literal, start):
        return False
    next_index = _next_non_whitespace_index(raw, start + len(literal))
    if next_index >= len(raw):
        return True
    return raw[next_index] in ",}]"


def _find_unescaped_quote_end(raw: str, start_quote_index: int) -> int | None:
    escape = False
    for index in range(start_quote_index + 1, len(raw)):
        char = raw[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            return index
    return None


def _quoted_token_looks_standalone_after_comma(raw: str, start_quote_index: int, container_type: str) -> bool:
    end_quote_index = _find_unescaped_quote_end(raw, start_quote_index)
    if end_quote_index is None:
        return False
    next_index = _next_non_whitespace_index(raw, end_quote_index + 1)
    if next_index >= len(raw):
        return True
    next_sig = raw[next_index]
    if container_type == "object":
        return next_sig == ":"
    if next_sig == "]":
        return True
    if next_sig == ",":
        return _looks_like_value_start_after_comma(raw, next_index + 1, container_type)
    return False


def _looks_like_value_start_after_comma(raw: str, start: int, container_type: str) -> bool:
    next_index = _next_non_whitespace_index(raw, start)
    if next_index >= len(raw):
        return False
    next_sig = raw[next_index]
    if container_type == "object":
        return next_sig == '"' and _quoted_token_looks_standalone_after_comma(raw, next_index, container_type)
    if next_sig == '"':
        return _quoted_token_looks_standalone_after_comma(raw, next_index, container_type)
    if next_sig in {"{", "[", "-", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
        return True
    if next_sig == "t":
        return _literal_has_boundary(raw, next_index, "true")
    if next_sig == "f":
        return _literal_has_boundary(raw, next_index, "false")
    if next_sig == "n":
        return _literal_has_boundary(raw, next_index, "null")
    return False


def _quote_terminates_string(raw: str, quote_index: int, string_role: str, container_type: str) -> bool:
    next_index = _next_non_whitespace_index(raw, quote_index + 1)
    next_sig = raw[next_index] if next_index < len(raw) else ""
    if string_role == "object_key":
        return next_sig == ":"
    if next_sig in {"", "}", "]"}:
        return True
    if next_sig == ":":
        return False
    if next_sig == ",":
        return _looks_like_value_start_after_comma(raw, next_index + 1, container_type)
    return False


def _after_value_state(context_stack: list[str]) -> str:
    if not context_stack:
        return "root_done"
    return "object_comma_or_end" if context_stack[-1] == "object" else "array_comma_or_end"


def _validate_required_keys(parsed: dict, required_keys: set[str] | None) -> dict:
    if not required_keys:
        return parsed
    missing = sorted(key for key in required_keys if key not in parsed)
    if missing:
        raise ValueError(f"model JSON missing required keys: {', '.join(missing)}")
    return parsed


def _escape_unescaped_inner_quotes(raw: str) -> str:
    """Escape stray quotes that appear inside JSON strings."""
    repaired: list[str] = []
    context_stack: list[str] = []
    state = "root_value"
    in_string = False
    string_role = "value"
    escape = False
    in_scalar = False

    index = 0
    while index < len(raw):
        char = raw[index]
        if escape:
            repaired.append(char)
            escape = False
            index += 1
            continue

        if in_scalar:
            if char in " \t\r\n":
                repaired.append(char)
                in_scalar = False
                state = _after_value_state(context_stack)
                index += 1
                continue
            if char in ",}]":
                in_scalar = False
                state = _after_value_state(context_stack)
                continue
            repaired.append(char)
            index += 1
            continue

        if in_string and char == "\\":
            repaired.append(char)
            escape = True
            index += 1
            continue

        if in_string:
            if char != '"':
                repaired.append(char)
                index += 1
                continue
            container_type = context_stack[-1] if context_stack else "root"
            if _quote_terminates_string(raw, index, string_role, container_type):
                in_string = False
                repaired.append(char)
                state = "object_colon" if string_role == "object_key" else _after_value_state(context_stack)
            else:
                repaired.append('\\"')
            index += 1
            continue

        if char in " \t\r\n":
            repaired.append(char)
            index += 1
            continue

        repaired.append(char)

        if state == "root_value":
            if char == '"':
                in_string = True
                string_role = "value"
            elif char == "{":
                context_stack.append("object")
                state = "object_key_or_end"
            elif char == "[":
                context_stack.append("array")
                state = "array_value_or_end"
            else:
                in_scalar = True
        elif state == "object_key_or_end":
            if char == "}":
                if context_stack:
                    context_stack.pop()
                state = _after_value_state(context_stack)
            elif char == '"':
                in_string = True
                string_role = "object_key"
        elif state == "object_key":
            if char == '"':
                in_string = True
                string_role = "object_key"
        elif state == "object_colon":
            if char == ":":
                state = "object_value"
        elif state == "object_value":
            if char == '"':
                in_string = True
                string_role = "value"
            elif char == "{":
                context_stack.append("object")
                state = "object_key_or_end"
            elif char == "[":
                context_stack.append("array")
                state = "array_value_or_end"
            else:
                in_scalar = True
        elif state == "object_comma_or_end":
            if char == ",":
                state = "object_key"
            elif char == "}":
                if context_stack:
                    context_stack.pop()
                state = _after_value_state(context_stack)
        elif state == "array_value_or_end":
            if char == "]":
                if context_stack:
                    context_stack.pop()
                state = _after_value_state(context_stack)
            elif char == '"':
                in_string = True
                string_role = "value"
            elif char == "{":
                context_stack.append("object")
                state = "object_key_or_end"
            elif char == "[":
                context_stack.append("array")
                state = "array_value_or_end"
            else:
                in_scalar = True
        elif state == "array_value":
            if char == '"':
                in_string = True
                string_role = "value"
            elif char == "{":
                context_stack.append("object")
                state = "object_key_or_end"
            elif char == "[":
                context_stack.append("array")
                state = "array_value_or_end"
            else:
                in_scalar = True
        elif state == "array_comma_or_end":
            if char == ",":
                state = "array_value"
            elif char == "]":
                if context_stack:
                    context_stack.pop()
                state = _after_value_state(context_stack)

        index += 1

    return "".join(repaired)


def parse_model_json(raw: str, required_keys: set[str] | None = None) -> dict:
    """Parse model JSON while tolerating literal control characters in strings."""
    cleaned = extract_json(raw)
    try:
        return _validate_required_keys(json.loads(cleaned, strict=False), required_keys)
    except json.JSONDecodeError:
        repaired = _escape_unescaped_inner_quotes(cleaned)
        if repaired != cleaned:
            logger.warning("repairing model JSON by escaping stray inner quotes")
            return _validate_required_keys(json.loads(repaired, strict=False), required_keys)
        raise


def compute_max_tokens(settings: Settings, chapter_count: int, multiplier: float = 1.0) -> int:
    """Dynamic max_tokens based on chapter count.

    The multiplier adds headroom for verbose presets but is capped at
    base + summarizer_max_tokens to avoid exceeding provider token limits
    (common on oMLX/OpenAI-compatible deployments).
    """
    base = max(settings.summarizer_max_tokens, 1024 * chapter_count + 1024)
    scaled = int(base * multiplier)
    cap = base + settings.summarizer_max_tokens
    return min(scaled, cap)


# ---------------------------------------------------------------------------
# Routing strategy
# ---------------------------------------------------------------------------

_CHAPTER_REQUIRED_KEYS = {"start_s", "end_s", "title", "summary_en", "summary_zh", "key_points"}
_OVERALL_REQUIRED_KEYS = {"summary_en", "summary_zh", "highlights"}

# Prompt overhead margin: system prompt, schema example, metadata JSON, and
# per-chapter JSON wrapping add roughly 2-3 KB on top of raw chapter text.
# Using a 0.7 utilisation factor ensures near-threshold inputs route to per-chapter.
_SINGLE_SHOT_UTILISATION = 0.7


def _validate_single_shot_payload(parsed: dict, expected_chapters: int | None = None) -> dict:
    """Validate each chapter and overall_summary in a single-shot response.

    If *expected_chapters* is given, the response must contain exactly that
    many chapter summaries — otherwise the LLM merged/dropped/invented chapters.
    """
    chapters = parsed.get("chapters", [])
    if not isinstance(chapters, list):
        raise ValueError("single-shot 'chapters' is not a list")
    if expected_chapters is not None and len(chapters) != expected_chapters:
        raise ValueError(
            f"single-shot returned {len(chapters)} chapters, expected {expected_chapters}"
        )
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            raise ValueError(f"single-shot chapter {i} is not a dict")
        missing = sorted(k for k in _CHAPTER_REQUIRED_KEYS if k not in ch)
        if missing:
            raise ValueError(f"single-shot chapter {i} missing keys: {', '.join(missing)}")
    overall = parsed.get("overall_summary", {})
    if not isinstance(overall, dict):
        raise ValueError("single-shot 'overall_summary' is not a dict")
    missing = sorted(k for k in _OVERALL_REQUIRED_KEYS if k not in overall)
    if missing:
        raise ValueError(f"single-shot overall_summary missing keys: {', '.join(missing)}")
    return parsed


def _choose_strategy(chapters: list[dict], max_input_chars: int,
                     utilisation: float = _SINGLE_SHOT_UTILISATION) -> str:
    """Choose summarization strategy based on transcript size.

    Returns one of: 'single_shot', 'per_chapter', 'hierarchical'.
    """
    total_chars = sum(len(ch.get("text", "")) for ch in chapters)
    # Apply utilisation factor to account for prompt overhead (system prompt,
    # schema example, metadata JSON, per-chapter JSON wrapping).
    if total_chars <= int(max_input_chars * utilisation):
        return "single_shot"
    any_chapter_exceeds = any(
        len(ch.get("text", "")) > max_input_chars for ch in chapters
    )
    if any_chapter_exceeds:
        return "hierarchical"
    return "per_chapter"


# ---------------------------------------------------------------------------
# Hierarchical summarization prompts
# ---------------------------------------------------------------------------

_CHUNK_NOTE_SYSTEM = (
    "You are a note-taking assistant. "
    "Summarize the following transcript excerpt in 3-5 sentences of plain English. "
    "Focus on the main ideas, arguments, and facts presented. "
    "Do NOT output JSON. Output plain text only."
)


def _build_chunk_note_user(chunk_text: str, chapter_title: str,
                           chunk_index: int, total_chunks: int,
                           focus_hint: str | None = None) -> str:
    msg = (
        f"Chapter: {chapter_title}\n"
        f"Chunk {chunk_index + 1} of {total_chunks}:\n\n"
        f"{chunk_text}"
    )
    if focus_hint:
        msg += f"\n---\nContent focus: {focus_hint}"
    return msg


def _build_chapter_synthesis_system(preset: StylePreset | None = None) -> str:
    if preset is None:
        preset = STYLE_PRESETS["default"]
    msg = (
        "You are a multilingual video summarization model.\n"
        "Given notes from a single chapter, produce a JSON object with these fields:\n"
        '  "start_s": <float>, "end_s": <float>, "title": "<short title>",\n'
        f'  "summary_en": "<{preset.chapter_length} sentence English summary>",\n'
        f'  "summary_zh": "<{preset.chapter_length} sentence Chinese summary>",\n'
        '  "key_points": ["point 1", "point 2", ...]\n'
        "Output ONLY the JSON object. No explanation, no markdown fences.\n"
        "Use valid JSON escaping for every string value."
    )
    if preset.system_suffix:
        msg += f"\n{preset.system_suffix}"
    return msg


_CHAPTER_SYNTHESIS_SYSTEM = _build_chapter_synthesis_system()


def _build_chapter_synthesis_user(chapter: dict, chunk_notes: list[str],
                                  focus_hint: str | None = None) -> str:
    notes_block = "\n\n".join(f"[Note {i+1}] {note}" for i, note in enumerate(chunk_notes))
    parts = []
    if focus_hint:
        parts.append(f"Content focus: {focus_hint}\n---")
    parts.append(
        f"Chapter title: {chapter.get('title_hint', 'Untitled')}\n"
        f"Time range: {chapter['start_s']:.1f}s - {chapter['end_s']:.1f}s\n\n"
        f"Notes:\n{notes_block}"
    )
    return "\n".join(parts)


def _build_overall_synthesis_system(preset: StylePreset | None = None) -> str:
    if preset is None:
        preset = STYLE_PRESETS["default"]
    msg = (
        "You are a multilingual video summarization model.\n"
        "Given chapter summaries, produce a JSON object with these fields:\n"
        f'  "summary_en": "<{preset.overall_length} sentence English summary of the entire video>",\n'
        f'  "summary_zh": "<{preset.overall_length} sentence Chinese summary of the entire video>",\n'
        '  "highlights": ["highlight 1", "highlight 2", "highlight 3"]\n'
        "Output ONLY the JSON object. No explanation, no markdown fences.\n"
        "Use valid JSON escaping for every string value."
    )
    if preset.system_suffix:
        msg += f"\n{preset.system_suffix}"
    return msg


_OVERALL_SYNTHESIS_SYSTEM = _build_overall_synthesis_system()


def _build_overall_synthesis_user(source_metadata: dict,
                                  chapter_summaries: list[dict],
                                  focus_hint: str | None = None) -> str:
    brief_metadata = {
        k: source_metadata[k]
        for k in ("title", "description", "duration", "upload_date", "channel", "tags")
        if k in source_metadata
    }
    chapters_block = "\n".join(
        f"[Ch {i+1}] {ch.get('title', 'Untitled')}: {ch.get('summary_en', '')}"
        for i, ch in enumerate(chapter_summaries)
    )
    parts = []
    if focus_hint:
        parts.append(f"Content focus: {focus_hint}\n---")
    parts.append(
        f"Metadata: {json.dumps(brief_metadata, ensure_ascii=False)}\n\n"
        f"Chapter summaries:\n{chapters_block}"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MLX in-process summarizer
# ---------------------------------------------------------------------------

class MlxQwenSummaryGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._tokenizer = None

    def _call_llm(
        self,
        system_msg: str,
        user_msg: str,
        max_tokens: int,
        artifact_dir: Path | None = None,
        artifact_label: str = "",
    ) -> str:
        """Apply chat template, call mlx_lm.generate, save artifacts, return raw text."""
        self._ensure_model_loaded()
        prompt = self._apply_chat_template(system_msg, user_msg)
        label = f"_{artifact_label}" if artifact_label else ""
        logger.info("mlx prompt%s built: %d chars", label, len(prompt))

        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / f"summarizer{label}_prompt.txt").write_text(prompt, encoding="utf-8")

        from mlx_lm import generate  # type: ignore[import-not-found]

        logger.info("mlx generating%s (max_tokens=%d)...", label, max_tokens)
        t0 = time.perf_counter()
        raw_output = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=max_tokens)
        elapsed = time.perf_counter() - t0
        logger.info("mlx generation%s complete: %d chars in %.1fs", label, len(raw_output), elapsed)

        if artifact_dir:
            (artifact_dir / f"summarizer{label}_raw_output.txt").write_text(raw_output, encoding="utf-8")

        return raw_output

    def _chunk_note_tokens(self, multiplier: float = 1.0) -> int:
        base = max(512, self.settings.summarizer_max_tokens // 4)
        return int(base * multiplier)

    def _step_tokens(self, multiplier: float = 1.0) -> int:
        base = max(1024, self.settings.summarizer_max_tokens // 2)
        return int(base * multiplier)

    def _summarize_chunk(self, chunk_text: str, chapter_title: str,
                         chunk_index: int, total_chunks: int,
                         artifact_dir: Path | None = None,
                         focus_hint: str | None = None,
                         multiplier: float = 1.0) -> str:
        user_msg = _build_chunk_note_user(chunk_text, chapter_title, chunk_index, total_chunks, focus_hint=focus_hint)
        raw = self._call_llm(
            _CHUNK_NOTE_SYSTEM, user_msg, max_tokens=self._chunk_note_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label=f"chunk_{chunk_index}",
        )
        return raw.strip()

    def _synthesize_chapter(self, chapter: dict, chunk_notes: list[str],
                            artifact_dir: Path | None = None,
                            preset: StylePreset | None = None,
                            focus_hint: str | None = None,
                            multiplier: float = 1.0) -> dict:
        system_msg = _build_chapter_synthesis_system(preset)
        user_msg = _build_chapter_synthesis_user(chapter, chunk_notes, focus_hint=focus_hint)
        raw = self._call_llm(
            system_msg, user_msg, max_tokens=self._step_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label="chapter_synthesis",
        )
        return parse_model_json(raw, required_keys={"start_s", "end_s", "title", "summary_en", "summary_zh", "key_points"})

    def _synthesize_overall(self, source_metadata: dict,
                            chapter_summaries: list[dict],
                            artifact_dir: Path | None = None,
                            preset: StylePreset | None = None,
                            focus_hint: str | None = None,
                            multiplier: float = 1.0) -> dict:
        system_msg = _build_overall_synthesis_system(preset)
        user_msg = _build_overall_synthesis_user(source_metadata, chapter_summaries, focus_hint=focus_hint)
        raw = self._call_llm(
            system_msg, user_msg, max_tokens=self._step_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label="overall_synthesis",
        )
        return parse_model_json(raw, required_keys={"summary_en", "summary_zh", "highlights"})

    def _single_shot(
        self,
        source_metadata: dict,
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
        preset: StylePreset | None = None,
        focus_hint: str | None = None,
        multiplier: float = 1.0,
    ) -> dict:
        """Single-shot summarization: all chapters in one prompt, one LLM call."""
        system_msg, user_msg = build_summarizer_prompt(
            self.settings, source_metadata, chapters, output_languages,
            preset=preset, focus_hint=focus_hint,
        )
        max_tokens = compute_max_tokens(self.settings, len(chapters), multiplier)
        raw = self._call_llm(
            system_msg, user_msg, max_tokens=max_tokens,
            artifact_dir=artifact_dir, artifact_label="single_shot",
        )
        parsed = parse_model_json(raw, required_keys={"chapters", "overall_summary"})
        return _validate_single_shot_payload(parsed, expected_chapters=len(chapters))

    def _summarize_power(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path],
        progress_callback: Optional[Callable[[str], None]],
        opts: dict,
    ) -> dict:
        preset = _resolve_preset(opts.get("style_preset"))
        focus_hint = opts.get("focus_hint")
        multiplier = preset.max_tokens_multiplier
        power_prompt = opts.get("power_prompt") or build_power_default_brief(
            opts.get("style_preset"), focus_hint,
        )
        strategy_override = opts.get("strategy_override", "auto")
        max_input_chars = self.settings.summarizer_max_input_chars

        if strategy_override == "force_single_shot":
            strategy = "single_shot"
            total_chars = sum(len(ch.get("text", "")) for ch in chapters)
            if total_chars > max_input_chars:
                logger.warning(
                    "power force_single_shot: transcript %d chars exceeds max_input_chars %d",
                    total_chars, max_input_chars,
                )
        else:
            strategy = _choose_strategy(chapters, max_input_chars, _POWER_SINGLE_SHOT_UTILISATION)

        logger.info("power mode strategy=%s chapters=%d", strategy, len(chapters))
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "summarizer_strategy.txt").write_text(f"power_{strategy}", encoding="utf-8")

        max_tokens = compute_max_tokens(self.settings, len(chapters), multiplier)

        if strategy == "single_shot":
            if progress_callback:
                progress_callback("summarizing_single_shot")
            user_msg = _build_power_user_msg(power_prompt, source_metadata, chapters)
            raw = self._call_llm(
                _POWER_MODE_SYSTEM, user_msg, max_tokens=max_tokens,
                artifact_dir=artifact_dir, artifact_label="power_single_shot",
            )
            return _power_stub_result(raw.strip())

        # --- Per-chapter / hierarchical paths ---
        fallback = RuleBasedSummaryGenerator(self.settings)
        chapter_proses: list[str] = []

        if progress_callback:
            progress_callback("summarizing_chunks")

        for ch_idx, chapter in enumerate(chapters):
            ch_artifact = (artifact_dir / f"ch{ch_idx}") if artifact_dir else None
            seg_chunks = chunk_segments(chapter.get("segments", []), max_input_chars)

            if len(seg_chunks) > 1:
                # Hierarchical: condense chunks first (reuses guided chunk-note prompts).
                notes = []
                for c_idx, seg_chunk in enumerate(seg_chunks):
                    text = segments_to_text(seg_chunk)
                    try:
                        note = self._summarize_chunk(
                            text, chapter.get("title_hint", ""),
                            c_idx, len(seg_chunks), artifact_dir=ch_artifact,
                            focus_hint=focus_hint, multiplier=multiplier,
                        )
                    except Exception as exc:
                        logger.warning("power chunk note failed ch=%d chunk=%d: %s", ch_idx, c_idx, exc)
                        note = text
                    notes.append(note)
                chapter_text = "\n\n".join(notes)
            else:
                chapter_text = chapter.get("text", "")

            if progress_callback:
                progress_callback("synthesizing_chapters")

            try:
                user_msg = _build_power_chapter_user_msg(
                    power_prompt, {**chapter, "text": chapter_text},
                    ch_idx, len(chapters),
                )
                raw = self._call_llm(
                    _POWER_MODE_SYSTEM, user_msg, max_tokens=self._step_tokens(multiplier),
                    artifact_dir=ch_artifact, artifact_label="power_chapter",
                )
                prose = raw.strip()
            except Exception as exc:
                logger.warning("power chapter synthesis failed ch=%d: %s, using rule-based fallback", ch_idx, exc)
                ch_summary = fallback.summarize_chapter(chapter, ch_idx + 1)
                prose = _format_rule_based_chapter_as_prose(ch_summary)

            if ch_artifact:
                ch_artifact.mkdir(parents=True, exist_ok=True)
                (ch_artifact / "power_chapter_prose.txt").write_text(prose, encoding="utf-8")
            chapter_proses.append(prose)

        # Overall synthesis
        if progress_callback:
            progress_callback("synthesizing_overall")

        try:
            user_msg = _build_power_overall_user_msg(power_prompt, source_metadata, chapter_proses)
            raw = self._call_llm(
                _POWER_MODE_SYSTEM, user_msg, max_tokens=max_tokens,
                artifact_dir=artifact_dir, artifact_label="power_overall",
            )
            final_prose = raw.strip()
        except Exception as exc:
            logger.warning("power overall synthesis failed: %s, concatenating chapter prose", exc)
            final_prose = "\n\n".join(
                f"## Chapter {i+1}\n\n{prose}" for i, prose in enumerate(chapter_proses)
            )

        return _power_stub_result(final_prose)

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        job_options: dict | None = None,
    ) -> dict:
        opts = job_options or {}
        preset = _resolve_preset(opts.get("style_preset"))
        focus_hint = opts.get("focus_hint")
        multiplier = preset.max_tokens_multiplier

        if opts.get("power_mode"):
            # Power mode failures propagate to the pipeline (job marked failed).
            # The user chose power mode deliberately — silently downgrading to
            # structured output would discard their edited brief.
            self._ensure_model_loaded()
            return self._summarize_power(
                source_metadata, transcript_segments, chapters,
                output_languages, artifact_dir, progress_callback, opts,
            )

        fallback = RuleBasedSummaryGenerator(self.settings)
        try:
            self._ensure_model_loaded()
            max_input_chars = self.settings.summarizer_max_input_chars
            strategy = _choose_strategy(chapters, max_input_chars)
            logger.info("summarizer strategy=%s chapters=%d max_input_chars=%d",
                        strategy, len(chapters), max_input_chars)

            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "summarizer_strategy.txt").write_text(strategy, encoding="utf-8")

            # --- Single-shot path ---
            if strategy == "single_shot":
                if progress_callback:
                    progress_callback("summarizing_single_shot")
                return self._single_shot(
                    source_metadata, chapters, output_languages, artifact_dir=artifact_dir,
                    preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                )

            # --- Per-chapter / hierarchical paths ---
            all_chunk_notes: dict[int, list[str]] = {}
            chapter_summaries: list[dict] = []

            if progress_callback:
                progress_callback("summarizing_chunks")

            for ch_idx, chapter in enumerate(chapters):
                seg_chunks = chunk_segments(chapter.get("segments", []), max_input_chars)
                ch_artifact = (artifact_dir / f"ch{ch_idx}") if artifact_dir else None

                if len(seg_chunks) <= 1:
                    # Single chunk — synthesize chapter directly from segment text.
                    text = segments_to_text(seg_chunks[0]) if seg_chunks else chapter.get("text", "")
                    notes = [text]
                else:
                    # Multiple chunks — produce a note per chunk first.
                    notes = []
                    for c_idx, seg_chunk in enumerate(seg_chunks):
                        text = segments_to_text(seg_chunk)
                        try:
                            note = self._summarize_chunk(
                                text, chapter.get("title_hint", ""),
                                c_idx, len(seg_chunks), artifact_dir=ch_artifact,
                                focus_hint=focus_hint, multiplier=multiplier,
                            )
                        except Exception as exc:
                            logger.warning(
                                "mlx chunk note failed for chapter=%d chunk=%d (%s: %s), using raw chunk text",
                                ch_idx,
                                c_idx,
                                type(exc).__name__,
                                exc,
                            )
                            note = text
                        notes.append(note)
                    all_chunk_notes[ch_idx] = notes

                if progress_callback:
                    progress_callback("synthesizing_chapters")

                try:
                    ch_summary = self._synthesize_chapter(
                        chapter, notes, artifact_dir=ch_artifact,
                        preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                    )
                except Exception as exc:
                    logger.warning(
                        "mlx chapter synthesis failed for chapter=%d (%s: %s), using rule-based chapter fallback",
                        ch_idx,
                        type(exc).__name__,
                        exc,
                    )
                    ch_summary = fallback.summarize_chapter(chapter, ch_idx + 1)
                chapter_summaries.append(ch_summary)

            if progress_callback:
                progress_callback("synthesizing_overall")

            try:
                overall = self._synthesize_overall(
                    source_metadata, chapter_summaries, artifact_dir=artifact_dir,
                    preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                )
            except Exception as exc:
                logger.warning(
                    "mlx overall synthesis failed (%s: %s), using rule-based overall fallback",
                    type(exc).__name__,
                    exc,
                )
                overall = fallback.summarize_overall(
                    source_metadata=source_metadata,
                    transcript_segments=transcript_segments,
                    chapter_summaries=chapter_summaries,
                )

            # Save chunk notes artifact.
            if artifact_dir and all_chunk_notes:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "chunk_notes.json").write_text(
                    json.dumps(all_chunk_notes, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            logger.info("summarization complete: strategy=%s chapters=%d", strategy, len(chapter_summaries))
            return {"chapters": chapter_summaries, "overall_summary": overall}

        except Exception as exc:
            logger.warning("MLX summarizer failed (%s: %s), falling back to rule-based",
                           type(exc).__name__, exc)
            return fallback.summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )

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


# ---------------------------------------------------------------------------
# Remote (HTTP) summarizer base — shared by oMLX and DeepSeek
# ---------------------------------------------------------------------------

class _RemoteSummaryGenerator:
    """Shared chunking/hierarchical/power-mode logic for remote LLM providers.

    Subclasses override _call_remote() with provider-specific request body
    and _extract_model_override() with the per-job option key.
    """

    provider_name: str = "remote"
    log_prefix: str = "remote"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---- Subclass hooks ----------------------------------------------------

    def _call_remote(
        self,
        system_msg: str,
        user_msg: str,
        max_tokens: int,
        artifact_dir: Path | None = None,
        artifact_label: str = "",
        model_override: str | None = None,
        json_mode: bool = False,
    ) -> str:
        raise NotImplementedError

    def _extract_model_override(self, opts: dict) -> str | None:
        return None

    # ---- Token budgets -----------------------------------------------------

    def _chunk_note_tokens(self, multiplier: float = 1.0) -> int:
        base = max(512, self.settings.summarizer_max_tokens // 4)
        return int(base * multiplier)

    def _step_tokens(self, multiplier: float = 1.0) -> int:
        base = max(1024, self.settings.summarizer_max_tokens // 2)
        return int(base * multiplier)

    # ---- Step helpers ------------------------------------------------------

    def _summarize_chunk(self, chunk_text: str, chapter_title: str,
                         chunk_index: int, total_chunks: int,
                         artifact_dir: Path | None = None,
                         focus_hint: str | None = None,
                         multiplier: float = 1.0,
                         model_override: str | None = None) -> str:
        user_msg = _build_chunk_note_user(chunk_text, chapter_title, chunk_index, total_chunks, focus_hint=focus_hint)
        raw = self._call_remote(
            _CHUNK_NOTE_SYSTEM, user_msg, max_tokens=self._chunk_note_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label=f"chunk_{chunk_index}",
            model_override=model_override, json_mode=False,
        )
        return raw.strip()

    def _synthesize_chapter(self, chapter: dict, chunk_notes: list[str],
                            artifact_dir: Path | None = None,
                            preset: StylePreset | None = None,
                            focus_hint: str | None = None,
                            multiplier: float = 1.0,
                            model_override: str | None = None) -> dict:
        system_msg = _build_chapter_synthesis_system(preset)
        user_msg = _build_chapter_synthesis_user(chapter, chunk_notes, focus_hint=focus_hint)
        raw = self._call_remote(
            system_msg, user_msg, max_tokens=self._step_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label="chapter_synthesis",
            model_override=model_override, json_mode=True,
        )
        return parse_model_json(raw, required_keys={"start_s", "end_s", "title", "summary_en", "summary_zh", "key_points"})

    def _synthesize_overall(self, source_metadata: dict,
                            chapter_summaries: list[dict],
                            artifact_dir: Path | None = None,
                            preset: StylePreset | None = None,
                            focus_hint: str | None = None,
                            multiplier: float = 1.0,
                            model_override: str | None = None) -> dict:
        system_msg = _build_overall_synthesis_system(preset)
        user_msg = _build_overall_synthesis_user(source_metadata, chapter_summaries, focus_hint=focus_hint)
        raw = self._call_remote(
            system_msg, user_msg, max_tokens=self._step_tokens(multiplier),
            artifact_dir=artifact_dir, artifact_label="overall_synthesis",
            model_override=model_override, json_mode=True,
        )
        return parse_model_json(raw, required_keys={"summary_en", "summary_zh", "highlights"})

    def _single_shot(
        self,
        source_metadata: dict,
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
        preset: StylePreset | None = None,
        focus_hint: str | None = None,
        multiplier: float = 1.0,
        model_override: str | None = None,
    ) -> dict:
        system_msg, user_msg = build_summarizer_prompt(
            self.settings, source_metadata, chapters, output_languages,
            preset=preset, focus_hint=focus_hint,
        )
        max_tokens = compute_max_tokens(self.settings, len(chapters), multiplier)
        raw = self._call_remote(
            system_msg, user_msg, max_tokens=max_tokens,
            artifact_dir=artifact_dir, artifact_label="single_shot",
            model_override=model_override, json_mode=True,
        )
        parsed = parse_model_json(raw, required_keys={"chapters", "overall_summary"})
        return _validate_single_shot_payload(parsed, expected_chapters=len(chapters))

    def _summarize_power(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path],
        progress_callback: Optional[Callable[[str], None]],
        opts: dict,
    ) -> dict:
        preset = _resolve_preset(opts.get("style_preset"))
        focus_hint = opts.get("focus_hint")
        multiplier = preset.max_tokens_multiplier
        model_override = self._extract_model_override(opts)
        power_prompt = opts.get("power_prompt") or build_power_default_brief(
            opts.get("style_preset"), focus_hint,
        )
        strategy_override = opts.get("strategy_override", "auto")
        max_input_chars = self.settings.summarizer_max_input_chars

        if strategy_override == "force_single_shot":
            strategy = "single_shot"
            total_chars = sum(len(ch.get("text", "")) for ch in chapters)
            if total_chars > max_input_chars:
                logger.warning(
                    "power force_single_shot: transcript %d chars exceeds max_input_chars %d",
                    total_chars, max_input_chars,
                )
        else:
            strategy = _choose_strategy(chapters, max_input_chars, _POWER_SINGLE_SHOT_UTILISATION)

        logger.info("%s power mode strategy=%s chapters=%d", self.log_prefix, strategy, len(chapters))
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "summarizer_strategy.txt").write_text(f"power_{strategy}", encoding="utf-8")

        max_tokens = compute_max_tokens(self.settings, len(chapters), multiplier)

        if strategy == "single_shot":
            if progress_callback:
                progress_callback("summarizing_single_shot")
            user_msg = _build_power_user_msg(power_prompt, source_metadata, chapters)
            raw = self._call_remote(
                _POWER_MODE_SYSTEM, user_msg, max_tokens=max_tokens,
                artifact_dir=artifact_dir, artifact_label="power_single_shot",
                model_override=model_override, json_mode=False,
            )
            return _power_stub_result(raw.strip())

        fallback = RuleBasedSummaryGenerator(self.settings)
        chapter_proses: list[str] = []

        if progress_callback:
            progress_callback("summarizing_chunks")

        for ch_idx, chapter in enumerate(chapters):
            ch_artifact = (artifact_dir / f"ch{ch_idx}") if artifact_dir else None
            seg_chunks = chunk_segments(chapter.get("segments", []), max_input_chars)

            if len(seg_chunks) > 1:
                notes = []
                for c_idx, seg_chunk in enumerate(seg_chunks):
                    text = segments_to_text(seg_chunk)
                    try:
                        note = self._summarize_chunk(
                            text, chapter.get("title_hint", ""),
                            c_idx, len(seg_chunks), artifact_dir=ch_artifact,
                            focus_hint=focus_hint, multiplier=multiplier,
                            model_override=model_override,
                        )
                    except Exception as exc:
                        logger.warning(
                            "%s power chunk note failed ch=%d chunk=%d: %s",
                            self.log_prefix, ch_idx, c_idx, exc,
                        )
                        note = text
                    notes.append(note)
                chapter_text = "\n\n".join(notes)
            else:
                chapter_text = chapter.get("text", "")

            if progress_callback:
                progress_callback("synthesizing_chapters")

            try:
                user_msg = _build_power_chapter_user_msg(
                    power_prompt, {**chapter, "text": chapter_text},
                    ch_idx, len(chapters),
                )
                raw = self._call_remote(
                    _POWER_MODE_SYSTEM, user_msg, max_tokens=self._step_tokens(multiplier),
                    artifact_dir=ch_artifact, artifact_label="power_chapter",
                    model_override=model_override, json_mode=False,
                )
                prose = raw.strip()
            except Exception as exc:
                logger.warning(
                    "%s power chapter synthesis failed ch=%d: %s, using rule-based fallback",
                    self.log_prefix, ch_idx, exc,
                )
                ch_summary = fallback.summarize_chapter(chapter, ch_idx + 1)
                prose = _format_rule_based_chapter_as_prose(ch_summary)

            if ch_artifact:
                ch_artifact.mkdir(parents=True, exist_ok=True)
                (ch_artifact / "power_chapter_prose.txt").write_text(prose, encoding="utf-8")
            chapter_proses.append(prose)

        if progress_callback:
            progress_callback("synthesizing_overall")

        try:
            user_msg = _build_power_overall_user_msg(power_prompt, source_metadata, chapter_proses)
            raw = self._call_remote(
                _POWER_MODE_SYSTEM, user_msg, max_tokens=max_tokens,
                artifact_dir=artifact_dir, artifact_label="power_overall",
                model_override=model_override, json_mode=False,
            )
            final_prose = raw.strip()
        except Exception as exc:
            logger.warning(
                "%s power overall synthesis failed: %s, concatenating chapter prose",
                self.log_prefix, exc,
            )
            final_prose = "\n\n".join(
                f"## Chapter {i+1}\n\n{prose}" for i, prose in enumerate(chapter_proses)
            )

        return _power_stub_result(final_prose)

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        job_options: dict | None = None,
    ) -> dict:
        opts = job_options or {}
        preset = _resolve_preset(opts.get("style_preset"))
        focus_hint = opts.get("focus_hint")
        multiplier = preset.max_tokens_multiplier
        model_override = self._extract_model_override(opts)

        if opts.get("power_mode"):
            return self._summarize_power(
                source_metadata, transcript_segments, chapters,
                output_languages, artifact_dir, progress_callback, opts,
            )

        fallback = RuleBasedSummaryGenerator(self.settings)
        try:
            max_input_chars = self.settings.summarizer_max_input_chars
            strategy = _choose_strategy(chapters, max_input_chars)
            logger.info(
                "%s summarizer strategy=%s chapters=%d max_input_chars=%d",
                self.log_prefix, strategy, len(chapters), max_input_chars,
            )

            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "summarizer_strategy.txt").write_text(strategy, encoding="utf-8")

            if strategy == "single_shot":
                if progress_callback:
                    progress_callback("summarizing_single_shot")
                return self._single_shot(
                    source_metadata, chapters, output_languages, artifact_dir=artifact_dir,
                    preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                    model_override=model_override,
                )

            all_chunk_notes: dict[int, list[str]] = {}
            chapter_summaries: list[dict] = []

            if progress_callback:
                progress_callback("summarizing_chunks")

            for ch_idx, chapter in enumerate(chapters):
                seg_chunks = chunk_segments(chapter.get("segments", []), max_input_chars)
                ch_artifact = (artifact_dir / f"ch{ch_idx}") if artifact_dir else None

                if len(seg_chunks) <= 1:
                    text = segments_to_text(seg_chunks[0]) if seg_chunks else chapter.get("text", "")
                    notes = [text]
                else:
                    notes = []
                    for c_idx, seg_chunk in enumerate(seg_chunks):
                        text = segments_to_text(seg_chunk)
                        try:
                            note = self._summarize_chunk(
                                text, chapter.get("title_hint", ""),
                                c_idx, len(seg_chunks), artifact_dir=ch_artifact,
                                focus_hint=focus_hint, multiplier=multiplier,
                                model_override=model_override,
                            )
                        except Exception as exc:
                            logger.warning(
                                "%s chunk note failed for chapter=%d chunk=%d (%s: %s), using raw chunk text",
                                self.log_prefix, ch_idx, c_idx, type(exc).__name__, exc,
                            )
                            note = text
                        notes.append(note)
                    all_chunk_notes[ch_idx] = notes

                if progress_callback:
                    progress_callback("synthesizing_chapters")

                try:
                    ch_summary = self._synthesize_chapter(
                        chapter, notes, artifact_dir=ch_artifact,
                        preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                        model_override=model_override,
                    )
                except Exception as exc:
                    logger.warning(
                        "%s chapter synthesis failed for chapter=%d (%s: %s), using rule-based chapter fallback",
                        self.log_prefix, ch_idx, type(exc).__name__, exc,
                    )
                    ch_summary = fallback.summarize_chapter(chapter, ch_idx + 1)
                chapter_summaries.append(ch_summary)

            if progress_callback:
                progress_callback("synthesizing_overall")

            try:
                overall = self._synthesize_overall(
                    source_metadata, chapter_summaries, artifact_dir=artifact_dir,
                    preset=preset, focus_hint=focus_hint, multiplier=multiplier,
                    model_override=model_override,
                )
            except Exception as exc:
                logger.warning(
                    "%s overall synthesis failed (%s: %s), using rule-based overall fallback",
                    self.log_prefix, type(exc).__name__, exc,
                )
                overall = fallback.summarize_overall(
                    source_metadata=source_metadata,
                    transcript_segments=transcript_segments,
                    chapter_summaries=chapter_summaries,
                )

            if artifact_dir and all_chunk_notes:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "chunk_notes.json").write_text(
                    json.dumps(all_chunk_notes, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            logger.info(
                "%s summarization complete: strategy=%s chapters=%d",
                self.log_prefix, strategy, len(chapter_summaries),
            )
            return {"chapters": chapter_summaries, "overall_summary": overall}

        except Exception as exc:
            logger.warning(
                "%s summarizer failed (%s: %s), falling back to rule-based",
                self.log_prefix, type(exc).__name__, exc,
            )
            return fallback.summarize(
                source_metadata=source_metadata,
                transcript_segments=transcript_segments,
                chapters=chapters,
                output_languages=output_languages,
            )


# ---------------------------------------------------------------------------
# OMLX remote summarizer (OpenAI-compatible)
# ---------------------------------------------------------------------------

class OmlxSummaryGenerator(_RemoteSummaryGenerator):
    provider_name = "omlx"
    log_prefix = "omlx"

    def _extract_model_override(self, opts: dict) -> str | None:
        return opts.get("omlx_model_override") or None

    def _call_remote(self, *args, **kwargs):
        # Delegate so subclass-style patching of `_call_omlx` continues to work.
        return self._call_omlx(*args, **kwargs)

    def _call_omlx(
        self,
        system_msg: str,
        user_msg: str,
        max_tokens: int,
        artifact_dir: Path | None = None,
        artifact_label: str = "",
        model_override: str | None = None,
        json_mode: bool = False,
    ) -> str:
        import httpx

        label = f"_{artifact_label}" if artifact_label else ""
        model = model_override or self.settings.omlx_model

        request_body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            prompt_text = f"=== SYSTEM ===\n{system_msg}\n\n=== USER ===\n{user_msg}"
            (artifact_dir / f"summarizer{label}_prompt.txt").write_text(prompt_text, encoding="utf-8")
            (artifact_dir / f"summarizer{label}_request.json").write_text(
                json.dumps(request_body, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        url = f"{self.settings.omlx_base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.omlx_api_key:
            headers["Authorization"] = f"Bearer {self.settings.omlx_api_key}"

        logger.info("omlx request%s: url=%s model=%s max_tokens=%d", label, url, model, max_tokens)
        t0 = time.perf_counter()
        response = httpx.post(
            url,
            json=request_body,
            headers=headers,
            timeout=self.settings.omlx_timeout_seconds,
        )
        elapsed = time.perf_counter() - t0
        logger.info("omlx response%s: status=%d elapsed=%.1fs", label, response.status_code, elapsed)

        response.raise_for_status()
        data = response.json()
        raw_output = data["choices"][0]["message"]["content"]

        if artifact_dir:
            (artifact_dir / f"summarizer{label}_raw_output.txt").write_text(raw_output, encoding="utf-8")

        return raw_output


# ---------------------------------------------------------------------------
# DeepSeek remote summarizer (OpenAI-compatible API)
# ---------------------------------------------------------------------------

class DeepseekSummaryGenerator(_RemoteSummaryGenerator):
    provider_name = "deepseek"
    log_prefix = "deepseek"

    def _extract_model_override(self, opts: dict) -> str | None:
        return opts.get("deepseek_model") or None

    def _call_remote(
        self,
        system_msg: str,
        user_msg: str,
        max_tokens: int,
        artifact_dir: Path | None = None,
        artifact_label: str = "",
        model_override: str | None = None,
        json_mode: bool = False,
    ) -> str:
        import httpx

        label = f"_{artifact_label}" if artifact_label else ""
        model = model_override or self.settings.deepseek_model

        request_body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            request_body["response_format"] = {"type": "json_object"}

        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            prompt_text = f"=== SYSTEM ===\n{system_msg}\n\n=== USER ===\n{user_msg}"
            (artifact_dir / f"summarizer{label}_prompt.txt").write_text(prompt_text, encoding="utf-8")
            (artifact_dir / f"summarizer{label}_request.json").write_text(
                json.dumps(request_body, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        url = f"{self.settings.deepseek_base_url}/chat/completions"
        # API key is sent via Authorization but never logged or persisted.
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
        }

        logger.info("deepseek request%s: url=%s model=%s max_tokens=%d json_mode=%s",
                    label, url, model, max_tokens, json_mode)
        t0 = time.perf_counter()
        response = httpx.post(
            url,
            json=request_body,
            headers=headers,
            timeout=self.settings.deepseek_timeout_seconds,
        )
        elapsed = time.perf_counter() - t0
        logger.info("deepseek response%s: status=%d elapsed=%.1fs", label, response.status_code, elapsed)

        response.raise_for_status()
        data = response.json()
        raw_output = data["choices"][0]["message"]["content"]

        if artifact_dir:
            (artifact_dir / f"summarizer{label}_raw_output.txt").write_text(raw_output, encoding="utf-8")

        return raw_output


# ---------------------------------------------------------------------------
# Routing summarizer — dispatches per-job to oMLX or DeepSeek
# ---------------------------------------------------------------------------

class RoutingSummaryGenerator:
    """Picks the per-job remote provider, falling back to the configured default."""

    def __init__(self, default_generator, providers: dict[str, object]) -> None:
        self._default = default_generator
        self._providers = providers

    @property
    def default(self):
        return self._default

    def _select(self, job_options: dict | None):
        opts = job_options or {}
        override = opts.get("summarizer_provider_override")
        if override and override in self._providers:
            return self._providers[override]
        return self._default

    def summarize(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapters: list[dict],
        output_languages: list[str],
        artifact_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        job_options: dict | None = None,
    ) -> dict:
        generator = self._select(job_options)
        return generator.summarize(
            source_metadata=source_metadata,
            transcript_segments=transcript_segments,
            chapters=chapters,
            output_languages=output_languages,
            artifact_dir=artifact_dir,
            progress_callback=progress_callback,
            job_options=job_options,
        )


# ---------------------------------------------------------------------------
# Rule-based fallback summarizer
# ---------------------------------------------------------------------------

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
        progress_callback: Optional[Callable[[str], None]] = None,
        job_options: dict | None = None,
    ) -> dict:
        chapter_summaries = []
        for index, chapter in enumerate(chapters, start=1):
            chapter_summaries.append(self.summarize_chapter(chapter, index))

        overall = self.summarize_overall(
            source_metadata=source_metadata,
            transcript_segments=transcript_segments,
        )
        return {
            "chapters": chapter_summaries,
            "overall_summary": overall,
        }

    def summarize_chapter(self, chapter: dict, index: int) -> dict:
        sentences = self._extract_sentences(chapter["text"], limit=2)
        summary_en = " ".join(sentences) if sentences else chapter["title_hint"]
        return {
            "start_s": chapter["start_s"],
            "end_s": chapter["end_s"],
            "title": chapter["title_hint"] or f"Chapter {index}",
            "summary_en": summary_en,
            "summary_zh": f"第{index}部分：{summary_en}",
            "key_points": sentences or [chapter["title_hint"]],
        }

    def summarize_overall(
        self,
        source_metadata: dict,
        transcript_segments: list[dict],
        chapter_summaries: list[dict] | None = None,
    ) -> dict:
        if chapter_summaries:
            all_text = " ".join(chapter.get("summary_en", "") for chapter in chapter_summaries)
        else:
            all_text = " ".join(segment["text"] for segment in transcript_segments)
        overall_sentences = self._extract_sentences(all_text, limit=3)
        overall_en = (
            " ".join(overall_sentences)
            if overall_sentences
            else source_metadata.get("title", "Summary unavailable.")
        )
        return {
            "summary_en": overall_en,
            "summary_zh": f"整体总结：{overall_en}",
            "highlights": overall_sentences or [source_metadata.get("title", "Untitled video")],
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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _omlx_configured(settings: Settings) -> bool:
    return bool(settings.omlx_base_url and settings.omlx_model)


def _deepseek_configured(settings: Settings) -> bool:
    return bool(settings.deepseek_api_key)


def _build_provider(settings: Settings, provider: str):
    if provider == "omlx":
        try:
            import httpx  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "httpx is not installed. Run `uv sync --extra omlx` to enable OMLX summarization."
            )
        logger.info("summarizer provider: omlx (url=%s model=%s)", settings.omlx_base_url, settings.omlx_model)
        return OmlxSummaryGenerator(settings)
    if provider == "deepseek":
        try:
            import httpx  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "httpx is not installed. Run `uv sync --extra omlx` to enable DeepSeek summarization."
            )
        logger.info(
            "summarizer provider: deepseek (url=%s model=%s)",
            settings.deepseek_base_url, settings.deepseek_model,
        )
        return DeepseekSummaryGenerator(settings)
    if provider == "mlx":
        logger.info("summarizer provider: mlx (model=%s)", settings.summarizer_model)
        return MlxQwenSummaryGenerator(settings)
    logger.info("summarizer provider: fallback (rule-based)")
    return RuleBasedSummaryGenerator(settings)


def create_summary_generator(settings: Settings):
    """Return the appropriate SummaryGenerator based on settings.

    When more than one remote provider is configured, the result is wrapped in
    a RoutingSummaryGenerator so per-job ``summarizer_provider_override`` can
    pick between them. Otherwise the configured default is returned directly.
    """
    default = _build_provider(settings, settings.summarizer_provider)

    available: dict[str, object] = {}
    if _omlx_configured(settings):
        available["omlx"] = (
            default if isinstance(default, OmlxSummaryGenerator) else _build_provider(settings, "omlx")
        )
    if _deepseek_configured(settings):
        available["deepseek"] = (
            default if isinstance(default, DeepseekSummaryGenerator) else _build_provider(settings, "deepseek")
        )

    if len(available) >= 2:
        return RoutingSummaryGenerator(default, available)
    return default
