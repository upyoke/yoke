"""Admission accepts any configured level and ignores launch stamps."""

import pytest
from yoke_contracts.levels import parse_levels
from yoke_core.domain import session_work_eligibility as admission
from yoke_core.domain.sessions_analytics import SessionError
from runtime.api.fixtures.level_store import levels_doc
from runtime.api.fixtures.model_catalog import RECORDS


@pytest.fixture
def configured(monkeypatch):
    levels = parse_levels(
        levels_doc(
            ("INTERN", [{"model": "claude-haiku-5-5", "min_effort": "max"}]),
            ("JUNIOR", [{"model": "grok-4.7", "min_effort": "high"}]),
        )
    )
    monkeypatch.setattr(
        admission, "effective_levels", lambda *args: (levels, "universe")
    )
    monkeypatch.setattr(admission, "current_model_records", lambda conn: RECORDS)


def test_any_matching_configured_level_admits_work(configured):
    assert (
        admission.require_work_selection(
            None,
            project_id=1,
            executor="cursor",
            model="grok-4.7-high-fast",
            reasoning_effort=None,
        )
        == "JUNIOR"
    )


@pytest.mark.parametrize(
    "model,effort", [("unknown", "high"), ("grok-4.7", None), ("grok-4.7", "low")]
)
def test_unknown_or_below_all_options_refuses_with_recovery(configured, model, effort):
    with pytest.raises(SessionError) as refusal:
        admission.require_work_selection(
            None, project_id=1, executor="cursor", model=model, reasoning_effort=effort
        )
    assert refusal.value.code == "SESSION_BELOW_INTERN"
    assert "Recovery:" in str(refusal.value)


def test_steering_process_claim_never_reads_model_facts():
    from yoke_core.domain.work_claim_targets import make_steering_target

    admission.require_session_work_eligibility(
        None, "unknown-session", make_steering_target(1)
    )


@pytest.mark.parametrize("work_required", [False, True])
def test_launch_guard_exempts_only_itemless_steering(
    configured, monkeypatch, work_required
):
    from types import SimpleNamespace
    from yoke_core.domain import session_launch_request_storage as storage
    from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError

    selected = SimpleNamespace(model="unknown", reasoning_effort=None)
    monkeypatch.setattr(storage, "resolve_machine_selection", lambda *a, **kw: selected)
    request = LaunchRequest(
        project_id=1,
        executor_surface="cursor-cli",
        instructions="Inspect",
        idempotency_key="guard",
        work_required=work_required,
    )
    relay = SimpleNamespace(machine_id="m1", surface="cursor-cli")
    if work_required:
        with pytest.raises(
            SessionLaunchError, match="session_model_unknown"
        ) as refusal:
            storage.resolve_work_launch_selection(None, request=request, relay=relay)
        assert refusal.value.code == "session_below_intern"
    else:
        assert (
            storage.resolve_work_launch_selection(None, request=request, relay=relay)
            is selected
        )


@pytest.fixture
def work_conn():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE projects(id INTEGER, slug TEXT);
        INSERT INTO projects VALUES(1, 'garden'), (2, 'office');
        CREATE TABLE items(id INTEGER, title TEXT, project_id INTEGER);
        INSERT INTO items VALUES(3, 'Plant trees', 1);
        CREATE TABLE item_refs(item_id INTEGER, public_ref TEXT);
        INSERT INTO item_refs VALUES(3, 'GAR-3');
        CREATE TABLE harness_sessions(session_id TEXT, project_id INTEGER,
            executor TEXT, model TEXT, current_item_id INTEGER, ended_at TEXT);
        INSERT INTO harness_sessions VALUES('session', 1, 'cursor', 'grok-4.7-high-fast', NULL, NULL);
        CREATE TABLE work_claims(id INTEGER);
    """)
    yield conn
    conn.close()


def _target(epic=False):
    from yoke_core.domain.work_claim_targets import (
        make_item_target,
        make_epic_task_target,
    )

    return make_epic_task_target(3, 1) if epic else make_item_target(3)


@pytest.mark.parametrize("epic", [False, True])
@pytest.mark.parametrize(
    "project,code",
    [(None, "SESSION_MACHINE_SCOPE_WORK_REFUSED"), (2, "SESSION_PROJECT_MISMATCH")],
)
def test_project_scope_refused_without_claim(work_conn, epic, project, code):
    work_conn.execute("UPDATE harness_sessions SET project_id=?", (project,))
    with pytest.raises(SessionError) as refusal:
        from yoke_core.domain.sessions_lifecycle_claim import claim_work

        claim_work(work_conn, session_id="session", target=_target(epic))
    assert refusal.value.code == code
    assert "GAR-3 (Plant trees)" in str(refusal.value)
    assert "garden project folder" in str(refusal.value)
    assert "sessions never switch projects" in str(refusal.value)
    assert work_conn.execute("SELECT COUNT(*) FROM work_claims").fetchone()[0] == 0
    assert (
        work_conn.execute("SELECT current_item_id FROM harness_sessions").fetchone()[0]
        is None
    )


def test_matching_project_session_admitted(work_conn, configured):
    admission.require_session_work_eligibility(work_conn, "session", _target())


def test_recheck_after_lock_refuses(work_conn, configured, monkeypatch):
    from yoke_core.domain import sessions_lifecycle_claim as claims

    def lock(conn, ids):
        conn.execute("UPDATE harness_sessions SET project_id=2")
        return {"session": None}

    monkeypatch.setattr(claims, "lock_session_rows_for_claim_lifecycle", lock)
    monkeypatch.setattr(
        claims.binding_lock, "lock_work_claim_target_workflow_binding", lambda *a: None
    )
    # The empty conflict table lets the real acquisition reach its post-lock check.
    work_conn.execute("DROP TABLE work_claims")
    work_conn.execute(
        "CREATE TABLE work_claims(target_kind TEXT, scope TEXT, session_id TEXT, released_at TEXT, claim_type TEXT)"
    )
    with pytest.raises(SessionError) as refusal:
        claims.claim_work(work_conn, session_id="session", target=_target())
    assert refusal.value.code == "SESSION_PROJECT_MISMATCH"
    assert work_conn.execute("SELECT COUNT(*) FROM work_claims").fetchone()[0] == 0
    assert (
        work_conn.execute("SELECT current_item_id FROM harness_sessions").fetchone()[0]
        is None
    )
