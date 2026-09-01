"""A launch's model ask reaches the session row it binds, on every harness.

The child process is not a reliable channel for its own ask: Claude serves
a launch from a pre-warmed process pool whose environment predates the
launch, so the registration envelope arrives with every requested column
null while the launch row beside it holds the exact string the operator
asked for. These tests hold the control plane to filling that gap.
"""

from __future__ import annotations

from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_TOKENS

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


NATIVE_SESSION_ID = "native-session"
LATER = "2026-08-22T12:00:31Z"


def _registered_launch(conn, *, surface: str, version: str, model: str | None):
    """Run one launch up to the moment its native session registers."""
    add_relay(conn, surface=surface, version=version)
    launch = assigned_launch(conn, surface=surface, model=model)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=NATIVE_SESSION_ID,
        adapter_revision=f"{surface}-v1",
        evidence={"duration_ms": 40, "exit_code": 0},
        now="2026-08-22T12:00:30Z",
    )
    return launch, claim


def _register_session(conn, *, surface: str, version: str, **stated) -> None:
    """Insert the session row a native writes when its first hook fires."""
    columns = ", ".join(stated)
    markers = ", ".join("?" for _ in stated)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        f"machine_id{', ' + columns if stated else ''}) "
        f"VALUES (?, 10, ?, ?, 'machine-1'{', ' + markers if stated else ''})",
        (NATIVE_SESSION_ID, surface, version, *stated.values()),
    )
    conn.commit()


def _stamped_facts(conn) -> dict:
    row = conn.execute(
        "SELECT requested_model, requested_reasoning_effort, "
        "requested_context_window_tokens, model FROM harness_sessions "
        "WHERE session_id = ?",
        (NATIVE_SESSION_ID,),
    ).fetchone()
    return dict(row)


def _bind(conn, *, surface: str, version: str, model: str | None, **stated) -> dict:
    launch, claim = _registered_launch(
        conn, surface=surface, version=version, model=model
    )
    _register_session(conn, surface=surface, version=version, **stated)
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=NATIVE_SESSION_ID,
        now=LATER,
    )
    return _stamped_facts(conn)


def test_a_claude_launch_stores_the_ask_its_pooled_process_could_not_read() -> None:
    conn = launch_connection()

    facts = _bind(
        conn,
        surface="claude-cli",
        version="2.1.252",
        model="claude-opus-5[1m]",
    )

    assert facts["requested_model"] == "claude-opus-5[1m]"
    assert facts["requested_context_window_tokens"] == CLAUDE_CONTEXT_TIER_TOKENS


def test_a_codex_launch_stores_the_model_it_asked_for() -> None:
    conn = launch_connection()

    facts = _bind(conn, surface="codex-cli", version="0.148.0a15", model="gpt-5.6-sol")

    assert facts["requested_model"] == "gpt-5.6-sol"
    assert facts["requested_reasoning_effort"] is None


def test_a_cursor_launch_stores_the_effort_its_variant_name_spells() -> None:
    conn = launch_connection()

    facts = _bind(
        conn,
        surface="cursor-cli",
        version="2026.08.25",
        model="cursor-grok-4.6-xhigh",
    )

    assert facts["requested_model"] == "cursor-grok-4.6-xhigh"
    assert facts["requested_reasoning_effort"] == "xhigh"


def test_binding_never_rewrites_an_ask_the_session_stated_itself() -> None:
    conn = launch_connection()

    facts = _bind(
        conn,
        surface="cursor-cli",
        version="2026.08.25",
        model="cursor-grok-4.6-xhigh",
        requested_model="cursor-grok-4.6-low",
        requested_reasoning_effort="low",
    )

    assert facts["requested_model"] == "cursor-grok-4.6-low"
    assert facts["requested_reasoning_effort"] == "low"


def test_binding_leaves_the_served_column_to_its_own_attestation_reader() -> None:
    """A launch's model is a request, so it never lands in ``model``."""
    conn = launch_connection()

    facts = _bind(
        conn,
        surface="cursor-cli",
        version="2026.08.25",
        model="cursor-grok-4.6-xhigh",
    )

    assert facts["model"] is None


def test_a_launch_asking_for_no_model_stamps_nothing() -> None:
    conn = launch_connection()

    facts = _bind(conn, surface="codex-cli", version="0.148.0a15", model=None)

    assert facts["requested_model"] is None


def test_the_binding_records_which_requested_columns_it_supplied() -> None:
    conn = launch_connection()
    launch, claim = _registered_launch(
        conn, surface="cursor-cli", version="2026.08.25", model="cursor-grok-4.6-xhigh"
    )
    _register_session(conn, surface="cursor-cli", version="2026.08.25")

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=NATIVE_SESSION_ID,
        now=LATER,
    )

    evidence = get_launch(conn, launch.launch_id).result_evidence or ""
    assert "requested_model" in evidence
    assert "requested_reasoning_effort" in evidence
