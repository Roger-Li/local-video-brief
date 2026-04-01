from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.services.chaptering import HeuristicChapterer


def test_chapterer_splits_on_large_gaps() -> None:
    chapterer = HeuristicChapterer(Settings())
    transcript = [
        {"start_s": 0.0, "end_s": 20.0, "text": "Intro segment"},
        {"start_s": 21.0, "end_s": 40.0, "text": "Still intro"},
        {"start_s": 100.0, "end_s": 120.0, "text": "New section"},
    ]

    chapters = chapterer.build_chapters(transcript)

    assert len(chapters) == 2
    assert chapters[0]["start_s"] == 0.0
    assert chapters[1]["start_s"] == 100.0


def _dense_segments(n: int, words_per: int = 25) -> list[dict]:
    """Generate *n* continuous segments each ~5s long with *words_per* words."""
    segments = []
    for i in range(n):
        text = " ".join(f"word{i}_{j}" for j in range(words_per))
        segments.append({
            "start_s": i * 5.0,
            "end_s": (i + 1) * 5.0 - 0.1,
            "text": text,
        })
    return segments


def test_density_repartition_splits_single_dense_chapter() -> None:
    """A dense single-chapter transcript >= 180s and >= 300 words should split."""
    chapterer = HeuristicChapterer(Settings())
    # 80 segments * 5s = 400s, 80 * 25 words = 2000 words.
    segments = _dense_segments(80)
    chapters = chapterer.build_chapters(segments)
    assert len(chapters) >= 2
    # Verify ordering is preserved.
    for i in range(len(chapters) - 1):
        assert chapters[i]["end_s"] <= chapters[i + 1]["start_s"] + 0.01


def test_short_sparse_video_stays_single_chapter() -> None:
    """A short/sparse transcript should remain a single chapter."""
    chapterer = HeuristicChapterer(Settings())
    # 5 segments * 5s = 25s total, well under 180s threshold.
    segments = _dense_segments(5)
    chapters = chapterer.build_chapters(segments)
    assert len(chapters) == 1


def test_already_multi_chapter_skips_repartition() -> None:
    """If gap-based splitting already produces multiple chapters, no repartition."""
    chapterer = HeuristicChapterer(Settings())
    segments = [
        {"start_s": 0.0, "end_s": 90.0, "text": "First section " * 50},
        {"start_s": 200.0, "end_s": 300.0, "text": "Second section " * 50},
    ]
    chapters = chapterer.build_chapters(segments)
    assert len(chapters) == 2

