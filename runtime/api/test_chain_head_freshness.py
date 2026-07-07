"""Tests for ``yoke_core.domain.chain_head_freshness``.

Covers holder/no-holder branches, heartbeat and task-activity freshness
windows, malformed/ended prior sessions, and per-task scoping. Task
recency reads ``epic_tasks.last_activity_at`` (first-class state; the
events ledger is telemetry-only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import chain_head_freshness
from yoke_core.domain.chain_head_freshness import (
    STATUS_BLOCKED,
    STATUS_BUSY,
    STATUS_RESUMABLE,
    evaluate_chain_head_freshness,
    resolve_freshness_window_s,
)
from runtime.api.test_dependency_schema import create_dependency_test_db


_EPIC_ID = 1684
_TASK_NUM = 3
_FRESHNESS_WINDOW_S = 60
_NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stale_ts(seconds: int) -> str:
    return (_NOW - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def conn() -> Any:
    """Authority-shaped session/claim/task schema on disposable Postgres."""
    c = create_dependency_test_db()
    c.execute(
        """
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            title TEXT,
            last_activity_at TEXT,
            UNIQUE(epic_id, task_num)
        )
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def _seed_prior(
    conn: Any,
    *,
    session_id: str = "sess-prior",
    heartbeat_age_s: Optional[int] = None,
    heartbeat_raw: Optional[str] = None,
    ended: bool = False,
    released: bool = True,
    item_id: int = _EPIC_ID,
) -> None:
    if heartbeat_raw is None and heartbeat_age_s is not None:
        heartbeat_raw = _stale_ts(heartbeat_age_s)
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, last_heartbeat, ended_at) "
        f"VALUES ({p}, {p}, {p})",
        (
            session_id,
            heartbeat_raw,
            _stale_ts(heartbeat_age_s or 0) if ended else None,
        ),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        f"claimed_at, released_at) VALUES ({p}, 'item', {p}, {p}, {p})",
        (
            session_id,
            item_id,
            _stale_ts(heartbeat_age_s or 0),
            _stale_ts(heartbeat_age_s or 0) if released else None,
        ),
    )


def _seed_task_activity(
    conn: Any,
    *,
    age_s: Optional[int],
    epic_id: int = _EPIC_ID,
    task_num: int = _TASK_NUM,
) -> None:
    """Insert an epic_tasks row whose last_activity_at is ``age_s`` old
    (``age_s=None`` seeds NULL — no recorded activity)."""
    p = _p(conn)
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, last_activity_at) "
        f"VALUES ({p}, {p}, 't', {p})",
        (epic_id, task_num, _stale_ts(age_s) if age_s is not None else None),
    )


@pytest.fixture(autouse=True)
def stub_who_claims(monkeypatch):
    holder = {"row": None}
    monkeypatch.setattr(
        chain_head_freshness, "who_claims_for_item",
        lambda item_id: holder["row"],
    )

    def set_live(session_id: Optional[str]):
        holder["row"] = (
            {"session_id": session_id} if session_id is not None else None
        )

    return set_live


def _evaluate(conn, current="sess-current"):
    return evaluate_chain_head_freshness(
        _EPIC_ID, _TASK_NUM, current, conn=conn,
        freshness_window_s=_FRESHNESS_WINDOW_S, now=_NOW,
    )


def test_blocked_when_other_session_holds_parent_claim(conn, stub_who_claims):
    stub_who_claims("sess-other")
    decision = _evaluate(conn)
    assert decision.status == STATUS_BLOCKED
    assert decision.evidence.holder_session_id == "sess-other"
    assert decision.evidence.holder_is_self is False
    assert "another live session" in decision.rationale


def test_busy_when_no_holder_but_heartbeat_within_window(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S - 10)
    decision = _evaluate(conn)
    assert decision.status == STATUS_BUSY
    assert decision.evidence.prior_heartbeat_age_s == _FRESHNESS_WINDOW_S - 10
    assert decision.evidence.recent_task_activity_age_s is None
    assert "inside freshness window" in decision.rationale


def test_busy_when_self_holds_and_task_activity_recent(conn, stub_who_claims):
    stub_who_claims("sess-current")
    _seed_prior(
        conn, session_id="sess-current",
        heartbeat_age_s=_FRESHNESS_WINDOW_S * 2, released=False,
    )
    _seed_task_activity(conn, age_s=15)
    decision = _evaluate(conn)
    assert decision.status == STATUS_BUSY
    assert decision.evidence.holder_is_self is True
    assert decision.evidence.recent_task_activity_age_s == 15
    assert "task activity" in decision.rationale


def test_busy_when_both_signals_within_window(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=5)
    _seed_task_activity(conn, age_s=10)
    decision = _evaluate(conn)
    assert decision.status == STATUS_BUSY
    assert "both inside" in decision.rationale


def test_resumable_when_no_holder_stale_heartbeat_no_activity(
    conn, stub_who_claims
):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.prior_session_id == "sess-prior"
    assert decision.evidence.recent_task_activity_age_s is None


