from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Bracketed markers to strip (case-insensitive exact match inside brackets).
_SOUND_BLOCKLIST = frozenset({
    "music", "applause", "cheering", "♪", "♫",
    "music playing", "applause and cheering",
})

_BRACKET_RE = re.compile(r"\[([^\]]*)\]")


@dataclass
class NormalizationStats:
    raw_segment_count: int = 0
    normalized_segment_count: int = 0
    cleaned_markup_count: int = 0
    merged_or_deduped_count: int = 0
    normalization_applied: bool = True
    normalization_fallback_used: bool = False
    source_mode: str = "captions"


def _tokenize(text: str) -> list[str]:
    """Whitespace-normalize and split into tokens for overlap comparison."""
    return re.sub(r"\s+", " ", text).strip().lower().split()


def _longest_suffix_prefix_overlap(tokens_a: list[str], tokens_b: list[str]) -> int:
    """Return the length of the longest overlap between suffix of *tokens_a*
    and prefix of *tokens_b*."""
    max_overlap = min(len(tokens_a), len(tokens_b))
    for length in range(max_overlap, 0, -1):
        if tokens_a[-length:] == tokens_b[:length]:
            return length
    return 0


def _strip_sound_markers(text: str) -> str:
    """Remove blocklisted bracketed markers; preserve all others."""
    def _replace(m: re.Match) -> str:
        inner = m.group(1).strip().lower()
        if inner in _SOUND_BLOCKLIST:
            return ""
        return m.group(0)
    return _BRACKET_RE.sub(_replace, text)


