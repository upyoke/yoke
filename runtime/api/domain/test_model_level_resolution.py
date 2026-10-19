"""Model identity, published effort and one-class demotion determine levels."""

from dataclasses import replace
import pytest
from yoke_contracts.levels import (
    default_levels,
    level_for_session,
    parse_levels,
    LevelsError,
)
from yoke_contracts.model_level_resolution import resolve_model_level
from yoke_contracts.model_reference_records import ModelRecord
from runtime.api.fixtures.model_catalog import RECORDS


@pytest.mark.parametrize(
    "model,effort,expected",
    [
        ("grok-4.7-high-fast", None, "JUNIOR"),
        ("grok-4.7-high", None, "JUNIOR"),
        ("grok-4.7-low", None, "INTERN"),
        ("claude-opus-5-5-medium", None, "SENIOR"),
        ("claude-opus-5-5", "low", "JUNIOR"),
        ("claude-fable-5-1", "xhigh", "PRINCIPAL"),
        ("claude-fable-5-1", "medium", "SENIOR"),
        ("gpt-6.1-sol", "medium", "SENIOR"),
        ("gpt-6-luna", "max", "INTERN"),
        ("claude-opus-4-8", "medium", "INTERN"),
        ("claude-opus-5", "medium", "INTERN"),
        ("gpt-6-sol", "high", "JUNIOR"),
        ("gpt-5.6-sol", "high", "JUNIOR"),
        ("gpt-5.6-luna", "max", None),
        ("cursor-grok-4.6-high", None, None),
        ("composer-2.5", "high", None),
        ("unknown", "high", None),
        ("grok-4.7", None, None),
        ("grok-4.7", "ultra", None),
    ],
)
def test_resolution_is_independent_of_harness(model, effort, expected):
    for executor in (
        "claude-code",
        "codex",
        "cursor",
        "cursor-desktop",
        "another-harness",
        "",
    ):
        assert (
            level_for_session(
                default_levels(),
                executor=executor,
                model=model,
                reasoning_effort=effort,
                records=RECORDS,
            )
            == expected
        )


def test_observed_effort_overrides_embedded_requested_effort():
    assert (
        level_for_session(
            default_levels(),
            executor="cursor",
            model="grok-4.7-high-fast",
            reasoning_effort="low",
            records=RECORDS,
        )
        == "INTERN"
    )


def test_old_bottom_class_refuses():
    old = ModelRecord(
        model_id="claude-haiku-4-5",
        provider="anthropic",
        display_name="Old Haiku",
        replacement_model_id="claude-haiku-5-5",
        reasoning_efforts=("low", "medium", "high"),
    )
    result = resolve_model_level(
        default_levels(), model=old.model_id, effort="medium", records=(*RECORDS, old)
    )
    assert result.level is None
    assert result.reason == "session_older_model_bottom_class"


def test_version_age_never_drops_more_than_one_class():
    old = replace(
        next(record for record in RECORDS if record.model_id == "claude-opus-4-8"),
        model_id="claude-opus-1",
        replacement_model_id="claude-opus-4-8",
    )
    result = resolve_model_level(
        default_levels(), model=old.model_id, effort="medium", records=(*RECORDS, old)
    )
    assert result.model == "claude-sonnet-5-5"
    assert result.level == "INTERN"


@pytest.mark.parametrize("minimum", ["low", "none"])
def test_minimum_effort_must_increase_with_level(minimum):
    document = [level.payload() for level in default_levels()]
    document[1]["options"][0]["min_effort"] = minimum
    with pytest.raises(LevelsError, match="level_min_effort_order_invalid"):
        parse_levels(document)


def test_no_catalog_is_no_level():
    assert (
        level_for_session(
            default_levels(),
            executor="codex",
            model="gpt-6.1-sol",
            reasoning_effort="medium",
            records=(),
        )
        is None
    )


@pytest.mark.parametrize(
    "effort,reason",
    [(None, "session_effort_unreported"), ("ultra", "session_effort_unpublished")],
)
def test_missing_effort_is_distinct_from_unpublished_effort(effort, reason):
    result = resolve_model_level(
        default_levels(), model="claude-opus-5-5", effort=effort, records=RECORDS
    )
    assert (result.level, result.reason) == (None, reason)


@pytest.mark.parametrize("model", ["gpt-6-astra", "claude-opus-5-5", "gpt-6-luna"])
def test_a_not_reported_effort_takes_the_lowest_level_and_names_why(model):
    levels = default_levels()

    result = resolve_model_level(
        levels, model=model, effort="not_reported", records=RECORDS
    )

    assert result.level == levels[0].name
    assert result.reason == "session_effort_not_reported"


def test_a_not_reported_effort_on_an_unknown_model_still_resolves_no_level():
    result = resolve_model_level(
        default_levels(), model="unknown", effort="not_reported", records=RECORDS
    )

    assert (result.level, result.reason) == (None, "session_model_unknown")
