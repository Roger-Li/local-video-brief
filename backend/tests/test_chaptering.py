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

