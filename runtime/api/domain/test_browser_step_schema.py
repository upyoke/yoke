"""Validation refuses the step shapes execution cannot run."""

from __future__ import annotations

import pytest

from yoke_cli.commands.qa_browser import qa_browser_step
from yoke_contracts.browser_qa_contract import browser_method_contract_violation
from yoke_contracts.browser_step_schema import declared_schema_help


def _violation(steps: list[dict]):
    return browser_method_contract_violation("browser-check", steps)


def test_object_target_names_the_field() -> None:
    found = _violation([{"action": "click", "target": {"css": "#submit"}}])
    assert found is not None
    assert found.code == "step_field_invalid"
    assert "not an object" in found.message
    assert "'target'" in found.message


def test_selector_alias_names_target() -> None:
    found = _violation([{"action": "click", "selector": "#submit"}])
    assert found is not None
    assert found.code == "step_key_unrecognized"
    assert "'selector'" in found.message
    assert "'target'" in found.message


def test_url_alias_names_route() -> None:
    found = _violation([{"action": "navigate", "url": "/login"}])
    assert found is not None
    assert "'url'" in found.message
    assert "'route'" in found.message


def test_assert_value_names_expected() -> None:
    found = _violation(
        [
            {"action": "navigate", "route": "/"},
            {
                "action": "assert",
                "target": "h1",
                "check": "text_equals",
                "value": "Hello",
            },
        ]
    )
    assert found is not None
    assert "'value'" in found.message
    assert "'expected'" in found.message


def test_screenshot_without_capture_is_refused() -> None:
    found = browser_method_contract_violation(
        "browser-inspection",
        [
            {"action": "navigate", "route": "/"},
            {"action": "screenshot"},
        ],
    )
    assert found is not None
    assert found.code == "screenshot_capture_required"
    assert "capture=true" in found.message


def test_screenshot_capture_false_is_refused() -> None:
    found = browser_method_contract_violation(
        "browser-inspection",
        [
            {"action": "navigate", "route": "/"},
            {"action": "screenshot", "capture": False, "target": "#panel"},
        ],
    )
    assert found is not None
    assert "capture=true" in found.message


def test_executable_check_still_passes() -> None:
    found = _violation(
        [
            {"action": "navigate", "route": "/"},
            {"action": "assert", "target": "main", "check": "visible"},
        ]
    )
    assert found is None


def test_step_help_publishes_the_declared_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = declared_schema_help()
    assert "navigate: route" in help_text
    assert "capture=true" in help_text
    assert "selector -> target" in help_text
    with pytest.raises(SystemExit) as raised:
        qa_browser_step(["--help"])
    assert raised.value.code == 0
    printed = capsys.readouterr().out
    assert "Declared browser step schema" in printed
    assert "navigate: route" in printed
