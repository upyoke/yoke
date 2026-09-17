"""Re-entering a landing the control-plane observer already recorded.

The queue merges on GitHub whether or not a process is watching, and the
observer records that merge on the item. Re-entering then finds a pull
request the queue has forgotten and a train that has already run, so every
read the full path makes would answer "not admitted" about a merge that
happened. The recorded landing is what lets re-entry skip straight to the
bookkeeping it still owes — only when the current candidate actually
landed. An earlier queue receipt must not satisfy a later candidate.
"""

from pathlib import Path

from runtime.api.merge_queue_landing_test_helpers import (
    UNARMED,
    dispatch_for,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.merge_queue_close_out import QueueCloseOut


LANDED = {"pr_number": "42", "landed_at": "2026-09-03T10:00:00Z"}
LATER = "9" * 40


def _cover(monkeypatch, verdict: str) -> None:
    monkeypatch.setattr(
        route_mod, "recorded_landing_covers_candidate", lambda *_a: verdict
    )


def test_a_recorded_landing_closes_out_without_consulting_the_queue(monkeypatch):
    wire_happy_path(monkeypatch)
    _cover(monkeypatch, "landed")

    def forbidden(*_a, **_kw):
        raise AssertionError("a recorded landing never re-enters the queue")

    monkeypatch.setattr(route_mod, "read_queue_members", forbidden)
    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden)
    monkeypatch.setattr(landing_pr_mod, "find_landable_pull_request", forbidden)
    landed: list[str] = []
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **kw: (
            landed.append(kw["pr_num"])
            or QueueCloseOut(
                merge_sha="n" * 40,
                touched_files=("a.py",),
            )
        ),
    )

    outcome = land(dispatch=dispatch_for({"YOK-200": {}}, merge_queue=LANDED))

    assert outcome.ok
    assert outcome.exit_code == 0
    assert outcome.already_merged
    assert outcome.pr_num == "42"
    assert landed == ["42"]


def test_a_recorded_pull_request_that_has_not_landed_takes_the_full_path(monkeypatch):
    """Arming a pull request records it, which is not evidence it merged."""
    wire_happy_path(monkeypatch)

    outcome = land(
        dispatch=dispatch_for({"YOK-200": {}}, merge_queue={"pr_number": "42"}),
    )

    assert outcome.ok
    assert outcome.pr_num == "42"


def test_a_later_uncontained_candidate_does_not_close_out_from_the_recorded_pr(
    monkeypatch,
):
    """Old PR plus new commits must not look like a green recorded close-out."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    _cover(monkeypatch, "unlanded")
    consulted: list[str] = []
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda _ctx, base_branch="main": (consulted.append(base_branch) or [], None),
    )
    closed: list[str] = []
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **kw: closed.append(kw["pr_num"])
        or QueueCloseOut(merge_sha="n" * 40, touched_files=("a.py",)),
    )

    outcome = land(
        commit_sha=LATER,
        dispatch=dispatch_for({"YOK-200": {}}, merge_queue=LANDED),
    )

    assert consulted
    assert not outcome.already_merged
    assert outcome.exit_code == 0
    assert closed == ["42"]


def test_unverifiable_containment_refuses_instead_of_closing_out(monkeypatch):
    wire_happy_path(monkeypatch)
    _cover(monkeypatch, "unverifiable")
    closed: list[str] = []
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **kw: closed.append(kw["pr_num"])
        or QueueCloseOut(merge_sha="n" * 40, touched_files=("a.py",)),
    )

    outcome = land(dispatch=dispatch_for({"YOK-200": {}}, merge_queue=LANDED))

    assert not outcome.ok
    assert outcome.exit_code != 0
    assert not outcome.already_merged
    assert closed == []
    assert "could not be verified" in outcome.error


def test_a_rebased_copy_with_no_unlanded_commits_is_the_same_landing(monkeypatch):
    monkeypatch.setattr(outcome_mod.git, "containing_ref", lambda *_a: "")
    monkeypatch.setattr(outcome_mod.git, "current_base_ref", lambda *_a: "main")
    monkeypatch.setattr(outcome_mod.git, "unlanded_commits", lambda *_a: ())
    assert (
        outcome_mod.recorded_landing_covers_candidate("/repo", LATER, "main")
        == "landed"
    )


def test_later_commits_on_the_same_lane_are_unlanded(monkeypatch):
    monkeypatch.setattr(outcome_mod.git, "containing_ref", lambda *_a: "")
    monkeypatch.setattr(outcome_mod.git, "current_base_ref", lambda *_a: "main")
    monkeypatch.setattr(outcome_mod.git, "unlanded_commits", lambda *_a: (LATER,))
    assert (
        outcome_mod.recorded_landing_covers_candidate("/repo", LATER, "main")
        == "unlanded"
    )


def test_an_unreadable_comparison_is_unverifiable(monkeypatch):
    monkeypatch.setattr(outcome_mod.git, "containing_ref", lambda *_a: "")
    monkeypatch.setattr(outcome_mod.git, "current_base_ref", lambda *_a: "main")
    monkeypatch.setattr(outcome_mod.git, "unlanded_commits", lambda *_a: None)
    assert (
        outcome_mod.recorded_landing_covers_candidate("/repo", LATER, "main")
        == "unverifiable"
    )


def test_uncontained_candidate_from_release_does_not_advance_status(
    monkeypatch, capsys
):
    """False-success recovery: queue record plus later commits, status held."""
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "release",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "merge_queue": LANDED,
        "worktrees": [{"branch": "ITEM-1", "state": "active", "path": "/repo/lane"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli, "review_readiness_refusal", lambda *_a, **_k: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    monkeypatch.setattr(
        merge_cli.landed, "stale_unlanded_work", lambda **_k: "stale at release"
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_k: None)
    _cover(monkeypatch, "unlanded")
    advanced: list[str] = []
    monkeypatch.setattr(
        merge_cli.close_out,
        "transition_to_done",
        lambda **kw: advanced.append(str(kw.get("source_status") or ""))
        or ("done", ""),
    )
    monkeypatch.setattr(
        verify,
        "verify_and_land",
        lambda *_a, **_k: (None, "take the candidate path"),
    )

    assert merge_cli.run(["ITEM-1", "--result", "x", "--verification", "y", "--json"]) == 1
    assert advanced == []
    assert item["status"] == "release"
    assert "take the candidate path" in capsys.readouterr().out