def test_resumable_when_task_activity_is_also_stale(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10)
    _seed_task_activity(conn, age_s=_FRESHNESS_WINDOW_S * 5)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.recent_task_activity_age_s == _FRESHNESS_WINDOW_S * 5


def test_resumable_when_self_holds_with_stale_signals(conn, stub_who_claims):
    stub_who_claims("sess-current")
    _seed_prior(
        conn, session_id="sess-current",
        heartbeat_age_s=_FRESHNESS_WINDOW_S * 10, released=False,
    )
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.holder_is_self is True
    assert "current session" in decision.rationale


def test_resumable_when_no_prior_session_row(conn, stub_who_claims):
    stub_who_claims(None)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.prior_session_id is None
    assert "no prior session row" in decision.rationale


def test_resumable_when_prior_session_ended_with_stale_heartbeat(
    conn, stub_who_claims
):
    stub_who_claims(None)
    _seed_prior(
        conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10, ended=True,
    )
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.prior_session_ended is True


def test_resumable_when_heartbeat_unparseable(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_raw="not-a-timestamp")
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.prior_heartbeat_age_s is None
    assert "unparseable" in decision.rationale


def test_freshness_window_boundary_at_window_is_outside(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.prior_heartbeat_age_s == _FRESHNESS_WINDOW_S


def test_freshness_window_boundary_just_inside_is_busy(conn, stub_who_claims):
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S - 1)
    decision = _evaluate(conn)
    assert decision.status == STATUS_BUSY


def test_unrelated_task_activity_does_not_keep_task_busy(conn, stub_who_claims):
    """AC-10: per-task scoping is structural — a sibling task's recent
    activity must not keep this task head busy."""
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10)
    _seed_task_activity(conn, age_s=5, task_num=_TASK_NUM + 99)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.recent_task_activity_age_s is None


def test_task_with_null_activity_reads_as_absent(conn, stub_who_claims):
    """NULL last_activity_at means no mutation recorded — never busy."""
    stub_who_claims(None)
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10)
    _seed_task_activity(conn, age_s=None)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.recent_task_activity_age_s is None


def test_missing_epic_tasks_table_reads_as_absent(conn, stub_who_claims):
    """Minimal fixture without epic_tasks: activity is simply absent."""
    stub_who_claims(None)
    conn.execute("DROP TABLE epic_tasks")
    conn.commit()
    _seed_prior(conn, heartbeat_age_s=_FRESHNESS_WINDOW_S * 10)
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.recent_task_activity_age_s is None


def test_resumable_when_current_active_masks_stale_prior_other_session(
    conn, stub_who_claims
):
    """S3b shape: ``_prior_session_for_epic`` must skip the current
    session's own fresh active row so the stale genuine prior surfaces."""
    stub_who_claims("sess-current")
    _seed_prior(
        conn,
        session_id="sess-other-prior",
        heartbeat_age_s=_FRESHNESS_WINDOW_S * 10,
    )
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, last_heartbeat, ended_at) "
        f"VALUES ({p}, {p}, NULL)",
        ("sess-current", _stale_ts(_FRESHNESS_WINDOW_S // 2)),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        f"claimed_at, released_at) VALUES ({p}, 'item', {p}, {p}, NULL)",
        ("sess-current", _EPIC_ID, _stale_ts(5)),
    )
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.holder_is_self is True
    assert decision.evidence.prior_session_id == "sess-other-prior"
    assert decision.evidence.prior_heartbeat_age_s == _FRESHNESS_WINDOW_S * 10


def test_resumable_when_current_active_is_only_claim_row(conn, stub_who_claims):
    """Fresh-claim case: when my own active claim is the only row, the
    prior-session lookup returns ``None`` ("no prior session row" /
    RESUMABLE) rather than re-reading my own recent heartbeat as evidence
    of a competing dispatch."""
    stub_who_claims("sess-current")
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, last_heartbeat, ended_at) "
        f"VALUES ({p}, {p}, NULL)",
        ("sess-current", _stale_ts(_FRESHNESS_WINDOW_S // 2)),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        f"claimed_at, released_at) VALUES ({p}, 'item', {p}, {p}, NULL)",
        ("sess-current", _EPIC_ID, _stale_ts(5)),
    )
    decision = _evaluate(conn)
    assert decision.status == STATUS_RESUMABLE
    assert decision.evidence.holder_is_self is True
    assert decision.evidence.prior_session_id is None
    assert "no prior session row" in decision.rationale


def test_resolve_freshness_window_returns_default_without_config(monkeypatch):
    monkeypatch.setattr(
        chain_head_freshness,
        "get_seconds",
        lambda key, default: default,
    )
    assert resolve_freshness_window_s() == chain_head_freshness.DEFAULT_FRESHNESS_WINDOW_S


def test_resolve_freshness_window_explicit_override_wins():
    assert resolve_freshness_window_s(override_s=42) == 42
