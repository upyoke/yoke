"""Verdict-path parity tests for Browser check and Browser inspection."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)


def _steps_for_method(method_id: str) -> list[dict]:
    steps = [{"action": "navigate", "route": "/"}]
    if method_id == "browser-check":
        steps.append({
            "action": "assert",
            "target": "main",
            "check": "visible",
        })
    else:
        steps.append({"action": "screenshot", "capture": True})
    return steps


@pytest.mark.parametrize(
    ("method_id", "expected_verdict", "scenario_verdict"),
    [
        ("browser-check", "pass", "pass"),
        ("browser-inspection", "inconclusive", "inconclusive"),
    ],
)
def test_plan_browser_method_selects_its_declared_verdict_path(
    tmp_path,
    method_id: str,
    expected_verdict: str,
    scenario_verdict: str,
) -> None:
    screenshot = tmp_path / "inspection.png"
    screenshot.write_bytes(b"PNG")
    responses = [{"success": True, "artifacts": []}]
    responses.append(
        {"success": True, "artifacts": [str(screenshot)]}
        if method_id == "browser-inspection"
        else {"success": True, "artifacts": []}
    )
    requirement = {
        "id": 41,
        "qa_kind": "method_case",
        "method_id": method_id,
        "method_config": json.dumps({
            "base_url": "https://preview.example",
            "steps": _steps_for_method(method_id),
        }),
        "expected_outcome": "The page is ready.",
    }
    completed = []
    with (
        mock.patch.object(
            browser_qa,
            "_fetch_browser_context",
            return_value={"item_id": 9, "requirements": [requirement]},
        ),
        mock.patch.object(
            browser_qa, "_validate_reachability", return_value=None,
        ),
        mock.patch.object(
            browser_qa, "_ensure_daemon_running", return_value=None,
        ),
        mock.patch.object(browser_qa, "_record_run", return_value=7),
        mock.patch.object(
            browser_qa,
            "_complete_run",
            side_effect=lambda *args, **kwargs: completed.append(
                (args, kwargs)
            ),
        ),
        mock.patch.object(
            browser_qa,
            "_execute_step",
            side_effect=responses,
        ),
        mock.patch.object(browser_qa, "_record_artifact", return_value=8),
        mock.patch.object(
            browser_qa,
            "_durable_artifact_handle",
            return_value={"backend": "local", "path": str(screenshot)},
        ),
    ):
        result = browser_qa.execute_scenario(
            item_id=9,
            project="yoke",
            requirement_id=41,
            base_url="https://preview.example",
        )

    assert result.verdict == scenario_verdict
    assert result.runs[0].verdict == expected_verdict
    assert completed[0][1]["verdict"] == expected_verdict
    assert completed[0][1]["execution_status"] == "captured"


def test_browser_check_records_failed_assertion_on_canonical_runner() -> None:
    requirement = {
        "id": 41,
        "qa_kind": "plan_case",
        "method_id": "browser-check",
        "method_config": json.dumps({
            "steps": _steps_for_method("browser-check"),
        }),
        "expected_outcome": "The page is ready.",
    }
    completed = []
    with (
        mock.patch.object(
            browser_qa,
            "_fetch_browser_context",
            return_value={"item_id": 9, "requirements": [requirement]},
        ),
        mock.patch.object(
            browser_qa, "_validate_reachability", return_value=None,
        ),
        mock.patch.object(
            browser_qa, "_ensure_daemon_running", return_value=None,
        ),
        mock.patch.object(browser_qa, "_record_run", return_value=7),
        mock.patch.object(
            browser_qa,
            "_complete_run",
            side_effect=lambda *args, **kwargs: completed.append(
                (args, kwargs)
            ),
        ),
        mock.patch.object(
            browser_qa,
            "_execute_step",
            side_effect=[
                {"success": True, "artifacts": []},
                {"success": False, "error": "assertion failed"},
            ],
        ),
    ):
        result = browser_qa.execute_scenario(
            item_id=9,
            project="yoke",
            requirement_id=41,
            base_url="https://preview.example",
        )

    assert result.verdict == "fail"
    assert result.runs[0].verdict == "fail"
    assert "assertion failed" in result.runs[0].errors
    assert completed[0][1]["verdict"] == "fail"


@pytest.mark.parametrize(
    ("method_id", "steps", "message"),
    [
        (
            "browser-check",
            [{"action": "navigate", "route": "/"}],
            "verdict-bearing assert",
        ),
        (
            "browser-check",
            [{
                "action": "assert",
                "target": "main",
                "check": "visible",
            }],
            "preceding navigate",
        ),
        (
            "browser-inspection",
            [{"action": "navigate", "route": "/"}],
            "screenshot",
        ),
        (
            "browser-check",
            [
                {"action": "navigate", "route": "/"},
                {"action": "assert", "target": "main"},
            ],
            "requires one of",
        ),
        (
            "browser-inspection",
            [
                {"action": "navigate", "route": "/"},
                {"action": "screenshot", "capture": False},
            ],
            "capture=true",
        ),
    ],
)
def test_browser_method_validation_rejects_vacuous_contracts(
    method_id: str,
    steps: list[dict],
    message: str,
) -> None:
    with pytest.raises(QaMethodConfigError, match=message):
        validate_method_config(method_id, {"steps": steps})
