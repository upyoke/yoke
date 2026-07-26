"""Verdict-path parity tests for Browser check and Browser inspection."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import browser_qa


@pytest.mark.parametrize(
    ("method_id", "expected_verdict", "scenario_verdict"),
    [
        ("browser-check", "pass", "pass"),
        ("browser-inspection", "inconclusive", "inconclusive"),
    ],
)
def test_plan_browser_method_selects_its_declared_verdict_path(
    method_id: str,
    expected_verdict: str,
    scenario_verdict: str,
) -> None:
    requirement = {
        "id": 41,
        "qa_kind": "method_case",
        "method_id": method_id,
        "method_config": json.dumps({
            "base_url": "https://preview.example",
            "steps": [{"action": "navigate", "route": "/"}],
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
            return_value={"success": True, "artifacts": []},
        ),
    ):
        result = browser_qa.execute_scenario(
            item_id=9,
            project="yoke",
            base_url="https://preview.example",
        )

    assert result.verdict == scenario_verdict
    assert result.runs[0].verdict == expected_verdict
    assert completed[0][1]["verdict"] == expected_verdict
    assert completed[0][1]["execution_status"] == "captured"
