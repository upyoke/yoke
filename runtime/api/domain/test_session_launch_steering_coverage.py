"""Steering-origin launches refuse items this live seat does not cover."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_steering_coverage import (
    MISSING,
    MISMATCH,
    refuse_uncovered_steering_launch,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.work_claim_targets import make_steering_target
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    add_steering_claim,
    authorization,
    launch_connection,
)
from runtime.api.domain.test_session_launch_terminal_admission import (
    _NoCloseConnection,
    _create_payload,
    _fleet_policy,
    _write_counts,
)


AREA = "AREA-PLAN"


def _prepare(conn) -> None:
    try:
        conn.execute("ALTER TABLE harness_sessions ADD COLUMN terminated_at TEXT")
    except Exception:
        pass
    conn.execute("ALTER TABLE projects ADD COLUMN public_item_prefix TEXT")
    conn.execute("ALTER TABLE projects ADD COLUMN name TEXT DEFAULT 'Launch'")
    conn.execute("UPDATE projects SET public_item_prefix='LP' WHERE id=10")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "project_sequence INTEGER NOT NULL, title TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_strategy_docs ("
        "item_id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "strategy_doc_slug TEXT NOT NULL, linked_at TEXT NOT NULL)"
    )
    conn.commit()


def _seed_item(conn, *, linked: str | None = None, sequence: int = 41) -> str:
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, title) "
        "VALUES (?, 10, ?, 'Coverage target')",
        (sequence, sequence),
    )
    if linked is not None:
        conn.execute(
            "INSERT INTO item_strategy_docs "
            "(item_id, project_id, strategy_doc_slug, linked_at) "
            "VALUES (?, 10, ?, ?)",
            (sequence, linked, NOW),
        )
    conn.commit()
    return f"LP-{sequence}"


def _document_seat(
    conn, *, session_id: str, claim_id: int, document: str = AREA
) -> None:
    if session_id != "caller":
        conn.execute(
            "INSERT INTO harness_sessions (session_id, project_id, executor_surface) "
            "VALUES (?, 10, 'codex-cli')",
            (session_id,),
        )
    target = make_steering_target(10, document=document)
    conn.execute(
        "INSERT INTO work_claims "
        "(id, session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES (?, ?, ?, ?, 'exclusive', ?, ?)",
        (claim_id, session_id, target.kind, target.scope_json(), NOW, NOW),
    )
    conn.commit()


def _refuse(conn, public_ref: str):
    refuse_uncovered_steering_launch(
        conn, public_ref=public_ref, project_id=10, session_id="caller"
    )


def test_operator_origin_does_not_require_coverage() -> None:
    conn = launch_connection()
    _prepare(conn)
    ref = _seed_item(conn, linked=AREA)
    _refuse(conn, ref)


def test_project_seat_covers_an_unlinked_item() -> None:
    conn = launch_connection()
    _prepare(conn)
    add_steering_claim(conn)
    ref = _seed_item(conn)
    _refuse(conn, ref)


def test_missing_link_from_a_document_seat_is_refused() -> None:
    conn = launch_connection()
    _prepare(conn)
    _document_seat(conn, session_id="caller", claim_id=20)
    ref = _seed_item(conn)
    before = conn.execute("SELECT COUNT(*) FROM item_strategy_docs").fetchone()[0]
    with pytest.raises(SessionLaunchError) as raised:
        _refuse(conn, ref)
    assert raised.value.code == MISSING
    assert "unlinked" in str(raised.value)
    assert "does not assign an unrelated document silently" in str(raised.value)
    after = conn.execute("SELECT COUNT(*) FROM item_strategy_docs").fetchone()[0]
    assert after == before


def test_linked_item_with_no_covering_seat_is_missing_coverage() -> None:
    conn = launch_connection()
    _prepare(conn)
    add_steering_claim(conn)
    ref = _seed_item(conn, linked=AREA)
    with pytest.raises(SessionLaunchError) as raised:
        _refuse(conn, ref)
    assert raised.value.code == MISSING
    assert AREA in str(raised.value)
    assert "does not assign an unrelated document silently" in str(raised.value)


def test_item_covered_by_another_seat_is_mismatched() -> None:
    conn = launch_connection()
    _prepare(conn)
    add_steering_claim(conn)
    _document_seat(conn, session_id="other", claim_id=21)
    ref = _seed_item(conn, linked=AREA)
    with pytest.raises(SessionLaunchError) as raised:
        _refuse(conn, ref)
    assert raised.value.code == MISMATCH
    assert "other" in str(raised.value)


def test_document_seat_covers_its_own_linked_item() -> None:
    conn = launch_connection()
    _prepare(conn)
    _document_seat(conn, session_id="caller", claim_id=20)
    ref = _seed_item(conn, linked=AREA)
    _refuse(conn, ref)


def _pin_item(conn) -> str:
    definition = deepcopy(builtin_workflow_definition("dash")["definition"])
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN name TEXT DEFAULT 'Launch'")
    except Exception:
        pass
    conn.execute(
        "CREATE TABLE workflow_versions ("
        "id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL, version INTEGER, "
        "definition_json TEXT NOT NULL, definition_digest TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO workflow_versions "
        "(id, workflow_id, version, definition_json, definition_digest) "
        "VALUES (1, 'dash', 1, ?, ?)",
        (canonical_definition_json(definition), definition_digest(definition)),
    )
    conn.execute("DROP TABLE IF EXISTS items")
    conn.execute(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "project_sequence INTEGER NOT NULL, title TEXT, status TEXT, "
        "workflow_id TEXT, workflow_version_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, title, status, "
        "workflow_id, workflow_version_id) "
        "VALUES (41, 10, 41, 'Active launch target', 'idea', 'dash', 1)"
    )
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (41, 10, ?, ?)",
        (AREA, NOW),
    )
    conn.commit()
    return "LP-41"


def test_steering_create_refuses_missing_coverage_before_any_write(monkeypatch) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    _prepare(conn)
    add_steering_claim(conn)
    item = _pin_item(conn)
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(handlers, "_authorization", lambda *_a, **_k: authorization())
    monkeypatch.setattr(handlers, "_fleet_policy", _fleet_policy)
    before = _write_counts(conn)
    outcome = handlers.handle_launch_create(
        FunctionCallRequest(
            function="session.launch.create",
            actor=ActorContext(actor_id="1", session_id="caller"),
            target=TargetRef(kind="global"),
            payload=_create_payload(item, compose_mandate=True, key="cov-1"),
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == MISSING
    assert _write_counts(conn) == before
