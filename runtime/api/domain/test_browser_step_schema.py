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


def test_ready_naming_no_indicator_teaches_what_it_needs() -> None:
    found = _violation(
        [
            {"action": "navigate", "route": "/"},
            {"action": "ready", "timeout_ms": 500},
        ]
    )
    assert found is not None
    assert found.code == "step_require_any"
    assert "requires target, text, or both" in found.message
    assert "prove nothing" in found.message


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
    assert "grant_clipboard" in help_text
    assert "clipboard_permission_origin_required" in help_text
    assert "selector -> target" in help_text
    with pytest.raises(SystemExit) as raised:
        qa_browser_step(["--help"])
    assert raised.value.code == 0
    printed = capsys.readouterr().out
    assert "navigate: route" in printed
    assert "grant_clipboard" in printed


@pytest.mark.parametrize("dialog", ["accept", "dismiss"])
def test_click_accepts_a_declared_dialog(dialog: str) -> None:
    from yoke_contracts.browser_step_schema import step_schema_violation

    assert (
        step_schema_violation(
            0,
            {
                "action": "click",
                "target": "#remove",
                "dialog": dialog,
            },
        )
        is None
    )


@pytest.mark.parametrize(
    "dialog",
    [
        None,
        [],
        {},
        True,
        1,
        "yes",
        {"accept": True},
    ],
)
def test_invalid_dialog_is_refused_before_execution(dialog) -> None:
    from yoke_contracts.browser_step_schema import step_schema_violation

    assert (
        step_schema_violation(
            0,
            {
                "action": "click",
                "target": "#remove",
                "dialog": dialog,
            },
        )
        is not None
    )


def test_dialog_is_only_defined_on_click() -> None:
    from yoke_contracts.browser_step_schema import step_schema_violation

    found = step_schema_violation(
        0,
        {
            "action": "navigate",
            "route": "/",
            "dialog": "accept",
        },
    )
    assert found is not None
    assert found.code == "step_key_unrecognized"
    assert "dialog" in found.message


def test_dialog_help_teaches_the_answer_and_failure() -> None:
    text = declared_schema_help()
    assert "dialog=" in text
    assert "browser_dialog_unanswered" in text
    assert 'dialog="dismiss"' in text


@pytest.mark.parametrize("missing", [None, "target", "path"])
def test_download_requires_target_and_destination(missing):
    from yoke_contracts.browser_step_schema import step_schema_violation

    step = {"action": "download", "target": "#export", "path": "archive.zip"}
    if missing:
        del step[missing]
    found = step_schema_violation(0, step)
    if missing:
        assert found is not None
        assert missing in found.message
    else:
        assert found is None
