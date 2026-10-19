"""The item detail read serves the item's shepherd verdicts."""

from yoke_core.domain import item_detail_read
from runtime.api.item_page_reads_test_support import _connection


def test_detail_read_returns_shepherd_verdicts_newest_first(monkeypatch):
    conn = _connection()
    conn.executemany(
        "INSERT INTO shepherd_verdicts (public_ref, transition, worker, "
        "verdict, caveats, attempt, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        [
            ("ACM-22", "refined_idea_to_planning", "boss", "CAVEATS",
             "Name the owner.", "2026-10-14T21:50:26Z"),
            ("ACM-22", "planning_to_plan_drafted", "boss", "CAVEATS",
             "Split the reader.", "2026-10-14T22:00:03Z"),
        ],
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    verdicts = item_detail_read.get_item_detail(51)["shepherd_verdicts"]

    assert [v["transition"] for v in verdicts] == [
        "planning_to_plan_drafted",
        "refined_idea_to_planning",
    ]
    assert verdicts[0]["verdict"] == "CAVEATS"
    assert verdicts[0]["caveats"] == "Split the reader."
    assert verdicts[0]["worker"] == "boss"


def test_detail_read_returns_no_verdicts_for_an_unreviewed_item(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    assert item_detail_read.get_item_detail(51)["shepherd_verdicts"] == []
