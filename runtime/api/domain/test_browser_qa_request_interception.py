"""Request interception is declared identically for authoring and execution."""

import pytest

from yoke_contracts.browser_step_schema import (
    declared_schema_help,
    step_schema_violation,
)


@pytest.mark.parametrize("mode", ["hold", "reject", "release", "status"])
def test_interception_declares_function_and_mode(mode):
    assert (
        step_schema_violation(
            0,
            {
                "action": "request_interception",
                "function_id": "qa.activity.read",
                "mode": mode,
            },
        )
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "abort"},
        {"mode": None},
        {"mode": {}},
        {"function_id": ""},
        {"function_id": {}},
        {"url_pattern": "*"},
    ],
)
def test_interception_refuses_unsupported_or_incomplete_steps(change):
    step = {
        "action": "request_interception",
        "function_id": "qa.activity.read",
        "mode": "hold",
    }
    step.update(change)
    assert step_schema_violation(0, step) is not None


def test_help_teaches_scope_lifecycle_and_observation_counts():
    help_text = declared_schema_help()
    for text in (
        "function_id",
        "hold",
        "reject",
        "release",
        "status",
        "same-origin",
        "matched/pending/",
    ):
        assert text in help_text
