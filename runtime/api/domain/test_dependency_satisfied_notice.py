"""A blocker's landing tells each dependent whose gate it cleared, for real.

Uses the actual recipient resolution and message insert, so a parked
dependent's holder receives a stored message, the key keeps it to one, and
an edge that gates nothing stays silent.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import dependency_satisfied_notice as notice
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.work_claim_targets import make_item_target

BLOCKER = 9851
OTHER_BLOCKER = 9852
DEPENDENT = 9853


def _items(conn: Any) -> None:
    _project(conn)
    for item_id in (BLOCKER, OTHER_BLOCKER, DEPENDENT):
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="implementing",
        )
    conn.execute(
        "UPDATE items SET merged_at=%s WHERE id=%s", ("2026-01-03T00:00:00Z", BLOCKER)
    )
    conn.commit()


def _edge(conn: Any, blocker: int, gate_point: str, satisfaction: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '', %s)",
        (DEPENDENT, blocker, gate_point, satisfaction, "2026-01-02T00:00:00Z"),
    )
    conn.commit()


def _parked_dependent(conn: Any) -> None:
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(DEPENDENT).scope_json(),
    )
    set_session_mode(conn, HOLDER_A, SESSION_MODE_PARKED, "awaiting blocker merge")


def _key(conn: Any, gate_point: str) -> str:
    row = conn.execute(
        "SELECT id FROM item_dependencies WHERE dependent_item_id=%s "
        "AND blocking_item_id=%s AND gate_point=%s",
        (DEPENDENT, BLOCKER, gate_point),
    ).fetchone()
    return notice.dependency_satisfied_key(DEPENDENT, BLOCKER, gate_point, row[0])


def test_landing_tells_the_parked_dependent_once(test_db: Any) -> None:
    _items(test_db)
    _edge(test_db, BLOCKER, "activation", "fact:merged")
    _parked_dependent(test_db)

    reports, advisory = notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )
    again, _ = notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )

    assert advisory == ""
    assert [r["gate_point"] for r in reports] == ["activation"]
    assert reports[0]["delivery"] in ("delivered", "undelivered")
    assert len(again) == 1
    assert _recipients(test_db, _key(test_db, "activation")) == [HOLDER_A]
    [body] = _bodies(test_db, _key(test_db, "activation"))
    blocker_ref = render_item_ref(test_db, BLOCKER)
    assert body.startswith(f"{blocker_ref} merged; your activation gate fact:merged")
    assert "is satisfied — resume." in body
    assert "No other gates remain." in body


def test_partially_satisfied_dependent_is_told_what_remains(test_db: Any) -> None:
    _items(test_db)
    _edge(test_db, BLOCKER, "integration", "fact:merged")
    _edge(test_db, OTHER_BLOCKER, "activation", "status:done")
    _parked_dependent(test_db)

    notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )

    [body] = _bodies(test_db, _key(test_db, "integration"))
    other_ref = render_item_ref(test_db, OTHER_BLOCKER)
    assert "resume" not in body
    assert f"Still unmet: {other_ref} activation gate status:done" in body


def test_coordination_only_and_unsatisfied_edges_send_nothing(test_db: Any) -> None:
    _items(test_db)
    _edge(test_db, BLOCKER, "coordination_only", "fact:merged")
    _edge(test_db, OTHER_BLOCKER, "activation", "status:done")
    _parked_dependent(test_db)

    for blocker in (BLOCKER, OTHER_BLOCKER):
        reports, _ = notice.notify_after_commit(
            test_db, blocking_item_id=blocker, event=notice.EVENT_MERGED
        )
        assert reports == []
    assert _bodies(test_db, _key(test_db, "coordination_only")) == []


def test_unheld_dependent_reaches_steering_with_staffing_text() -> None:
    body = notice.satisfied_message(
        "steering",
        blocker_ref="YOK-1",
        dependent_ref="YOK-2",
        event=notice.EVENT_DONE,
        gate_point="closure",
        satisfaction="status:done",
        remaining=[],
    )
    assert body.startswith("YOK-1 reached done; YOK-2's closure gate status:done")
    assert "no live claim holder. Route normal staffing" in body


def test_failed_send_keeps_the_trigger_and_names_recovery(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _items(test_db)
    _edge(test_db, BLOCKER, "activation", "fact:merged")

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("relay offline")

    monkeypatch.setattr(notice, "push_notice", boom)
    reports, advisory = notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )

    assert reports == []
    assert advisory.startswith("dependency_notice_deferred:")
    assert "relay offline" in advisory
    assert "yoke items dependency list" in advisory
    row = test_db.execute(
        "SELECT merged_at FROM items WHERE id=%s", (BLOCKER,)
    ).fetchone()
    assert row[0] is not None


def test_transition_to_done_tells_the_dependent(test_db: Any) -> None:
    import io

    from yoke_core.domain.backlog_update_effects import (
        UpdateEffectReceipt,
        run_post_commit_update_effects,
    )

    _items(test_db)
    _edge(test_db, BLOCKER, "closure", "status:done")
    _parked_dependent(test_db)
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (BLOCKER,))
    test_db.commit()

    receipt = UpdateEffectReceipt(
        status_event=(BLOCKER, "release", "done", "test"),
        session_id=None,
        messages=(),
    )
    run_post_commit_update_effects(test_db, receipt=receipt, out=io.StringIO())

    [body] = _bodies(test_db, _key(test_db, "closure"))
    assert " reached done; your closure gate status:done " in body


@pytest.mark.parametrize("gate_point", ["activation", "integration", "closure"])
def test_unheld_notice_checks_remaining_activation_before_staffing(test_db, gate_point):
    _items(test_db)
    _edge(test_db, BLOCKER, "integration", "fact:merged")
    _edge(test_db, OTHER_BLOCKER, gate_point, "status:done")
    remaining = notice._remaining_gates(test_db, DEPENDENT, BLOCKER)
    body = notice.satisfied_message(
        "steering",
        blocker_ref=render_item_ref(test_db, BLOCKER),
        dependent_ref=render_item_ref(test_db, DEPENDENT),
        event=notice.EVENT_MERGED,
        gate_point="integration",
        satisfaction="fact:merged",
        remaining=remaining,
    )
    if gate_point == "activation":
        assert (
            f"still waits on {render_item_ref(test_db, OTHER_BLOCKER)} activation gate; do not staff it yet"
            in body
        )
        assert "Route normal staffing" not in body
    else:
        assert "Route normal staffing" in body
    assert f"{gate_point} gate status:done" in body


def test_recreated_merge_wait_gets_a_fresh_notice(test_db):
    _items(test_db)
    _edge(test_db, BLOCKER, "integration", "fact:merged")
    _parked_dependent(test_db)
    notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )
    old_key = _key(test_db, "integration")
    test_db.execute(
        "DELETE FROM item_dependencies WHERE dependent_item_id=%s", (DEPENDENT,)
    )
    _edge(test_db, BLOCKER, "integration", "fact:merged")
    test_db.execute(
        "UPDATE item_dependencies SET created_at=%s WHERE dependent_item_id=%s",
        ("2026-01-04T00:00:00Z", DEPENDENT),
    )
    test_db.commit()
    assert (
        notice.notify_after_commit(
            test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
        )[0]
        == []
    )
    test_db.execute(
        "UPDATE items SET merged_at=%s WHERE id=%s", ("2026-01-05T00:00:00Z", BLOCKER)
    )
    test_db.commit()
    reports, advisory = notice.notify_after_commit(
        test_db, blocking_item_id=BLOCKER, event=notice.EVENT_MERGED
    )
    assert advisory == ""
    assert len(reports) == 1
    assert _key(test_db, "integration") != old_key
    assert len(_bodies(test_db, old_key)) == 1
    assert len(_bodies(test_db, _key(test_db, "integration"))) == 1
