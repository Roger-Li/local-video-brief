#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}(?:[–-]\d{2}:\d{2})\]")
LOG_WARNING_RE = re.compile(r"\b(WARNING|ERROR)\b|fallback|timed out", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a real e2e smoke-test result for local-video-brief.",
    )
    parser.add_argument("--result", required=True, help="Path to the saved *-result.json file.")
    parser.add_argument("--backend-log", help="Optional backend log path for warning/error checks.")
    parser.add_argument("--expect-study-pack", action="store_true", help="Require study_pack to be present.")
    parser.add_argument(
        "--allow-section-refinement",
        action="store_true",
        help="Allow study_pack.sections to differ from chapter count.",
    )
    parser.add_argument(
        "--expect-timestamp-markdown",
        action="store_true",
        help="Require study_guide.md to include [MM:SS-MM:SS] or [MM:SS–MM:SS] ranges.",
    )
    parser.add_argument(
        "--expect-llm-artifacts",
        action="store_true",
        help="Require hierarchical or single-shot summarizer prompt/raw-output artifacts.",
    )
    parser.add_argument(
        "--expect-omlx-request",
        action="store_true",
        help="Require at least one oMLX request artifact.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_summary_text(label: str, value: Any, failures: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        failures.append(f"{label} is missing or empty")


def validate_list(label: str, value: Any, failures: list[str]) -> list[Any]:
    if not isinstance(value, list):
        failures.append(f"{label} is missing or is not a list")
        return []
    return value


def find_artifact_root(result: dict[str, Any], result_path: Path) -> Path:
    artifacts = result.get("artifacts") or {}
    for key in ("transcript_raw_path", "transcript_normalized_path", "study_pack_path", "study_guide_path"):
        raw_path = artifacts.get(key)
        if isinstance(raw_path, str) and raw_path:
            return Path(raw_path).resolve().parent
    return (result_path.resolve().parents[1] / result.get("job_id", "")).resolve()


def check_required_file(label: str, raw_path: Any, failures: list[str]) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        failures.append(f"artifact '{label}' is missing from result.artifacts")
        return None
    path = Path(raw_path)
    if not path.exists():
        failures.append(f"artifact '{label}' does not exist: {path}")
        return None
    return path


def format_range(start_s: float, end_s: float) -> str:
    return f"{int(start_s // 60):02d}:{int(start_s % 60):02d}-{int(end_s // 60):02d}:{int(end_s % 60):02d}"


def main() -> int:
    args = parse_args()
    result_path = Path(args.result)
    result = load_json(result_path)
    failures: list[str] = []

    chapters = validate_list("chapters", result.get("chapters"), failures)
    transcript_segments = validate_list("transcript_segments", result.get("transcript_segments"), failures)
    overall_summary = result.get("overall_summary") or {}
    study_pack = result.get("study_pack")
    artifacts = result.get("artifacts") or {}
    artifact_root = find_artifact_root(result, result_path)

    if result.get("status") != "completed":
        failures.append(f"status is {result.get('status')!r}, expected 'completed'")
    if not result.get("job_id"):
        failures.append("job_id is missing")
    if not chapters:
        failures.append("chapters is empty")
    if not transcript_segments:
        failures.append("transcript_segments is empty")

    validate_summary_text("overall_summary.summary_en", overall_summary.get("summary_en"), failures)
    validate_summary_text("overall_summary.summary_zh", overall_summary.get("summary_zh"), failures)
    highlights = validate_list("overall_summary.highlights", overall_summary.get("highlights"), failures)
    if not highlights:
        failures.append("overall_summary.highlights is empty")

    previous_end = -1.0
    for index, chapter in enumerate(chapters):
        start_s = chapter.get("start_s")
        end_s = chapter.get("end_s")
        if not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
            failures.append(f"chapter {index} has invalid timestamps")
            continue
        if end_s < start_s:
            failures.append(f"chapter {index} has end_s < start_s")
        if start_s < previous_end:
            failures.append(f"chapter {index} starts before the previous chapter ends")
        previous_end = float(end_s)
        validate_summary_text(f"chapter {index} title", chapter.get("title"), failures)
        validate_summary_text(f"chapter {index} summary_en", chapter.get("summary_en"), failures)
        validate_summary_text(f"chapter {index} summary_zh", chapter.get("summary_zh"), failures)
        key_points = validate_list(f"chapter {index} key_points", chapter.get("key_points"), failures)
        if not key_points:
            failures.append(f"chapter {index} key_points is empty")

    transcript_raw = check_required_file("transcript_raw_path", artifacts.get("transcript_raw_path"), failures)
    transcript_normalized = check_required_file(
        "transcript_normalized_path", artifacts.get("transcript_normalized_path"), failures,
    )

    study_pack_path: Path | None = None
    study_guide_path: Path | None = None
    if args.expect_study_pack:
        if not isinstance(study_pack, dict):
            failures.append("study_pack is missing or null")
        else:
            if study_pack.get("version") != 1:
                failures.append(f"study_pack.version is {study_pack.get('version')!r}, expected 1")
            if study_pack.get("format") != "lecture_study_guide":
                failures.append(
                    f"study_pack.format is {study_pack.get('format')!r}, expected 'lecture_study_guide'",
                )
            objectives = validate_list("study_pack.learning_objectives", study_pack.get("learning_objectives"), failures)
            sections = validate_list("study_pack.sections", study_pack.get("sections"), failures)
            takeaways = validate_list("study_pack.final_takeaways", study_pack.get("final_takeaways"), failures)
            if not objectives:
                failures.append("study_pack.learning_objectives is empty")
            if not sections:
                failures.append("study_pack.sections is empty")
            if not takeaways:
                failures.append("study_pack.final_takeaways is empty")
            if not args.allow_section_refinement and len(sections) != len(chapters):
                failures.append(
                    f"study_pack.sections count ({len(sections)}) does not match chapters count ({len(chapters)})",
                )

            previous_section_end = -1.0
            for index, section in enumerate(sections):
                start_s = section.get("start_s")
                end_s = section.get("end_s")
                if not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
                    failures.append(f"study_pack section {index} has invalid timestamps")
                    continue
                if end_s < start_s:
                    failures.append(f"study_pack section {index} has end_s < start_s")
                if start_s < previous_section_end:
                    failures.append(f"study_pack section {index} is not monotonic")
                previous_section_end = float(end_s)
                validate_summary_text(f"study_pack section {index} title", section.get("title"), failures)
                validate_summary_text(f"study_pack section {index} summary_en", section.get("summary_en"), failures)
                if section.get("summary_zh"):
                    validate_summary_text(f"study_pack section {index} summary_zh", section.get("summary_zh"), failures)
                section_kp = section.get("key_points")
                if not isinstance(section_kp, list):
                    failures.append(f"study_pack section {index} key_points is not a list")

        study_pack_path = check_required_file("study_pack_path", artifacts.get("study_pack_path"), failures)
        study_guide_path = check_required_file("study_guide_path", artifacts.get("study_guide_path"), failures)
        if args.expect_timestamp_markdown and study_guide_path and study_guide_path.exists():
            markdown = study_guide_path.read_text(encoding="utf-8")
            if not TIMESTAMP_RE.search(markdown):
                failures.append("study_guide.md is missing [MM:SS-MM:SS] timestamp ranges")

    if args.expect_llm_artifacts:
        prompt_candidates = list(artifact_root.glob("summarizer_prompt.txt"))
        prompt_candidates += list(artifact_root.glob("summarizer_single_shot_prompt.txt"))
        prompt_candidates += list(artifact_root.glob("summarizer_overall_synthesis_prompt.txt"))
        prompt_candidates += list(artifact_root.glob("ch*/summarizer_*_prompt.txt"))
        raw_output_candidates = list(artifact_root.glob("summarizer_raw_output.txt"))
        raw_output_candidates += list(artifact_root.glob("summarizer_single_shot_raw_output.txt"))
        raw_output_candidates += list(artifact_root.glob("summarizer_overall_synthesis_raw_output.txt"))
        raw_output_candidates += list(artifact_root.glob("ch*/summarizer_*_raw_output.txt"))
        if not prompt_candidates:
            failures.append(f"no summarizer prompt artifacts found under {artifact_root}")
        if not raw_output_candidates:
            failures.append(f"no summarizer raw output artifacts found under {artifact_root}")

    if args.expect_omlx_request:
        request_candidates = list(artifact_root.glob("summarizer_request.json"))
        request_candidates += list(artifact_root.glob("summarizer_single_shot_request.json"))
        request_candidates += list(artifact_root.glob("ch*/summarizer_*_request.json"))
        if not request_candidates:
            failures.append(f"no oMLX request artifacts found under {artifact_root}")

    warning_lines: list[str] = []
    if args.backend_log:
        backend_log = Path(args.backend_log)
        if not backend_log.exists():
            failures.append(f"backend log does not exist: {backend_log}")
        else:
            warning_lines = [
                line.rstrip()
                for line in backend_log.read_text(encoding="utf-8", errors="replace").splitlines()
                if LOG_WARNING_RE.search(line)
            ]

    print(f"job_id={result.get('job_id', '(missing)')}")
    print(f"result={result_path}")
    print(f"artifact_root={artifact_root}")
    print(f"chapters={len(chapters)} transcript_segments={len(transcript_segments)} highlights={len(highlights)}")
    if chapters:
        first = chapters[0]
        last = chapters[-1]
        print(
            "chapter_span="
            f"{format_range(float(first.get('start_s', 0.0)), float(last.get('end_s', 0.0)))}",
        )
    print(f"study_pack_present={'yes' if isinstance(study_pack, dict) else 'no'}")
    if transcript_raw:
        print(f"transcript_raw={transcript_raw}")
    if transcript_normalized:
        print(f"transcript_normalized={transcript_normalized}")
    if study_pack_path:
        print(f"study_pack_json={study_pack_path}")
    if study_guide_path:
        print(f"study_guide_md={study_guide_path}")
    print(f"log_warnings={len(warning_lines)}")

    if warning_lines:
        print("warnings:")
        for line in warning_lines[:20]:
            print(f"  - {line}")

    if failures:
        print("validation_failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("validation=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
