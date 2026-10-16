"""An evidence-read job success is not a session-liveness verdict."""

import io
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters.session_control_evidence import _write_evidence
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_control.evidence_fetch import evidence_pull_command
from yoke_contracts.session_control.function_ids import EVIDENCE_GET_FUNCTION_ID
from yoke_core.domain.handlers import session_evidence as handler
from yoke_core.domain import session_evidence_fetch as evidence


def test_evidence_success_is_labelled_as_fetch_job_state():
    out = io.StringIO()
    _write_evidence(
        SimpleNamespace(
            result={"session_id": "worker", "state": "succeeded", "result_code": "read"}
        ),
        out,
        io.StringIO(),
    )
    assert "FETCH JOB STATE" in out.getvalue()
    assert "succeeded" in out.getvalue()


_WORKSPACE_RECOVERY = (
    "org-scoped session has no recorded workspace on this machine — terminate it deliberately "
    "(confirm the command with `yoke sessions --help`) or start a new session; project registration does not apply"
)


@pytest.mark.parametrize("wait_seconds", [0, 1])
@pytest.mark.parametrize(
    "state,code,org_id,recovery",
    [
        ("failed", "session_workspace_unrecorded", 7, _WORKSPACE_RECOVERY),
        ("failed", "session_workspace_unrecorded", None, None),
        ("failed", "unreadable", 7, None),
        ("succeeded", "read", 7, None),
        ("succeeded", "session_workspace_unrecorded", 7, None),
        ("expired", "expired", 7, None),
        ("pending", None, 7, evidence_pull_command("target")),
    ],
)
def test_public_evidence_handler_and_renderer_preserve_recovery(
    monkeypatch, wait_seconds, state, code, org_id, recovery
):
    record = {
        "fetch_id": "fetch",
        "target_session_id": "target",
        "project_id": None if org_id is not None else 1,
        "org_id": org_id,
        "state": state,
        "result_code": code,
    }
    closed = []
    conn = SimpleNamespace(
        close=lambda: closed.append(True), rollback=lambda: None, commit=lambda: None
    )
    monkeypatch.setattr(handler, "open_connection", lambda: conn)
    monkeypatch.setattr(evidence, "request_evidence_fetch", lambda *a, **kw: record)
    monkeypatch.setattr(evidence, "read_evidence_fetch", lambda *a: record)
    outcome = handler.handle_evidence_get(
        FunctionCallRequest(
            function=EVIDENCE_GET_FUNCTION_ID,
            actor=ActorContext(actor_id="1", session_id="caller"),
            target=TargetRef(kind="global"),
            payload={"session_id": "target", "wait_seconds": wait_seconds},
        )
    )
    result = outcome.result_payload
    assert result["state"] == state and result["result_code"] == code
    assert result["recovery"] == recovery
    assert closed == [True]
    out = io.StringIO()
    _write_evidence(SimpleNamespace(result=result), out, io.StringIO())
    assert state in out.getvalue()
    if recovery:
        assert "READ IT BACK" in out.getvalue()
        assert recovery in out.getvalue()
