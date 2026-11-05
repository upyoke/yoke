"""Settlement checks the current execution identity and active stage."""

import subprocess
import sys
from unittest import mock

import pytest

from yoke_core.domain.deployment_qa_stage_settlement import settle_execution


def test_destination_refusal_preserves_digest_after_cold_import():
    # A separate process makes settlement load the refresh module for the first
    # time, independent of which files xdist already ran on this worker.
    probe = """
from pytest import MonkeyPatch
from runtime.api.domain.test_deployment_qa_settlement_identity import (
    test_settlement_rejects_execution_for_a_different_destination,
)
from yoke_core.domain import qa_execution_environment_target as authority

target = {"endpoints": {"app_url": "https://old.example.test"}}
stored_json = authority.canonical_target(target)
stored_digest = authority.target_digest(target)
with MonkeyPatch.context() as patch:
    test_settlement_rejects_execution_for_a_different_destination(patch)
from yoke_core.domain import deployment_qa_requirement_target_refresh as refresh
recomputed = refresh.target_digest(target)
assert recomputed == stored_digest, (
    f"stored_digest={stored_digest!r}; recomputed_digest={recomputed!r}; "
    f"stored_target_json={stored_json!r}"
)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_settlement_rejects_execution_for_a_different_destination(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement._current_execution",
        lambda conn, execution_id: {
            "id": execution_id,
            "state": "completed",
            "deployment_run_id": "run-frozen",
            "deployment_stage": "visual-qa",
            "execution_target_digest": "old",
            "execution_target": {"endpoints": {"app_url": "https://old.example.test"}},
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
        "yoke_core.domain.deployment_qa_target_continuity.settlement_target",
        lambda conn, subject, target: target,
    )
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "status": "executing",
        "current_stage": "visual-qa",
    }
    with pytest.raises(ValueError, match="qa_execution_destination_mismatch"):
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
