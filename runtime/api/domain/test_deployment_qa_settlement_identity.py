"""Settlement checks the current execution identity and active stage."""

from unittest import mock

import pytest

from yoke_core.domain.deployment_qa_stage_settlement import settle_execution


def test_settlement_rejects_execution_for_a_different_frozen_target(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement._current_execution",
        lambda conn, execution_id: {
            "id": execution_id,
            "state": "completed",
            "deployment_run_id": "run-frozen",
            "deployment_stage": "visual-qa",
            "execution_target_digest": "old",
        },
    )
    subject = {"stage": {"name": "visual-qa"}}
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_contract.deployment_qa_stage_subject",
        lambda *args, **kwargs: subject,
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_execution_target.deployment_qa_execution_target",
        lambda *args: {"kind": "run_preview", "revision": "new"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_execution_environment_target.target_digest",
        lambda *args: "expected",
    )
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "status": "executing",
        "current_stage": "visual-qa",
    }
    with pytest.raises(ValueError, match="different deployment candidate"):
        settle_execution(
            conn,
            {
                "id": "execution-old",
                "state": "completed",
                "deployment_run_id": "run-frozen",
                "deployment_stage": "visual-qa",
                "execution_target_digest": "old",
            },
        )


def test_replayed_completion_after_stage_advance_does_not_reopen_gate(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement._current_execution",
        lambda conn, execution_id: {
            "id": execution_id,
            "state": "completed",
            "deployment_run_id": "run-frozen",
            "deployment_stage": "visual-qa",
        },
    )
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "status": "executing",
        "current_stage": "complete",
    }
    assert (
        settle_execution(
            conn,
            {
                "id": "completed-qa",
                "state": "completed",
                "deployment_run_id": "run-frozen",
                "deployment_stage": "visual-qa",
            },
        )
        is None
    )
    conn.execute.assert_called_once()
