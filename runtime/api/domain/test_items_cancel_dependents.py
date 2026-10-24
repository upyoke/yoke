"""Cancelling a blocker removes its dependents' edges and tells their holders.

Drives ``items.cancel.run`` end to end with the real recipient resolution
and message insert: every edge naming the cancelled item as blocker is
gone, the receipt lists each one, and each dependent with a live holder
gets exactly one notice naming the blocker and the replacement.
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
from runtime.api.domain.test_items_cancel import (
    _caller_session,  # noqa: F401
    _isolate_write_side_effects,  # noqa: F401
    SESSION,
    _request,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_core.domain.backlog_cancel_dependent_notice import cancelled_blocker_key
from yoke_core.domain.handlers.items_cancel import handle_cancel
from yoke_core.domain.work_claim_targets import make_item_target

BLOCKER = 9871
HELD = 9872
UNHELD = 9873
REPLACEMENT = 9874


def _edge(conn: Any, dependent: int, gate_point: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'status:done', 'test', '', %s)",
        (dependent, BLOCKER, gate_point, "2026-01-02T00:00:00Z"),
    )
    conn.commit()


def _seed(conn: Any, *, blocker_status: str = "implementing") -> None:
    _project(conn)
    for item_id in (BLOCKER, HELD, UNHELD, REPLACEMENT):
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="implementing",
        )
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (blocker_status, BLOCKER))
    conn.commit()
    _edge(conn, HELD, "activation")
    _edge(conn, HELD, "integration")
    _edge(conn, UNHELD, "activation")
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(HELD).scope_json(),
    )


def _blocker_edges(conn: Any) -> list:
    return conn.execute(
        "SELECT dependent_item_id FROM item_dependencies WHERE blocking_item_id=%s",
        (BLOCKER,),
    ).fetchall()


def _assert_reconciled(conn: Any, recon: dict) -> None:
    assert _blocker_edges(conn) == []
    assert [
        (edge["dependent_item"], edge["gate_point"]) for edge in recon["inbound_removed"]
    ] == [
        (f"YOK-{HELD}", "activation"),
        (f"YOK-{HELD}", "integration"),
        (f"YOK-{UNHELD}", "activation"),
    ]
    notices = {n["dependent_item"]: n for n in recon["holder_notices"]}
    assert notices[f"YOK-{UNHELD}"]["delivery"] == "no_live_holder"
    assert notices[f"YOK-{HELD}"]["holder_session_id"] == HOLDER_A
    assert notices[f"YOK-{HELD}"]["delivery"] in ("delivered", "undelivered")
    assert recon["notice_advisory"] == ""
    assert _recipients(conn, cancelled_blocker_key(BLOCKER, HELD)) == [HOLDER_A]
    assert _recipients(conn, cancelled_blocker_key(BLOCKER, UNHELD)) == []


def test_cancel_removes_inbound_edges_and_tells_each_live_holder_once(
    test_db: Any,
) -> None:
    _seed(test_db)

    outcome = handle_cancel(
        _request(BLOCKER, reason="superseded", ref=f"YOK-{REPLACEMENT}")
    )

    assert outcome.primary_success, outcome.error
    _assert_reconciled(test_db, outcome.result_payload["dependency_reconciliation"])
    [body] = _bodies(test_db, cancelled_blocker_key(BLOCKER, HELD))
    assert body.startswith(f"YOK-{BLOCKER} was cancelled (superseded).")
    assert f"Its replacement is YOK-{REPLACEMENT}." in body
    assert f"yoke items dependency add YOK-{HELD} YOK-{REPLACEMENT}" in body
    log = outcome.result_payload["log"]
    assert f"removed 3 dependency row(s) where YOK-{BLOCKER} was the blocker" in log
    assert f"Not notified: YOK-{UNHELD} has no live holder." in log


def test_abandon_merged_removes_inbound_edges_the_same_way(test_db: Any) -> None:
    _seed(test_db, blocker_status="release")
    test_db.execute(
        "UPDATE items SET merged_at=CURRENT_TIMESTAMP WHERE id=%s", (BLOCKER,)
    )
    test_db.commit()
    insert_steering_claim(test_db, SESSION, project_id=1)

    outcome = handle_cancel(
        _request(BLOCKER, reason="Cannot recover", abandon_merged=True)
    )

    assert outcome.primary_success, outcome.error
    _assert_reconciled(test_db, outcome.result_payload["dependency_reconciliation"])
    [body] = _bodies(test_db, cancelled_blocker_key(BLOCKER, HELD))
    assert "No replacement was named." in body


def test_notice_failure_keeps_the_cancel_and_names_the_recovery(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_core.domain import backlog_cancel_dependent_notice as notice

    def _boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("mail store offline")

    monkeypatch.setattr(notice, "push_notice", _boom)
    _seed(test_db)

    outcome = handle_cancel(_request(BLOCKER, reason="obsolete"))

    assert outcome.primary_success, outcome.error
    recon = outcome.result_payload["dependency_reconciliation"]
    assert _blocker_edges(test_db) == []
    assert recon["holder_notices"] == []
    assert recon["notice_advisory"].startswith("cancelled_blocker_notice_deferred:")
    assert "mail store offline" in recon["notice_advisory"]
    assert "yoke say --stdin --item" in recon["notice_advisory"]


def test_human_receipt_lists_removed_edges_and_notices(test_db: Any) -> None:
    import io
    from types import SimpleNamespace

    from yoke_cli.commands.adapters.items_cancel import _write_receipt

    _seed(test_db)
    outcome = handle_cancel(_request(BLOCKER, reason="obsolete"))
    stdout = io.StringIO()

    _write_receipt(SimpleNamespace(result=outcome.result_payload), stdout, io.StringIO())

    text = stdout.getvalue()
    assert "Removed 3 dependency edge(s) waiting on this item:" in text
    assert f"  - YOK-{HELD} gate=integration satisfaction=status:done" in text
    assert f"  Told YOK-{HELD}'s holder session {HOLDER_A} (" in text
    assert f"  YOK-{UNHELD} has no live holder; no message sent." in text
