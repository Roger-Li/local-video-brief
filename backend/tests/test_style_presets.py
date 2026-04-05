from __future__ import annotations

from backend.app.core.style_presets import STYLE_PRESETS, StylePreset


def test_all_presets_have_required_fields() -> None:
    required = {"id", "label", "description", "system_suffix", "chapter_length",
                "single_shot_chapter_length", "overall_length", "max_tokens_multiplier"}
    for preset_id, preset in STYLE_PRESETS.items():
        assert isinstance(preset, StylePreset), f"{preset_id} is not a StylePreset"
        for field in required:
            assert hasattr(preset, field), f"{preset_id} missing field: {field}"


def test_default_preset_values() -> None:
    p = STYLE_PRESETS["default"]
    assert p.system_suffix == ""
    assert p.chapter_length == "2-4"
    assert p.single_shot_chapter_length == "3-5"
    assert p.overall_length == "3-5"
    assert p.max_tokens_multiplier == 1.0


def test_all_multipliers_are_positive() -> None:
    for preset_id, preset in STYLE_PRESETS.items():
        assert preset.max_tokens_multiplier > 0, f"{preset_id} has non-positive multiplier"


def test_length_fields_are_nonempty_strings() -> None:
    for preset_id, preset in STYLE_PRESETS.items():
        assert isinstance(preset.chapter_length, str) and preset.chapter_length, f"{preset_id} chapter_length empty"
        assert isinstance(preset.single_shot_chapter_length, str) and preset.single_shot_chapter_length, f"{preset_id} single_shot_chapter_length empty"
        assert isinstance(preset.overall_length, str) and preset.overall_length, f"{preset_id} overall_length empty"


def test_non_default_presets_unify_chapter_lengths() -> None:
    for preset_id, preset in STYLE_PRESETS.items():
        if preset_id == "default":
            continue
        assert preset.chapter_length == preset.single_shot_chapter_length, (
            f"{preset_id}: chapter_length ({preset.chapter_length}) != "
            f"single_shot_chapter_length ({preset.single_shot_chapter_length})"
        )


def test_no_preset_suffix_mentions_structural_format() -> None:
    structural_keywords = ["json", "schema", "format", "field", "key_points", "summary_en"]
    for preset_id, preset in STYLE_PRESETS.items():
        suffix_lower = preset.system_suffix.lower()
        for kw in structural_keywords:
            assert kw not in suffix_lower, (
                f"{preset_id} system_suffix mentions structural keyword '{kw}'"
            )
