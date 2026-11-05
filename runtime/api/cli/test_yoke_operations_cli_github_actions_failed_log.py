"""CLI coverage for ``yoke github-actions failed-log``."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_github_actions_failed_log_test_support import (
    _CAPTURED_REQUESTS as _CAPTURED_REQUESTS,
    _CONNECTION as _CONNECTION,
    _run as _run,
)


import json

import pytest

import yoke_cli.commands.adapters.github_actions_failed_log as failed_log_mod


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_failed_log_relays_run_id_and_prints_output() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "9182736",
        "--project",
        "platform",
        "--lines",
        "25",
        result={
            "run_id": "9182736",
            "output": "failed step output",
            "truncated": False,
        },
    )

    assert rc == 0
    assert out == "failed step output\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.failed_log"
    assert request.payload == {
        "repo": "upyoke/platform",
        "project": "platform",
        "max_lines": 25,
        "run_id": "9182736",
    }


def test_failed_log_resolves_workflow_selector_from_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        failed_log_mod,
        "_resolve_head_sha",
        lambda head_ref: (0, "deadbeef" * 5),
    )
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "--workflow",
        "ci.yml",
        "--branch",
        "main",
        "--project",
        "platform",
        result={"run_id": "77", "output": "boom", "truncated": False},
    )

    assert rc == 0
    assert out == "boom\n"
    request = _CAPTURED_REQUESTS[-1]
    assert request.payload == {
        "repo": "upyoke/platform",
        "project": "platform",
        "workflow": "ci.yml",
        "branch": "main",
        "head_sha": "deadbeef" * 5,
    }


def test_failed_log_json_preserves_envelope() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "1",
        "--project",
        "platform",
        "--json",
        result={"run_id": "1", "output": "x", "truncated": False},
    )

    assert rc == 0
    assert err == ""
    envelope = json.loads(out)
    assert envelope["function"] == "github_actions.failed_log"
    assert envelope["result"]["output"] == "x"


def test_failed_log_requires_run_id_or_workflow() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "--project",
        "platform",
    )

    assert rc == 2
    assert "run id or --workflow is required" in err


def test_failed_log_refuses_a_line_bound_below_one() -> None:
    rc, _out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "1",
        "--project",
        "platform",
        "--lines",
        "0",
    )

    assert rc == 2
    assert "--lines must be at least 1" in err
    assert _CAPTURED_REQUESTS == []
