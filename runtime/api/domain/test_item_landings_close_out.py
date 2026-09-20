"""The merge close-out is the one place a landing is recorded.

Both routes to the base branch — the merge queue and the standalone engine —
reach close-out with the merge identity already resolved, and only there. A
second writer anywhere else could disagree with what close-out believes it
landed, which is the drift this record exists to make impossible.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import item_landings_close_out as landings
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_close_out_transition as transition
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.item_landings_schema import (
    ROUTE_FAST_FORWARD,
    ROUTE_MERGE_QUEUE,
    ROUTE_STANDALONE,
)
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
QUEUE_LANDED_AT = "2026-09-19T23:04:11Z"
COMMIT_TIME = "2026-09-19T22:58:02Z"


def _outcome(**overrides) -> StandaloneMergeOutcome:
    fields = {
        "ok": True,
        "exit_code": 0,
        "already_merged": False,
        "commit_sha": LANE_SHA,
        "merge_sha": MERGE_SHA,
        "touched_files": ("feature.py",),
        "pushed": True,
    }
    fields.update(overrides)
    return StandaloneMergeOutcome(**fields)


def _recorded(monkeypatch) -> list:
    sent: list = []

    def dispatch(*, function_id, target, payload=None, **_kw):
        sent.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(landings, "call_dispatcher", dispatch)
    monkeypatch.setattr(landings.git, "commit_time", lambda *_a: COMMIT_TIME)
    return sent


def test_a_standalone_merge_records_its_own_merge_commit(monkeypatch):
    sent = _recorded(monkeypatch)

    lane, note = landings.close_out_lane(
        item_id=41,
        branch="ITEM-41",
        target="main",
        repo_root="/repo",
        landed_lane=None,
        outcome=_outcome(),
    )

    assert note == ""
    assert lane.merge_sha == MERGE_SHA
    function_id, payload = sent[0]
    assert function_id == "item_landings.record"
    assert payload["merge_sha"] == MERGE_SHA
    assert payload["candidate_sha"] == LANE_SHA
    assert payload["route"] == ROUTE_STANDALONE
    assert payload["target_branch"] == "main"
    assert payload["landed_at"] == COMMIT_TIME


def test_a_queue_landing_records_its_pull_request_and_the_moment_it_merged(
    monkeypatch,
):
    """The queue's merge commit predates the landing; GitHub's moment wins."""
    sent = _recorded(monkeypatch)

    landings.close_out_lane(
        item_id=42,
        branch="ITEM-42",
        target="main",
        repo_root="/repo",
        landed_lane=None,
        outcome=_outcome(pr_num="1288"),
        queue_pr_number="1288",
        queue_landed_at=QUEUE_LANDED_AT,
    )

    _, payload = sent[0]
    assert payload["route"] == ROUTE_MERGE_QUEUE
    assert payload["pr_number"] == "1288"
    assert payload["landed_at"] == QUEUE_LANDED_AT


def test_a_landing_with_no_distinct_merge_commit_is_keyed_on_what_landed(
    monkeypatch,
):
    """A fast-forward or squash leaves no merge commit; the row is still keyed."""
    sent = _recorded(monkeypatch)

    landings.close_out_lane(
        item_id=43,
        branch="ITEM-43",
        target="main",
        repo_root="/repo",
        landed_lane=None,
        outcome=_outcome(merge_sha=""),
    )

    _, payload = sent[0]
    assert payload["merge_sha"] == LANE_SHA
    assert payload["candidate_sha"] == LANE_SHA
    assert payload["route"] == ROUTE_FAST_FORWARD


def test_a_landed_lane_records_the_landing_that_carried_it(monkeypatch):
    """Convergence on an already-landed lane is still that lane's landing."""
    sent = _recorded(monkeypatch)

    lane, note = landings.close_out_lane(
        item_id=44,
        branch="ITEM-44",
        target="main",
        repo_root="/repo",
        landed_lane=landed.LandedLane(
            branch="ITEM-44",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py",),
            source="lane branch",
        ),
        outcome=_outcome(already_merged=True),
    )

    assert note == ""
    assert lane.source == "lane branch"
    assert sent[0][1]["merge_sha"] == MERGE_SHA


def test_a_landing_with_no_commit_at_all_names_why_and_does_not_write(
    monkeypatch,
):
    sent = _recorded(monkeypatch)

    _lane, note = landings.close_out_lane(
        item_id=45,
        branch="ITEM-45",
        target="main",
        repo_root="/repo",
        landed_lane=None,
        outcome=_outcome(commit_sha="", merge_sha=""),
    )

    assert sent == []
    assert "no identity to record it under" in note
    assert "Re-run the merge" in note


def test_a_refused_record_warns_and_never_unwinds_the_merge(monkeypatch):
    """The audit trail losing a row must not cost the item its close-out."""
    monkeypatch.setattr(landings.git, "commit_time", lambda *_a: COMMIT_TIME)
    monkeypatch.setattr(
        landings,
        "call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(message="control plane unreachable"),
        ),
    )

    lane, note = landings.close_out_lane(
        item_id=46,
        branch="ITEM-46",
        target="main",
        repo_root="/repo",
        landed_lane=None,
        outcome=_outcome(),
    )

    assert lane.merge_sha == MERGE_SHA
    assert note == "landing not recorded: control plane unreachable"


def test_the_merge_command_records_the_landing_it_closed_out(monkeypatch, capsys):
    """End to end through ``yoke merge item``'s own orchestration."""
    item = {
        "id": 47,
        "public_ref": "ITEM-47",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-47", "path": "/repo/.worktrees/ITEM-47"}],
        "merge_queue": {"pr_number": "1290", "landed_at": QUEUE_LANDED_AT},
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli.stale_lane, "stale_unlanded_work", lambda **_kw: "",
    )
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: (LANE_SHA, ""))
    monkeypatch.setattr(
        verify, "route_standalone_landing", lambda **_k: _outcome(pr_num="1290"),
    )
    monkeypatch.setattr(merge_cli.evidence, "record", lambda **_k: "")
    monkeypatch.setattr(sim, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, ""),
    )
    monkeypatch.setattr(
        merge_cli.close_out, "record_execution_evidence", lambda **_k: ("", ""),
    )
    monkeypatch.setattr(
        transition, "run_terminal_transition", lambda **_k: 0,
    )
    sent = _recorded(monkeypatch)
    monkeypatch.setattr(merge_cli, "run_terminal_transition", lambda **_k: 0)

    exit_code = merge_cli.run(
        ["ITEM-47", "--result", "landed", "--verification", "suite green"],
    )

    assert exit_code == 0
    assert [function_id for function_id, _ in sent] == ["item_landings.record"]
    assert sent[0][1]["pr_number"] == "1290"
    assert sent[0][1]["route"] == ROUTE_MERGE_QUEUE
