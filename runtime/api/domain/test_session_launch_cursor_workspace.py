"""A launched native binds by the workspace its opening hook registered.

Cursor's sessionStart names its workspace in ``workspace_roots`` and carries
no ``cwd``; Claude and Codex carry ``cwd``. Registration must store the same
workspace the relay recorded for the launch on every surface, or the launch's
registration candidate never matches and the native is left unbound.
"""

from __future__ import annotations

import json

from yoke_core.domain.session_launch_binding_evidence import (
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


def test_session_end_names_the_launch_it_never_bound() -> None:
    conn = _connection()
    launch, _claim = _claimed_launch(conn, "ended-unbound")
    state_before = get_launch(conn, launch.launch_id).state

    assert record_session_ended_unbound(
        conn, launch_id=launch.launch_id, session_id=SESSION_ID
    )
    ended = get_launch(conn, launch.launch_id)
    evidence = ended.result_evidence
    evidence = json.loads(evidence) if isinstance(evidence, str) else evidence
    assert evidence["registration_refusal_code"] == "session_ended_unbound"
    assert evidence["registration_session_id"] == SESSION_ID
    assert ended.state == state_before, "a refusal is evidence, not a transition"


def test_session_end_leaves_a_bound_launch_untouched() -> None:
    conn = _connection()
    launch, _claim = _claimed_launch(conn, "ended-bound")
    _register_candidate(conn)
    conn.execute(
        "UPDATE session_launches SET registered_session_id=? WHERE launch_id=?",
        (SESSION_ID, launch.launch_id),
    )
    conn.commit()

    assert not record_session_ended_unbound(
        conn, launch_id=launch.launch_id, session_id="another-session"
    )
    evidence = get_launch(conn, launch.launch_id).result_evidence
    assert "session_ended_unbound" not in str(evidence or "")
