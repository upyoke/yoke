"""Every preparation ends in exactly one envelope, success or refusal.

Regression: a failure inside preparation printed a traceback and no
receipt, so the caller could not tell a crash from a preparation that
never started — and could not tell whether a lane had been left behind.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import direct_workflow_worktree_preflight as preflight
from yoke_core.domain.worktree_preflight_outcome import BLOCK_PREPARE_FAILED


def _raising_dispatcher(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _dispatch(**_kwargs):
        raise exc

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatch,
    )


def test_an_unexpected_failure_still_prints_a_refusal_receipt(
    monkeypatch, capsys
) -> None:
    _raising_dispatcher(monkeypatch, RuntimeError("relay socket closed"))

    assert preflight.run(["YOK-7", "--workflow", "dash"]) == 1

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is False
    assert receipt["block_kind"] == BLOCK_PREPARE_FAILED
    assert receipt["item"] == "YOK-7"
    assert "RuntimeError: relay socket closed" in receipt["narrative"]


def test_the_refusal_names_the_lane_read_and_the_retry(monkeypatch, capsys) -> None:
    _raising_dispatcher(monkeypatch, ValueError("no"))

    preflight.run(["YOK-7", "--workflow", "dash"])

    narrative = json.loads(capsys.readouterr().out)["narrative"]
    assert "yoke item-worktrees list YOK-7" in narrative
    assert "reuses a recorded lane" in narrative


def test_a_usage_error_is_not_dressed_up_as_a_prepared_lane(monkeypatch) -> None:
    _raising_dispatcher(monkeypatch, RuntimeError("never reached"))

    with pytest.raises(SystemExit) as exit_info:
        preflight.run(["YOK-7", "--workflow", "nonsense"])

    assert exit_info.value.code == 2
