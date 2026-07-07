"""Regression coverage for superseding no-claim exceptions."""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, item_id: int) -> None:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()


def _register_exception(conn, *, item_id: int, actor: int) -> int:
    from yoke_core.domain import path_claims_register

    return path_claims_register.register_for_item(
        conn,
        item_id=item_id,
        integration_target="main",
        paths=[],
        actor_id=actor,
        mode="exception",
        exception_reason="planning-only; files unknown",
    )


def _active_upstream_claim(conn, *, item_id: int, actor: int) -> int:
    from yoke_core.domain.path_claims import activate, register

    target = seed_target(conn, path_string="src/foo.py")
    upstream = register(
        conn,
        actor_id=actor,
        integration_target="main",
        target_ids=[target],
        item_id=item_id,
    )
    activate(conn, claim_id=upstream, base_commit_sha=SNAP)
    return upstream


def test_concrete_registration_cancels_active_exception(conn, monkeypatch):
    from yoke_core.domain import path_claims_events, path_claims_register

    emitted = []
    monkeypatch.setattr(
        path_claims_events,
        "emit_cancelled",
        lambda *, conn, claim, reason, project=None:
            emitted.append((claim["id"], reason)),
    )

    actor = local_human(conn)
    _seed_item(conn, 12301)
    seed_target(conn, path_string="src/foo.py")
    exception_id = _register_exception(conn, item_id=12301, actor=actor)
    concrete_id = path_claims_register.register_for_item(
        conn,
        item_id=12301,
        integration_target="main",
        paths=["src/foo.py"],
        actor_id=actor,
    )

    rows = conn.execute(
        "SELECT id, state, cancel_reason FROM path_claims "
        "WHERE id IN (%s, %s) ORDER BY id",
        (exception_id, concrete_id),
    ).fetchall()
    reason = f"superseded by concrete path claim {concrete_id}"
    assert [r["state"] for r in rows] == ["cancelled", "planned"]
    assert rows[0]["cancel_reason"] == reason
    assert emitted == [(exception_id, reason)]


def test_second_concrete_registration_widens_existing_claim(conn):
    from yoke_core.domain import path_claims_register

    actor = local_human(conn)
    _seed_item(conn, 12306)
    first = seed_target(conn, path_string="src/foo.py")
    second = seed_target(conn, path_string="src/bar.py")
    claim_id = path_claims_register.register_for_item(
        conn,
        item_id=12306,
        integration_target="main",
        paths=["src/foo.py"],
        actor_id=actor,
    )
    reused_id = path_claims_register.register_for_item(
        conn,
        item_id=12306,
        integration_target="main",
        paths=["src/bar.py"],
        actor_id=actor,
    )

    concrete_count = conn.execute(
        "SELECT COUNT(*) FROM path_claims WHERE item_id = %s "
        "AND mode <> 'exception'",
        (12306,),
    ).fetchone()[0]
    targets = [
        int(row[0])
        for row in conn.execute(
            "SELECT target_id FROM path_claim_targets WHERE claim_id = %s "
            "ORDER BY target_id",
            (claim_id,),
        )
    ]
    assert reused_id == claim_id
    assert concrete_count == 1
    assert targets == sorted([first, second])


def test_reused_concrete_claim_cancels_stale_exception(conn):
    from yoke_core.domain import path_claims_register

    actor = local_human(conn)
    _seed_item(conn, 12307)
    seed_target(conn, path_string="src/foo.py")
    seed_target(conn, path_string="src/bar.py")
    claim_id = path_claims_register.register_for_item(
        conn,
        item_id=12307,
        integration_target="main",
        paths=["src/foo.py"],
        actor_id=actor,
    )
    exception_id = _register_exception(conn, item_id=12307, actor=actor)
    reused_id = path_claims_register.register_for_item(
        conn,
        item_id=12307,
        integration_target="main",
        paths=["src/bar.py"],
        actor_id=actor,
    )

    states = conn.execute(
        "SELECT id, state FROM path_claims WHERE id IN (%s, %s) ORDER BY id",
        (claim_id, exception_id),
    ).fetchall()
    assert reused_id == claim_id
    assert [row["state"] for row in states] == ["planned", "cancelled"]


def test_multiple_existing_concrete_claims_block_registration(conn):
    from yoke_core.domain import path_claims_register
    from yoke_core.domain.path_claims import register
    from yoke_core.domain.path_claims_register_reconcile import (
        MultipleConcreteClaims,
    )

    actor = local_human(conn)
    _seed_item(conn, 12308)
    first = seed_target(conn, path_string="src/foo.py")
    second = seed_target(conn, path_string="src/bar.py")
    seed_target(conn, path_string="src/baz.py")
    register(
        conn,
        actor_id=actor,
        integration_target="main",
        target_ids=[first],
        item_id=12308,
    )
    register(
        conn,
        actor_id=actor,
        integration_target="main",
        target_ids=[second],
        item_id=12308,
    )

    with pytest.raises(MultipleConcreteClaims):
        path_claims_register.register_for_item(
            conn,
            item_id=12308,
            integration_target="main",
            paths=["src/baz.py"],
            actor_id=actor,
        )


def test_blocked_concrete_registration_still_cancels_exception(conn):
    from yoke_core.domain import path_claims_register

    actor = local_human(conn)
    _seed_item(conn, 12311)
    _seed_item(conn, 12312)
    upstream = _active_upstream_claim(conn, item_id=12311, actor=actor)
    exception_id = _register_exception(conn, item_id=12312, actor=actor)
    concrete_id = path_claims_register.register_for_item(
        conn,
        item_id=12312,
        integration_target="main",
        paths=["src/foo.py"],
        actor_id=actor,
        upstream_claim_id=upstream,
    )

    rows = conn.execute(
        "SELECT id, state FROM path_claims WHERE id IN (%s, %s) ORDER BY id",
        (exception_id, concrete_id),
    ).fetchall()
    assert [r["state"] for r in rows] == ["cancelled", "blocked"]


def test_failed_concrete_registration_leaves_exception_active(conn):
    from yoke_core.domain import path_claims_register

    actor = local_human(conn)
    _seed_item(conn, 12321)
    _seed_item(conn, 12322)
    _active_upstream_claim(conn, item_id=12321, actor=actor)
    exception_id = _register_exception(conn, item_id=12322, actor=actor)

    with pytest.raises(Exception):
        path_claims_register.register_for_item(
            conn,
            item_id=12322,
            integration_target="main",
            paths=["src/foo.py"],
            actor_id=actor,
        )

    state = conn.execute(
        "SELECT state FROM path_claims WHERE id = %s",
        (exception_id,),
    ).fetchone()["state"]
    assert state == "active"