def _clean_text(text: str) -> str:
    """Light text cleanup applied to every segment."""
    text = _strip_sound_markers(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TranscriptNormalizer:
    """Normalizes parsed transcript segments.

    Operates on the unified segment dicts produced by VttTranscriptProvider
    or MlxWhisperAsrService — each dict has at minimum:
    ``start_s``, ``end_s``, ``text``, ``source``.
    """

    # Tuning knobs ----------------------------------------------------------
    MAX_MERGE_GAP_S: float = 2.0
    MIN_OVERLAP_TOKENS: int = 2
    MIN_OVERLAP_RATIO: float = 0.75
    SHORT_FRAGMENT_MAX_WORDS: int = 2

    def normalize(
        self,
        segments: list[dict],
    ) -> tuple[list[dict], NormalizationStats]:
        stats = NormalizationStats(raw_segment_count=len(segments))

        if not segments:
            stats.normalized_segment_count = 0
            return [], stats

        # Determine job-level source_mode.
        sources = {seg.get("source", "captions") for seg in segments}
        if sources == {"captions"}:
            stats.source_mode = "captions"
        elif sources == {"asr"}:
            stats.source_mode = "asr"
        else:
            stats.source_mode = "mixed"

        # Phase 1: per-segment text cleanup.
        cleaned: list[dict] = []
        for seg in segments:
            new_text = _clean_text(seg["text"])
            if new_text != seg["text"]:
                stats.cleaned_markup_count += 1
            if not new_text:
                continue
            cleaned.append({**seg, "text": new_text})

        # Phase 2: rolling-caption dedup (captions only).
        deduped = self._dedup_rolling_captions(cleaned, stats)

        # Phase 3: merge ultra-short fragments.
        merged = self._merge_short_fragments(deduped, stats)

        stats.normalized_segment_count = len(merged)

        # Fallback: if normalization eliminated everything, fall back to
        # the original raw segments to avoid losing the transcript entirely.
        if not merged and segments:
            fallback = cleaned if cleaned else [{**s} for s in segments]
            logger.warning(
                "normalization produced 0 segments; falling back to %s (%d segments)",
                "cleaned" if cleaned else "raw", len(fallback),
            )
            stats.normalization_fallback_used = True
            stats.normalized_segment_count = len(fallback)
            return fallback, stats

        return merged, stats

    # ------------------------------------------------------------------
    # Rolling-caption dedup
    # ------------------------------------------------------------------
    def _dedup_rolling_captions(
        self,
        segments: list[dict],
        stats: NormalizationStats,
    ) -> list[dict]:
        if not segments:
            return []

        result: list[dict] = []
        acc = dict(segments[0])  # mutable accumulator for current merged segment

        for seg in segments[1:]:
            # Only dedup caption-sourced segments.
            if acc.get("source") != "captions" or seg.get("source") != "captions":
                result.append(acc)
                acc = dict(seg)
                continue

            gap = seg["start_s"] - acc["end_s"]
            if gap > self.MAX_MERGE_GAP_S:
                result.append(acc)
                acc = dict(seg)
                continue

            tokens_acc = _tokenize(acc["text"])
            tokens_seg = _tokenize(seg["text"])

            if not tokens_acc or not tokens_seg:
                result.append(acc)
                acc = dict(seg)
                continue

            overlap = _longest_suffix_prefix_overlap(tokens_acc, tokens_seg)
            shorter_len = min(len(tokens_acc), len(tokens_seg))
            ratio = overlap / shorter_len if shorter_len else 0.0

            # Also check if the seg's prefix appears as a substring of the
            # accumulated text — catches sliding-window captions where
            # overlap ratio against the shorter list is below the strict
            # threshold but the repeated phrase is clearly duplicated.
            prefix_in_acc = False
            if overlap < self.MIN_OVERLAP_TOKENS or ratio < self.MIN_OVERLAP_RATIO:
                seg_prefix = " ".join(tokens_seg[:len(tokens_seg) // 2 + 1])
                if len(seg_prefix.split()) >= 2 and seg_prefix in " ".join(tokens_acc):
                    prefix_in_acc = True

            if (overlap >= self.MIN_OVERLAP_TOKENS and ratio >= self.MIN_OVERLAP_RATIO) or prefix_in_acc:
                # Rolling continuation — append only the non-overlapping suffix.
                # When prefix_in_acc triggered the merge but suffix/prefix overlap
                # was low, find the actual overlap by scanning for the longest
                # prefix of seg that appears at the end of acc.
                effective_overlap = overlap
                if prefix_in_acc and overlap < self.MIN_OVERLAP_TOKENS:
                    for k in range(min(len(tokens_acc), len(tokens_seg)), 0, -1):
                        if tokens_seg[:k] == tokens_acc[-k:]:
                            effective_overlap = k
                            break
                    else:
                        # Prefix is a substring but not at the suffix boundary —
                        # find how many leading seg tokens are contained in acc.
                        for k in range(len(tokens_seg), 0, -1):
                            candidate = " ".join(tokens_seg[:k])
                            if candidate in " ".join(tokens_acc):
                                effective_overlap = k
                                break
                suffix_tokens = seg["text"].split()[effective_overlap:]
                if suffix_tokens:
                    acc["text"] = acc["text"] + " " + " ".join(suffix_tokens)
                # If the new segment is a pure prefix expansion (no new tokens),
                # keep the longer phrasing.
                if len(tokens_seg) > len(tokens_acc) and not suffix_tokens:
                    acc["text"] = seg["text"]
                acc["end_s"] = max(acc["end_s"], seg["end_s"])
                stats.merged_or_deduped_count += 1
            else:
                # Check if the new segment is a complete subset of the
                # accumulated text (pure duplicate / shorter prefix).
                seg_normalized = " ".join(tokens_seg)
                acc_normalized = " ".join(tokens_acc)
                if seg_normalized in acc_normalized:
                    acc["end_s"] = max(acc["end_s"], seg["end_s"])
                    stats.merged_or_deduped_count += 1
                else:
                    result.append(acc)
                    acc = dict(seg)

        result.append(acc)
        return result

    # ------------------------------------------------------------------
    # Short-fragment merge
    # ------------------------------------------------------------------
    def _merge_short_fragments(
        self,
        segments: list[dict],
        stats: NormalizationStats,
    ) -> list[dict]:
        if len(segments) <= 1:
            return list(segments)

        result: list[dict] = [dict(segments[0])]
        for seg in segments[1:]:
            word_count = len(seg["text"].split())
            prev = result[-1]
            gap = seg["start_s"] - prev["end_s"]

            if (
                word_count <= self.SHORT_FRAGMENT_MAX_WORDS
                and gap <= self.MAX_MERGE_GAP_S
                and seg.get("source") != "asr"
                and prev.get("source") != "asr"
            ):
                # Strip any overlapping prefix to avoid duplication
                # (e.g. prev="Hello", seg="Hello world" → append only "world").
                prev_tokens = _tokenize(prev["text"])
                seg_tokens = _tokenize(seg["text"])
                overlap = _longest_suffix_prefix_overlap(prev_tokens, seg_tokens)
                suffix_words = seg["text"].split()[overlap:]
                if suffix_words:
                    prev["text"] = prev["text"] + " " + " ".join(suffix_words)
                elif len(seg_tokens) > len(prev_tokens):
                    # seg is a longer expansion — keep it entirely.
                    prev["text"] = seg["text"]
                prev["end_s"] = max(prev["end_s"], seg["end_s"])
                stats.merged_or_deduped_count += 1
            else:
                result.append(dict(seg))

        return result
