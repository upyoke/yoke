"""Observed landings have custody identity before worker closeout runs."""

from dataclasses import replace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    MERGED,
    MERGE_COMMIT,
    merged,
    observe,
    observer_connection,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain import item_merge_receipt_document as receipts
from yoke_core.domain import merge_queue_landing_identity as identity
from yoke_core.domain.deployment_run_unheld_candidates import unheld_candidate_ids
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_contracts.timestamps import utc_now


def test_observer_commits_identity_before_notice(monkeypatch):
    conn = observer_connection()
    from yoke_core.domain import merge_queue_landing_observer as observer

    real_notice = observer.push_notice

    def notice(conn, **kwargs):
        assert receipts.landing_shas(conn, 101) == [MERGED.head_sha, MERGE_COMMIT]
        return real_notice(conn, **kwargs)

    monkeypatch.setattr(observer, "push_notice", notice)
    assert observe(conn, read_state=merged)["landed"] == 1
    entry = receipts.find_entry(conn, 101, branch=MERGED.head_branch, target="main")
    assert entry["merge_sha"] == MERGE_COMMIT
    assert observe(conn, read_state=merged)["landed"] == 0
    assert len(receipts.read_entries(conn, 101)) == 1


def test_failed_receipt_rolls_back_both_landing_stamps(monkeypatch):
    conn = observer_connection()

    def fail(*args, **kwargs):
        raise ValueError("receipt storage unavailable")

    monkeypatch.setattr(identity.item_merge_receipt_document, "record_entry", fail)
    result = observe(conn, read_state=merged)
    assert result["landed"] == result["notified"] == 0
    row = conn.execute(
        "SELECT merged_at,merge_queue_landed_at FROM items WHERE id=101"
    ).fetchone()
    assert tuple(row) == (None, None)
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


@pytest.mark.parametrize(
    "field", ["head_sha", "merge_commit_sha", "head_branch", "target_branch"]
)
def test_missing_current_identity_never_becomes_visible_as_merged(field):
    conn = observer_connection()
    state = replace(MERGED, **{field: ""})
    assert observe(conn, read_state=lambda *_: (state, None))["landed"] == 0
    assert (
        conn.execute("SELECT merged_at FROM items WHERE id=101").fetchone()[0] is None
    )


def test_replaced_pr_cannot_stamp_old_observation():
    conn = observer_connection()

    def changed(*_):
        conn.execute("UPDATE items SET merge_queue_pr_number='43' WHERE id=101")
        conn.commit()
        return MERGED, None

    assert observe(conn, read_state=changed)["landed"] == 0
    assert receipts.read_entries(conn, 101) == {}


def test_repeated_branch_retains_history_and_worker_enriches_current_receipt():
    conn = observer_connection()
    receipts.record_entry(
        conn,
        item_id=101,
        branch=MERGED.head_branch,
        target="main",
        commit_sha="1" * 40,
        merge_sha="2" * 40,
        touched_files=["old.py"],
    )
    conn.commit()
    assert observe(conn, read_state=merged)["landed"] == 1
    receipts.record_entry(
        conn,
        item_id=101,
        branch=MERGED.head_branch,
        target="main",
        commit_sha=MERGED.head_sha,
        merge_sha=MERGE_COMMIT,
        touched_files=["current.py"],
        check_runs=[{"name": "ci", "conclusion": "success"}],
    )
    entries = receipts.read_entries(conn, 101)
    assert len(entries) == 2
    current = entries[receipts.entry_key(MERGED.head_branch, "main")]
    assert current["merge_sha"] == MERGE_COMMIT
    assert current["touched_files"] == ["current.py"]
    assert current["check_runs"][0]["conclusion"] == "success"
    assert sorted(receipts.merge_shas(conn, 101)) == sorted(["2" * 40, MERGE_COMMIT])


def test_new_landing_is_excluded_from_older_candidate_before_worker_closeout(
    test_db,
    tmp_path,
    monkeypatch,
):
    """Real containment consumes the receipt immediately after observer commit."""
    item_id = 9871
    flow = "observed-landing-candidate"
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow,
        merge_queue_pr_number="42",
    )
    test_db.commit()
    repo, baseline, landing = release_repository(tmp_path, "ITEM-1")
    serve_repository(monkeypatch, repo)
    stage_environment(test_db)
    cmd_create(
        test_db,
        flow,
        "yoke",
        "Observed landing",
        "",
        '[{"name":"stage","step_runner":"auto","stage_kind":"execution","scope":"run"}]',
        status="disabled",
    )
    insert_run(
        test_db, "older-candidate", lineage=baseline, status="created", flow=flow
    )
    insert_run(
        test_db, "containing-candidate", lineage=landing, status="created", flow=flow
    )
    state = replace(MERGED, head_sha=landing, merge_commit_sha=landing)
    result = observe_pending_landings(
        test_db,
        [1],
        now=utc_now(),
        cadence_seconds=0,
        read_state=lambda *_: (state, None),
    )
    assert result["landed"] == 1
    assert unheld_candidate_ids(test_db, "older-candidate") == ()
    assert item_id in unheld_candidate_ids(test_db, "containing-candidate")
    test_db.execute(
        "DELETE FROM item_sections WHERE item_id=%s AND section_name='Merge Receipts'",
        (item_id,),
    )
    test_db.commit()
    with pytest.raises(
        ValueError, match="no commit identity|no recorded landing|merge receipt"
    ):
        unheld_candidate_ids(test_db, "older-candidate")
