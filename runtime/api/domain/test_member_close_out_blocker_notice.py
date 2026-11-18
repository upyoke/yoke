"""The item-QA acceptance notice names every close-out blocker, once per set.

A delivery-satisfied member refused by a closure dependency can also owe
another target's plan credit. Its owner's notice names both and never calls
the delivery satisfied. The notice is keyed on blocker identities, so a
blocker whose status moves sends nothing, a blocker that clears sends
nothing (its own dependency notice reports it), and a new blocker sends one.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _project,
    _run,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
)
from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _ready_member,
)
from runtime.api.domain.satisfied_delivery_member_close_out_test_support import (
    _settled_member_requirement,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_qa_plan_credit, member_close_out_blockers
from yoke_core.domain import deployment_qa_member_acceptance_notice as notice
from yoke_core.domain.no_obligation_member_close_out import (
    close_out_satisfied_delivery_member,
)

MEMBER = 9841
FIRST_BLOCKER = 9842
SECOND_BLOCKER = 9843
RUN_ID = "run-blocker-set-notice"
STAGE_WAIT = "Awaiting stage plan happy-path-checks-wsl QA credit on deployment run run-s."


def _depend(conn: Any, blocker: int) -> None:
    insert_item(conn, id=blocker, project_sequence=blocker, status="release")
    conn.execute(
        "INSERT INTO item_dependencies(dependent_item_id,blocking_item_id,"
        "gate_point,satisfaction,source,created_at) "
        "VALUES(%s,%s,'closure','status:done','operator','2026-10-01T00:00:00Z')",
        (MEMBER, blocker),
    )
    conn.commit()


def _member_owing_stage_credit(conn: Any, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _project(conn)
    _ready_member(conn, MEMBER, HOLDER_A)
    _depend(conn, FIRST_BLOCKER)
    _run(conn, RUN_ID, flow=COMPLETION_FLOW, members=(MEMBER,))
    _settled_member_requirement(conn, item_id=MEMBER, run_id=RUN_ID, resolution="pass")
    monkeypatch.setattr(
        deployment_qa_plan_credit, "other_target_plan_wait", lambda *_a, **_k: STAGE_WAIT
    )
    monkeypatch.setattr(
        member_close_out_blockers, "owed_plan_targets", lambda *_a, **_k: ("7@stage",)
    )


def _notify(conn: Any) -> str:
    member = {"item_id": MEMBER, "project_id": 1, "public_ref": f"YOK-{MEMBER}"}
    return notice._close_or_notify(
        conn,
        run_id=RUN_ID,
        item_id=MEMBER,
        route=(member, True),
        now=notice.parse_instant(notice.utc_now()),
    )


def _notices(conn: Any) -> list[tuple[str, str]]:
    prefix = notice.item_qa_accepted_idempotency_key(MEMBER, RUN_ID)
    rows = conn.execute(
        "SELECT idempotency_key,body FROM session_messages "
        "WHERE idempotency_key LIKE %s ORDER BY created_at",
        (prefix + "%",),
    ).fetchall()
    return [(row["idempotency_key"], row["body"]) for row in rows]


def _set_status(conn: Any, item_id: int, status: str) -> None:
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (status, item_id))
    conn.commit()


def test_a_closure_refusal_with_owed_stage_credit_names_both(
    test_db: Any, monkeypatch
) -> None:
    _member_owing_stage_credit(test_db, monkeypatch)

    closed = close_out_satisfied_delivery_member(
        test_db, item_id=MEMBER, public_ref=f"YOK-{MEMBER}", run_id=RUN_ID
    )
    assert closed.applies and not closed.ok
    assert closed.pending_credit == STAGE_WAIT
    assert closed.blockers == (f"closure:YOK-{FIRST_BLOCKER}", "plan:7@stage")

    _notify(test_db)

    [(key, body)] = _notices(test_db)
    assert key.endswith(f":blocked:closure:YOK-{FIRST_BLOCKER},plan:7@stage")
    assert "closure dependency(ies) remain unsatisfied" in body
    assert f"YOK-{FIRST_BLOCKER}" in body
    assert STAGE_WAIT in body
    assert "satisfied post-deploy delivery" not in body
    assert "auto-close this item when" not in body


def test_the_same_blockers_with_changed_statuses_send_nothing(
    test_db: Any, monkeypatch
) -> None:
    _member_owing_stage_credit(test_db, monkeypatch)
    _notify(test_db)

    _set_status(test_db, FIRST_BLOCKER, "implementing")
    assert _notify(test_db) == ""

    assert len(_notices(test_db)) == 1


def test_a_cleared_blocker_sends_nothing_and_a_new_one_sends_once(
    test_db: Any, monkeypatch
) -> None:
    _member_owing_stage_credit(test_db, monkeypatch)
    _notify(test_db)

    _depend(test_db, SECOND_BLOCKER)
    _notify(test_db)
    _notify(test_db)
    notices = _notices(test_db)
    assert len(notices) == 2
    assert f"YOK-{SECOND_BLOCKER}" in notices[1][0]
    assert f"YOK-{FIRST_BLOCKER}" in notices[1][1]

    _set_status(test_db, FIRST_BLOCKER, "done")
    assert _notify(test_db) == ""
    assert len(_notices(test_db)) == 2
