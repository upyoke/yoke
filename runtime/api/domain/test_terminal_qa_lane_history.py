"""Terminal transitions accept an earlier passing lane commit."""

from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement, insert_qa_run
from runtime.api.domain.test_terminal_qa_settlement import (
    _seed_merging_sha, _terminal_result, _tree_result,
)


def test_terminal_transition_accepts_pass_from_an_earlier_lane_commit(test_db, monkeypatch):
    insert_item(test_db, id=10, status="release")
    _seed_merging_sha(test_db, "b" * 40)
    requirement = insert_qa_requirement(test_db, item_id=10)
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass",
        raw_result=_tree_result("a" * 40), completed_at="2026-01-01T00:00:01Z")
    calls = []

    def contains(_conn, item_id):
        def check(head, commit):
            calls.append((item_id, head, commit))
            return head == "b" * 40 and commit == "a" * 40
        return check

    monkeypatch.setattr("yoke_core.domain.qa_lane_history.item_lane_contains", contains)
    assert _terminal_result(test_db) == {"success": True}
    assert calls == [(10, "b" * 40, "a" * 40)]
