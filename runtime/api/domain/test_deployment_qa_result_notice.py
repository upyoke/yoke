"""A settled QA stage result reaches the audience its flow configured.

Real audience resolution and a real Inbox insert. This is the third
notification surface on a release and the cases hold it apart from the
other two: it addresses PEOPLE rather than the sessions the wait and
verdict wakes address, it fires for an item-scoped and a run-scoped
stage alike, and it reports rather than asks. A stage still waiting is
not a result, and a stage that configured no audience reports that
instead of inventing one.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _project
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    grant_actor_org_role,
    grant_actor_project_role,
)
from yoke_core.domain.deployment_qa_result_notice import (
    OUTCOME_PASSED,
    OUTCOME_REJECTED,
    notification_audience,
    notify_qa_stage_result,
    qa_result_idempotency_key,
)

LINEAGE = "e" * 40
OWNER = 9960
OPERATOR = 9961
OUTSIDER = 9962


def _member(conn: Any, actor_id: int, *, role: str) -> None:
    conn.execute(
        "INSERT INTO actors(id,kind,name,created_at) VALUES "
        "(%s,'human',%s,'2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (actor_id, f"member-{actor_id}"),
    )
    grant_actor_project_role(
        conn, actor_id=actor_id, project_id=1, role_name=role
    )
    for row in conn.execute("SELECT org_id FROM projects WHERE id=1").fetchall():
        if row["org_id"] is not None:
            grant_actor_org_role(
                conn,
                actor_id=actor_id,
                org_id=int(row["org_id"]),
                role_name=ROLE_ADMIN,
            )
    conn.commit()


def _owned_item(conn: Any, item_id: int, owner: int | None = OWNER) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        owner=str(owner) if owner is not None else None,
    )


def _inbox(conn: Any, key: str) -> tuple[list[int], str]:
    rows = conn.execute(
        "SELECT r.actor_id, m.body FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key = %s ORDER BY r.actor_id",
        (key,),
    ).fetchall()
    actors = [int(row["actor_id"]) for row in rows]
    return actors, str(rows[0]["body"]) if rows else ""


def _notify(conn: Any, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = dict(
        notification={
            "enabled": True,
            "recipients": {"roles": [], "actors": [], "item_owners": True},
        },
        run_id="run-result",
        stage_name="item-qa",
        member_item_id=9970,
        project_id=1,
        outcome=OUTCOME_PASSED,
        subject="YOK-9970",
        target_tier="stage",
        revision=LINEAGE,
        target_digest="digest-1",
    )
    payload.update(overrides)
    result = notify_qa_stage_result(conn, **payload)
    conn.commit()
    return result


def test_item_owners_audience_reaches_the_owner(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9970)

    result = _notify(test_db)

    assert result["notified"] == [OWNER]
    actors, body = _inbox(
        test_db,
        qa_result_idempotency_key("run-result", "item-qa", 9970, OUTCOME_PASSED, "digest-1"),
    )
    assert actors == [OWNER]
    assert "passed for YOK-9970" in body
    assert "on stage at" in body
    assert "nothing to approve" in body


def test_a_role_audience_reaches_its_holders_only(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OPERATOR, role=ROLE_OPERATOR)
    _member(test_db, OUTSIDER, role=ROLE_VIEWER)
    _owned_item(test_db, 9971, owner=None)

    result = _notify(
        test_db,
        notification={
            "enabled": True,
            "recipients": {"roles": [ROLE_OPERATOR], "item_owners": False},
        },
        member_item_id=9971,
        subject="YOK-9971",
    )

    assert result["notified"] == [OPERATOR]


def test_an_explicit_actor_and_the_owner_are_both_reached(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _member(test_db, OPERATOR, role=ROLE_OPERATOR)
    _owned_item(test_db, 9972)

    result = _notify(
        test_db,
        notification={
            "enabled": True,
            "recipients": {"actors": [OPERATOR], "item_owners": True},
        },
        member_item_id=9972,
        subject="YOK-9972",
    )

    assert result["notified"] == sorted([OWNER, OPERATOR])
    actors, _body = _inbox(
        test_db,
        qa_result_idempotency_key("run-result", "item-qa", 9972, OUTCOME_PASSED, "digest-1"),
    )
    assert actors == sorted([OWNER, OPERATOR])


def test_a_run_scoped_result_reports_the_whole_batch(test_db: Any) -> None:
    """A run-scoped stage has no member, so its audience cannot be owners."""
    _project(test_db)
    _member(test_db, OPERATOR, role=ROLE_OPERATOR)

    result = _notify(
        test_db,
        notification={
            "enabled": True,
            "recipients": {"roles": [ROLE_OPERATOR], "item_owners": True},
        },
        stage_name="release-qa",
        member_item_id=None,
        subject="the whole release batch",
        outcome=OUTCOME_REJECTED,
    )

    assert result["notified"] == [OPERATOR]
    actors, body = _inbox(
        test_db,
        qa_result_idempotency_key(
            "run-result", "release-qa", None, OUTCOME_REJECTED, "digest-1"
        ),
    )
    assert actors == [OPERATOR]
    assert "was rejected for the whole release batch" in body


def test_a_stage_that_configured_nothing_reports_that(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9973)

    disabled = _notify(
        test_db, notification={"enabled": False}, member_item_id=9973
    )
    absent = _notify(test_db, notification=None, member_item_id=9973)

    for result in (disabled, absent):
        assert result["notified"] == []
        assert "configured no notification audience" in result["reason"]


def test_an_audience_that_resolves_to_nobody_reports_that(test_db: Any) -> None:
    """A configured role with no holders is an empty audience, not a failure."""
    _project(test_db)
    _owned_item(test_db, 9974, owner=None)

    result = _notify(
        test_db,
        notification={
            "enabled": True,
            "recipients": {"roles": [ROLE_OPERATOR], "item_owners": True},
        },
        member_item_id=9974,
        subject="YOK-9974",
    )

    assert result["notified"] == []
    assert "configured no notification audience" in result["reason"]


def test_a_waiting_stage_is_not_a_result(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9975)

    result = _notify(test_db, member_item_id=9975, outcome="waiting")

    assert result["notified"] == []
    assert "not a settled stage result" in result["reason"]


def test_the_same_result_reported_twice_is_one_notice(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9976)

    _notify(test_db, member_item_id=9976, subject="YOK-9976")
    _notify(test_db, member_item_id=9976, subject="YOK-9976")

    actors, _body = _inbox(
        test_db,
        qa_result_idempotency_key("run-result", "item-qa", 9976, OUTCOME_PASSED, "digest-1"),
    )
    assert actors == [OWNER]


def test_a_later_rejection_is_its_own_event(test_db: Any) -> None:
    """Passed and rejected are different results, not a replaced one."""
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9977)

    _notify(test_db, member_item_id=9977, subject="YOK-9977")
    _notify(test_db, member_item_id=9977, subject="YOK-9977", outcome=OUTCOME_REJECTED)

    passed_key = qa_result_idempotency_key(
        "run-result", "item-qa", 9977, OUTCOME_PASSED, "digest-1"
    )
    rejected_key = qa_result_idempotency_key(
        "run-result", "item-qa", 9977, OUTCOME_REJECTED, "digest-1"
    )
    assert passed_key != rejected_key
    assert _inbox(test_db, passed_key)[0] == [OWNER]
    assert _inbox(test_db, rejected_key)[0] == [OWNER]


def test_audience_resolution_is_readable_without_sending(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, OWNER, role=ROLE_OWNER)
    _owned_item(test_db, 9978)

    assert notification_audience(
        test_db,
        notification={
            "enabled": True,
            "recipients": {"item_owners": True},
        },
        project_id=1,
        member_item_ids=(9978,),
    ) == [OWNER]
