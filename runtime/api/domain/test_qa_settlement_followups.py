"""Owed settlement follow-ups replay durably, and a failure stays visible."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_member_close_out_retry as close_out
from yoke_core.domain import qa_settlement_followups as followups
from yoke_core.domain.db_helpers import utc_now

ITEM = 7101


def _rows(conn: Any) -> list[tuple[int, int, str]]:
    rows = conn.execute(
        "SELECT item_id, attempts, last_error FROM qa_settlement_followups "
        "ORDER BY item_id"
    ).fetchall()
    return [(int(row[0]), int(row[1]), str(row[2])) for row in rows]


@pytest.fixture
def owed(test_db: Any, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    insert_item(test_db, id=ITEM, status="release")
    followups.request_settlement_followup(test_db, item_id=ITEM)
    test_db.commit()
    replayed: list[int] = []
    monkeypatch.setattr(
        close_out,
        "after_record_settled",
        lambda _conn, *, item_id: replayed.append(item_id),
    )
    return replayed


def test_a_replayed_follow_up_leaves_the_queue(test_db: Any, owed: list[int]) -> None:
    assert followups.replay_settlement_followups(test_db)["replayed"] == [ITEM]

    assert owed == [ITEM]
    assert _rows(test_db) == []


def test_a_failed_replay_keeps_its_error_and_retries_later(
    test_db: Any, monkeypatch: pytest.MonkeyPatch, owed: list[int]
) -> None:
    def fail(_conn: Any, *, item_id: int) -> None:
        raise RuntimeError("settlement read refused")

    monkeypatch.setattr(close_out, "after_record_settled", fail)
    now = utc_now()

    assert followups.replay_settlement_followups(test_db, now=now)["failed"] == [ITEM]
    assert _rows(test_db) == [(ITEM, 1, "RuntimeError: settlement read refused")]
    # The next cycle inside the retry window leaves it alone.
    assert followups.replay_settlement_followups(test_db, now=now) == {
        "replayed": [],
        "failed": [],
    }

    monkeypatch.setattr(
        close_out, "after_record_settled", lambda _conn, *, item_id: owed.append(item_id)
    )
    later = now + timedelta(seconds=followups.RETRY_AFTER_SECONDS + 1)

    assert followups.replay_settlement_followups(test_db, now=later)["replayed"] == [
        ITEM
    ]
    assert _rows(test_db) == []


def test_a_request_made_during_a_replay_is_kept_for_the_next_cycle(
    test_db: Any, monkeypatch: pytest.MonkeyPatch, owed: list[int]
) -> None:
    def waive_again(conn: Any, *, item_id: int) -> None:
        followups.request_settlement_followup(conn, item_id=item_id)
        conn.commit()

    monkeypatch.setattr(close_out, "after_record_settled", waive_again)
    followups.replay_settlement_followups(test_db)

    assert _rows(test_db) == [(ITEM, 0, "")]
    monkeypatch.setattr(
        close_out, "after_record_settled", lambda _conn, *, item_id: owed.append(item_id)
    )
    assert followups.replay_settlement_followups(test_db)["replayed"] == [ITEM]
