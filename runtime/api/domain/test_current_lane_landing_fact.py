"""An old landing cannot describe the head of a reopened lane."""

import sqlite3

from yoke_core.domain.turn_end_relay_continuation import continuation_notice
from yoke_core.domain.turn_end_unfinished_work import (
    lane_head_landed_sql,
    landed_but_open,
)


def test_only_a_receipt_for_the_recorded_head_proves_landing():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE items(id INTEGER);
        CREATE TABLE item_worktrees(item_id INTEGER, commit_sha TEXT);
        CREATE TABLE item_landings(item_id INTEGER, candidate_sha TEXT);
        INSERT INTO items VALUES(1);
        INSERT INTO item_worktrees VALUES(1,'correction');
        INSERT INTO item_landings VALUES(1,'earlier');
    """)
    query = f"SELECT {lane_head_landed_sql()} FROM items i"
    assert conn.execute(query).fetchone()[0] == 0
    conn.execute("INSERT INTO item_landings VALUES(1,'correction')")
    assert conn.execute(query).fetchone()[0] == 1


def test_old_merge_stamps_do_not_tell_a_close_out_story():
    claim = {
        "item_id": 1,
        "status": "implementing",
        "merged_at": "2026-11-04T18:21:19Z",
    }
    assert not landed_but_open(claim)
    notice = continuation_notice("TEST-1", claim, 1)
    assert "after landing" not in notice
    assert "Nothing about your item" not in notice
    notice = continuation_notice("TEST-1", {**claim, "lane_head_landed": True}, 1)
    assert "recorded lane head matches a candidate" in notice
