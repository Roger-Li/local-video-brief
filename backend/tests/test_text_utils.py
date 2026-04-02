from __future__ import annotations

from backend.app.utils.text import chunk_segments, segments_to_text


def _seg(text: str, start: float = 0.0, end: float = 1.0) -> dict:
    return {"text": text, "start_s": start, "end_s": end}


def test_chunk_segments_respects_boundaries():
    segs = [_seg("aaa"), _seg("bbb"), _seg("ccc"), _seg("ddd")]
    # Budget accounts for joining spaces: "aaa bbb" = 7 chars
    chunks = chunk_segments(segs, max_chars=7)
    assert len(chunks) == 2
    assert chunks[0] == [segs[0], segs[1]]
    assert chunks[1] == [segs[2], segs[3]]


def test_chunk_segments_single_large_segment():
    big = _seg("x" * 100)
    small = _seg("y")
    chunks = chunk_segments([big, small], max_chars=10)
    # Oversized segment is its own chunk.
    assert len(chunks) == 2
    assert chunks[0] == [big]
    assert chunks[1] == [small]


def test_chunk_segments_small_input_single_chunk():
    segs = [_seg("a"), _seg("b"), _seg("c")]
    chunks = chunk_segments(segs, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0] == segs


def test_chunk_segments_empty_input():
    assert chunk_segments([], max_chars=100) == []


def test_segments_to_text():
    segs = [_seg("hello"), _seg("world")]
    assert segments_to_text(segs) == "hello world"


def test_segments_to_text_empty():
    assert segments_to_text([]) == ""
