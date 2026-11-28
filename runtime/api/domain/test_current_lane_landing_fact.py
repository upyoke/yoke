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
        CREATE TABLE item_worktrees(id INTEGER PRIMARY KEY, item_id INTEGER, commit_sha TEXT, lane_role TEXT DEFAULT 'implementation', state TEXT DEFAULT 'active');
        CREATE TABLE item_landings(item_id INTEGER, candidate_sha TEXT, landed_at TEXT);
        CREATE TABLE item_status_transitions(item_id INTEGER, task_num INTEGER, from_status TEXT, to_status TEXT, created_at TEXT);
        INSERT INTO items VALUES(1);
        INSERT INTO item_worktrees(item_id,commit_sha) VALUES(1,'correction');
        INSERT INTO item_landings VALUES(1,'earlier','2026-11-28T09:00:00Z');
    """)
    query = f"SELECT {lane_head_landed_sql()} FROM items i"
    assert conn.execute(query).fetchone()[0] == 0
    conn.execute(
        "INSERT INTO item_worktrees(item_id,commit_sha,state) VALUES(1,'earlier','released')"
    )
    assert conn.execute(query).fetchone()[0] == 0
    conn.execute("INSERT INTO item_landings VALUES(1,'correction','2026-11-28T09:30:00Z')")
    assert conn.execute(query).fetchone()[0] == 1


def _reopened_lane() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE items(id INTEGER);
        CREATE TABLE item_worktrees(id INTEGER PRIMARY KEY, item_id INTEGER, commit_sha TEXT, lane_role TEXT DEFAULT 'implementation', state TEXT DEFAULT 'active');
        CREATE TABLE item_landings(item_id INTEGER, candidate_sha TEXT, landed_at TEXT);
        CREATE TABLE item_status_transitions(item_id INTEGER, task_num INTEGER, from_status TEXT, to_status TEXT, created_at TEXT);
        INSERT INTO items VALUES(1);
        INSERT INTO item_worktrees(item_id,commit_sha) VALUES(1,'landed');
        INSERT INTO item_landings VALUES(1,'landed','2026-11-28T09:28:18Z');
        INSERT INTO item_status_transitions VALUES(1,NULL,'reviewing-implementation','release','2026-11-28T09:29:00Z');
    """)
    return conn


def test_item_qa_reopen_retires_a_same_sha_receipt_from_close_out():
    conn = _reopened_lane()
    query = f"SELECT {lane_head_landed_sql()} FROM items i"
    assert conn.execute(query).fetchone()[0] == 1
    conn.execute(
        "INSERT INTO item_status_transitions VALUES(1,NULL,'release','implementing','2026-11-28T11:11:27Z')"
    )
    assert conn.execute(query).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM item_landings").fetchone()[0] == 1


def test_a_fresh_receipt_after_the_reopen_still_proves_landing():
    conn = _reopened_lane()
    conn.execute(
        "INSERT INTO item_status_transitions VALUES(1,NULL,'release','implementing','2026-11-28T11:11:27Z')"
    )
    conn.execute("INSERT INTO item_landings VALUES(1,'landed','2026-11-28T12:00:00Z')")
    query = f"SELECT {lane_head_landed_sql()} FROM items i"
    assert conn.execute(query).fetchone()[0] == 1


def test_a_task_reopen_does_not_retire_the_root_receipt():
    conn = _reopened_lane()
    conn.execute(
        "INSERT INTO item_status_transitions VALUES(1,3,'release','implementing','2026-11-28T11:11:27Z')"
    )
    conn.execute(
        "INSERT INTO item_status_transitions VALUES(1,NULL,'reviewing-implementation','implementing','2026-11-28T11:12:00Z')"
    )
    query = f"SELECT {lane_head_landed_sql()} FROM items i"
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
