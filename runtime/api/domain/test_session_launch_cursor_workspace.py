"""A launched native binds by the workspace its opening hook registered.

Cursor's sessionStart names its workspace in ``workspace_roots`` and carries
no ``cwd``; Claude and Codex carry ``cwd``. Registration must store the same
workspace the relay recorded for the launch on every surface, or the launch's
registration candidate never matches and the native is left unbound.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session_launch_binding_evidence import (
    SESSION_END_RECORDED,
    SESSION_END_SKIP_ATTESTATION_INVALID,
    SESSION_END_SKIP_EARLIER_REFUSAL,
    SESSION_END_SKIP_LAUNCH_BOUND,
    SESSION_END_SKIP_LAUNCH_CLOSED,
    SESSION_END_SKIP_NATIVE_SESSION_MISMATCH,
    record_registration_refusal,
    record_session_ended_unbound,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_relay import report_relay_job
from yoke_core.hooks.registration_observed import parse_hook_registration_facts
from runtime.api.domain.test_session_launch_registration_candidate import (
    SESSION_ID,
    WORKSPACE,
    _claimed_launch,
    _connection,
    _register_candidate,
)


def _workspace(payload: dict) -> str:
    return parse_hook_registration_facts(
        json.dumps(payload), project_id=1, transcript_path=""
    ).workspace


def test_cursor_session_start_without_cwd_registers_its_workspace_root() -> None:
    assert (
        _workspace(
            {
                "hook_event_name": "sessionStart",
                "session_id": SESSION_ID,
                "workspace_roots": [WORKSPACE, "/second-root"],
            }
        )
        == WORKSPACE
    )


def test_workspace_root_leads_a_cursor_tool_event_cwd() -> None:
    assert (
        _workspace({"workspace_roots": [WORKSPACE], "cwd": f"{WORKSPACE}/sub"})
        == WORKSPACE
    )


def test_claude_and_codex_cwd_registration_is_unchanged() -> None:
    assert _workspace({"cwd": WORKSPACE}) == WORKSPACE
    assert _workspace({}) == ""


def test_cursor_registered_workspace_binds_the_launch_candidate() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "cursor-workspace")
    _register_candidate(
        conn,
        workspace=_workspace({"workspace_roots": [WORKSPACE]}),
    )

    progress = report_relay_job(
        conn,
        actor_id=1,
        relay_id="relay-1",
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="progress",
        adapter_revision="claude-native-v7",
        evidence={
            "result_code": "identity_registration_wait",
            "native_launch_workspace": WORKSPACE,
        },
        now="2026-08-22T12:00:03Z",
    )

    assert progress["registration"]["session_id"] == SESSION_ID
    assert get_launch(conn, launch.launch_id).native_session_id == SESSION_ID


def _evidence(conn, launch_id: str) -> dict:
    raw = get_launch(conn, launch_id).result_evidence
    if isinstance(raw, str):
        return json.loads(raw) if raw else {}
    return dict(raw or {})


def _end(conn, launch_id: str, attestation: str, session_id: str = SESSION_ID):
    return record_session_ended_unbound(
        conn, launch_id=launch_id, attestation=attestation, session_id=session_id
    )


def _set(conn, launch_id: str, assignments: str, *values) -> None:
    conn.execute(
        f"UPDATE session_launches SET {assignments} WHERE launch_id=?",
        (*values, launch_id),
    )
    conn.commit()


def _awaiting_launch(conn, key: str):
    launch, claim = _claimed_launch(conn, key)
    _set(conn, launch.launch_id, "state='awaiting_registration'")
    return launch, claim


def test_session_end_names_the_launch_it_never_bound() -> None:
    conn = _connection()
    launch, claim = _awaiting_launch(conn, "ended-unbound")

    assert _end(conn, launch.launch_id, claim.attestation) == SESSION_END_RECORDED
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["registration_refusal_code"] == "session_ended_unbound"
    assert evidence["registration_session_id"] == SESSION_ID
    assert get_launch(conn, launch.launch_id).state == "awaiting_registration", (
        "a refusal is evidence, not a transition"
    )


def test_session_end_of_the_named_native_is_recorded() -> None:
    conn = _connection()
    launch, claim = _awaiting_launch(conn, "ended-own-native")
    _register_candidate(conn)
    _set(conn, launch.launch_id, "native_session_id=?", SESSION_ID)

    assert _end(conn, launch.launch_id, claim.attestation) == SESSION_END_RECORDED


def test_session_end_of_another_session_skips_a_launch_naming_its_native() -> None:
    conn = _connection()
    launch, claim = _awaiting_launch(conn, "ended-other-native")
    _register_candidate(conn)
    _set(conn, launch.launch_id, "native_session_id=?", SESSION_ID)

    assert (
        _end(conn, launch.launch_id, claim.attestation, "inherited-attestation")
        == SESSION_END_SKIP_NATIVE_SESSION_MISMATCH
    )
    assert "registration_refusal_code" not in _evidence(conn, launch.launch_id)


def test_session_end_with_a_wrong_attestation_records_nothing() -> None:
    conn = _connection()
    launch, _claim = _awaiting_launch(conn, "ended-forged")

    assert (
        _end(conn, launch.launch_id, "not-the-attestation")
        == SESSION_END_SKIP_ATTESTATION_INVALID
    )
    assert "registration_refusal_code" not in _evidence(conn, launch.launch_id)


def test_session_end_leaves_a_bound_launch_untouched() -> None:
    conn = _connection()
    launch, claim = _awaiting_launch(conn, "ended-bound")
    _register_candidate(conn)
    _set(conn, launch.launch_id, "registered_session_id=?", SESSION_ID)

    assert (
        _end(conn, launch.launch_id, claim.attestation, "another")
        == SESSION_END_SKIP_LAUNCH_BOUND
    )
    assert "registration_refusal_code" not in _evidence(conn, launch.launch_id)


@pytest.mark.parametrize("state", ["launching", "cancelled", "failed"])
def test_session_end_leaves_a_launch_binding_cannot_reach_untouched(state) -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, f"ended-{state}")
    _set(conn, launch.launch_id, "state=?", state)

    assert _end(conn, launch.launch_id, claim.attestation) == (
        SESSION_END_SKIP_LAUNCH_CLOSED
    )
    assert "registration_refusal_code" not in _evidence(conn, launch.launch_id)


def test_session_end_still_names_an_outcome_unknown_launch_recovery_could_bind():
    conn = _connection()
    launch, claim = _claimed_launch(conn, "ended-outcome-unknown")
    _set(conn, launch.launch_id, "state='outcome_unknown', native_session_id=NULL")

    assert _end(conn, launch.launch_id, claim.attestation) == SESSION_END_RECORDED


def test_session_end_keeps_an_earlier_more_specific_refusal() -> None:
    conn = _connection()
    launch, claim = _awaiting_launch(conn, "ended-earlier-refusal")
    record_registration_refusal(
        conn,
        launch_id=launch.launch_id,
        code="attestation_invalid",
        session_id=SESSION_ID,
    )

    assert (
        _end(conn, launch.launch_id, claim.attestation)
        == SESSION_END_SKIP_EARLIER_REFUSAL
    )
    assert (
        _evidence(conn, launch.launch_id)["registration_refusal_code"]
        == "attestation_invalid"
    )
