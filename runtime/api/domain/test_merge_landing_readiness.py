"""Every landing blocker is found in one pass, and review is entered by the merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import merge_landing_readiness as readiness_gate
from yoke_core.domain import qa_item_stage_plan_gate as plan_gate
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane
from yoke_core.domain import standalone_item_merge_verify as verify
from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

ITEM_SCOPED_QA = [{"name": "item-qa", "stage_kind": "qa", "scope": "item"}]


def _item(**overrides) -> dict:
    item = {
        "id": 51,
        "public_ref": "ITEM-51",
        "status": "implementing",
        "workflow": {"id": "dash", "version": 10},
        "project": {"slug": "yoke"},
        "completion_flow": "release-qa",
        "worktrees": [
            {"branch": "ITEM-51", "state": "active", "path": "/nonexistent/lane"}
        ],
        "qa_requirements": [],
        "qa_plan_attachments": [],
    }
    item.update(overrides)
    return item


@pytest.fixture
def merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Stub every control-plane and git read the gates make."""
    state = {"item": _item(), "transitions": [], "landed": 0}
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (state["item"], ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli, "_resolve_checkout", lambda *_a: (tmp_path, "main"))
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(landed, "landed_lane", lambda **_k: None)
    monkeypatch.setattr(stale_lane, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: ("abc", ""))
    monkeypatch.setattr(plan_gate, "flow_stages", lambda _flow: (ITEM_SCOPED_QA, ""))
    monkeypatch.setattr(plan_gate, "attachment_transition", lambda _item: "release")
    monkeypatch.setattr(
        merge_cli,
        "enter_review_stage",
        lambda ref, review, *, reason: state["transitions"].append(
            (review.source_stage, review.review_stage, reason)
        )
        or "",
    )

    def _verify(*_a, enter_review, **_k):
        refusal = enter_review()
        if refusal:
            return None, refusal
        state["landed"] += 1
        return None, "stop after landing was reached"

    monkeypatch.setattr(verify, "verify_and_land", _verify)
    return state


def _run(*extra: str) -> int:
    return merge_cli.run(["ITEM-51", "--session-id", "s-1", *extra])


def test_one_refusal_names_every_blocker_and_the_stage_is_not_one(merge, capsys):
    exit_code = _run()

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "2 landing blockers" in err
    assert "[close-out evidence]" in err
    assert "[post-deploy QA]" in err
    assert "yoke qa post-deploy record-no-obligation --item ITEM-51" in err
    assert "[review stage]" not in err
    assert merge["transitions"] == []
    assert merge["landed"] == 0


def test_the_qa_answer_is_the_only_blocker_once_evidence_is_passed(merge, capsys):
    exit_code = _run("--result", "done", "--verification", "green CI")

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "1 landing blocker." in err
    assert "[post-deploy QA]" in err
    assert merge["transitions"] == []


def test_check_prints_the_same_report_and_changes_nothing(merge, capsys):
    exit_code = _run("--check", "--json")

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert [b["gate"] for b in report["blockers"]] == [
        "close-out evidence",
        "post-deploy QA",
    ]
    assert any("'reviewing-implementation'" in note for note in report["merge_will"])
    assert merge["transitions"] == []
    assert merge["landed"] == 0


def test_a_ready_item_enters_review_with_the_verification_then_lands(merge):
    merge["item"] = _item(
        qa_requirements=[{"qa_phase": "post_deploy", "qa_kind": "check"}]
    )

    _run("--result", "done", "--verification", "green CI")

    assert merge["transitions"] == [
        ("implementing", "reviewing-implementation", "green CI")
    ]
    assert merge["landed"] == 1


def test_check_on_a_ready_item_exits_zero(merge, capsys):
    merge["item"] = _item(status="reviewing-implementation", completion_flow="")

    assert _run("--check", "--result", "r", "--verification", "v") == 0
    assert "ITEM-51: ready to land." in capsys.readouterr().out
    assert merge["landed"] == 0


def test_uncommitted_lane_files_are_a_blocker(merge, monkeypatch, tmp_path, capsys):
    lane = tmp_path / "lane"
    lane.mkdir()
    merge["item"] = _item(
        completion_flow="",
        worktrees=[{"branch": "ITEM-51", "state": "active", "path": str(lane)}],
    )
    monkeypatch.setattr(
        readiness_gate, "classify_dirty_files", lambda **_k: ([], ["notes.txt"])
    )

    assert _run("--check", "--result", "r", "--verification", "v") == 1
    out = capsys.readouterr().out
    assert "[clean tree]" in out
    assert "notes.txt" in out
