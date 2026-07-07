"""Handler coverage for conduct-owned epic pipeline wrappers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from yoke_core.domain.handlers import conduct_epic_pipeline as handlers
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import (
    list_entries,
    reset_registry_for_tests,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


@contextmanager
def _fake_conn():
    yield object()


def _request(
    function: str,
    *,
    task_num: int | None = 1,
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="session-1"),
        target=TargetRef(kind="epic_task", epic_id=42, task_num=task_num),
        payload=payload or {},
    )


def test_update_status_uses_pipeline_env_and_flags() -> None:
    def fake_update(
        conn, epic_id, task_num, status, note, *,
        no_rebuild, no_github, no_derive, stdout, stderr,
    ) -> int:
        assert epic_id == "42"
        assert task_num == "7"
        assert status == "implementing"
        assert note == "retry"
        assert no_rebuild is True
        assert no_github is False
        assert no_derive is True
        assert os.environ["YOKE_STATUS_SOURCE"] == "conduct"
        assert os.environ["YOKE_CLAIM_BYPASS"] == "simulation-autofix:epic-42"
        stdout.write("ok\n")
        return 0

    with patch.object(handlers, "_open_connection", _fake_conn):
        with patch.object(
            handlers.update_status, "update_task_status",
            side_effect=fake_update,
        ):
            outcome = handlers.handle_update_status(
                _request(
                    "conduct.epic_task.update_status",
                    task_num=7,
                    payload={
                        "status": "implementing",
                        "note": "retry",
                        "no_rebuild": True,
                        "no_derive": True,
                        "claim_bypass": "simulation-autofix:epic-42",
                    },
                ),
            )

    assert outcome.primary_success
    assert outcome.result_payload["stdout"] == "ok\n"
    assert "YOKE_CLAIM_BYPASS" not in os.environ


def test_update_status_nonzero_maps_failure() -> None:
    def fake_update(*_args, stderr, **_kwargs) -> int:
        stderr.write("not allowed\n")
        return 3

    with patch.object(handlers, "_open_connection", _fake_conn):
        with patch.object(
            handlers.update_status, "update_task_status",
            side_effect=fake_update,
        ):
            outcome = handlers.handle_update_status(
                _request(
                    "conduct.epic_task.update_status",
                    payload={"status": "failed"},
                ),
            )

    assert not outcome.primary_success
    assert outcome.error.code == "status_pipeline_failed"
    assert "not allowed" in outcome.error.message


def test_proceed_handoff_uses_actor_session_when_payload_omits_it() -> None:
    with patch.object(
        handlers.epic, "proceed_triage_and_handoff", return_value=0,
    ) as handoff:
        outcome = handlers.handle_proceed_triage_handoff(
            _request(
                "conduct.epic.proceed_triage_handoff",
                task_num=None,
                payload={
                    "recommendation": "PROCEED",
                    "gap_summary": "minor",
                    "filed_ticket_ids": ["YOK-1"],
                },
            ),
        )

    assert outcome.primary_success
    handoff.assert_called_once_with(
        42,
        recommendation="PROCEED",
        gap_summary="minor",
        filed_ticket_ids=["YOK-1"],
        session_id="session-1",
    )


def test_conduct_registration_models_claims_and_side_effects() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        entries = {entry.function_id: entry for entry in list_entries()}
        status = entries["conduct.epic_task.update_status"]
        proceed = entries["conduct.epic.proceed_triage_handoff"]
        assert status.claim_required_kind is None
        assert "epic_task_status_pipeline" in status.side_effects
        assert proceed.claim_required_kind == "epic"
        assert "epic_status_handoff" in proceed.side_effects
    finally:
        reset_registry_for_tests()
