"""Minimum-effort document validation, precedence and unresolved presentation."""

import copy
import pytest
from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_contracts.level_proposals import (
    published_capability_conflicts,
    unplaced_models,
)
from yoke_contracts.levels import (
    LevelsError,
    default_levels,
    levels_payload,
    parse_levels,
    resolve_effective_levels,
    level_presentation,
    unresolved_level_reason,
)
from yoke_contracts.model_reference_data import MODEL_RECORDS


def document(model="gpt-6.1-sol", effort="medium"):
    return [
        {
            "name": "SENIOR",
            "glyph": "🦉",
            "options": [{"model": model, "min_effort": effort}],
        }
    ]


def test_approved_rows_are_stored_without_native_knobs():
    levels = default_levels()
    assert [level.name for level in levels] == [
        "INTERN",
        "JUNIOR",
        "SENIOR",
        "PRINCIPAL",
    ]
    assert [len(level.options) for level in levels] == [5, 7, 4, 2]
    assert levels_payload(levels) == list(DEFAULT_LEVELS)
    assert all(
        set(entry.payload()) == {"model", "min_effort"}
        for level in levels
        for entry in level.options
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("surface", "codex-cli"),
        ("reasoning_effort", "medium"),
        ("context_window_tokens", None),
        ("fallback", {}),
    ],
)
def test_retired_native_fields_refuse(key, value):
    raw = document()
    raw[0]["options"][0][key] = value
    with pytest.raises(LevelsError, match="levels_document_invalid"):
        parse_levels(raw)


@pytest.mark.parametrize(
    "model", ["", "*", "grok-4.7-high", "grok-4.7-fast", "claude-opus-5-5[1m]"]
)
def test_rows_require_base_model_ids(model):
    with pytest.raises(LevelsError, match="level_model_invalid"):
        parse_levels(document(model))


@pytest.mark.parametrize("effort", ["", None, "automatic", 3])
def test_unknown_minimum_effort_refuses(effort):
    with pytest.raises(LevelsError, match="level_min_effort_invalid"):
        parse_levels(document(effort=effort))


@pytest.mark.parametrize("name", ["primary", "default", "lowercase", "", "bad-name"])
def test_level_names_follow_existing_contract(name):
    raw = document()
    raw[0]["name"] = name
    with pytest.raises(LevelsError, match="level_name_invalid"):
        parse_levels(raw)


def test_duplicate_model_in_a_level_refuses():
    raw = document()
    raw[0]["options"].append({"model": "gpt-6.1-sol", "min_effort": "high"})
    with pytest.raises(LevelsError, match="level_option_duplicate"):
        parse_levels(raw)


@pytest.mark.parametrize("later", ["low", "medium"])
def test_thresholds_must_strictly_increase_across_levels(later):
    raw = document()
    raw.append(
        {
            "name": "PRINCIPAL",
            "glyph": "🦅",
            "options": [{"model": "gpt-6.1-sol", "min_effort": later}],
        }
    )
    with pytest.raises(LevelsError, match="level_min_effort_order_invalid"):
        parse_levels(raw)


def test_other_models_have_independent_thresholds():
    raw = document("claude-opus-5-5", "max")
    raw.append(
        {
            "name": "PRINCIPAL",
            "glyph": "🦅",
            "options": [{"model": "gpt-6-astra", "min_effort": "low"}],
        }
    )
    assert len(parse_levels(raw)) == 2


def test_project_override_precedes_universe_then_default():
    override = document()
    universe = copy.deepcopy(override)
    universe[0]["name"] = "UNIVERSE"
    assert resolve_effective_levels({"levels": override}, universe)[1] == "project"
    assert resolve_effective_levels({}, universe)[1] == "universe"
    assert resolve_effective_levels(None, None)[1] == "default"


@pytest.mark.parametrize("level", [None, "", "primary"])
def test_unresolved_presentation_never_prints_primary(level):
    assert level_presentation(default_levels(), level) == {
        "label": "no level",
        "glyph": "",
        "reason": "",
    }


@pytest.mark.parametrize(
    "model,effort,reason,label",
    [
        ("no-such-model", "high", "session_model_unknown", "model not in the catalog"),
        (
            "claude-opus-5-5",
            "turbo",
            "session_effort_unpublished",
            "effort not published for its model",
        ),
        ("", "high", "session_model_unreported", "model not reported yet"),
    ],
)
def test_unresolved_presentation_names_its_reason(model, effort, reason, label):
    levels = default_levels()
    found = unresolved_level_reason(
        levels, model=model, effort=effort, records=MODEL_RECORDS
    )
    assert found == reason
    assert level_presentation(levels, "primary", reason=found) == {
        "label": f"no level: {label}",
        "glyph": "",
        "reason": reason,
    }


def _shipped_default_gaps(records):
    conflicts, unverified = published_capability_conflicts(default_levels(), records)
    return conflicts + unverified


def test_every_shipped_default_row_resolves_in_the_shipped_catalog():
    assert _shipped_default_gaps(MODEL_RECORDS) == []
    assert unplaced_models(default_levels(), MODEL_RECORDS) == []


def test_shipped_default_check_catches_a_model_missing_from_the_catalog():
    without = tuple(r for r in MODEL_RECORDS if r.model_id != "claude-opus-5-5")
    gaps = _shipped_default_gaps(without)
    assert {gap["model"] for gap in gaps} == {"claude-opus-5-5"}


def test_unsafe_glyph_refuses():
    raw = document()
    raw[0]["glyph"] = "a"
    with pytest.raises(LevelsError, match="level_glyph_unsafe"):
        parse_levels(raw)
