"""A close-out finished during landing owns the terminal writes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_cli as cli
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain.standalone_item_merge_landed import LandedLane

MERGE_SHA = "2" * 40
LANE = LandedLane(
    branch="ITEM-1", target="main", commit_sha="1" * 40, merge_sha=MERGE_SHA,
)


@pytest.mark.parametrize("recorded_sha", [MERGE_SHA, "3" * 40, None])
def test_concurrent_done_skips_claim_gated_writes(monkeypatch, capsys, recorded_sha):
    item = {
        "public_ref": "ITEM-1", "status": "reviewing-implementation",
        "workflow": {"id": "dash"}, "project": {"slug": "example"},
        "worktrees": [{"state": "active", "branch": LANE.branch}],
    }
    outcome = SimpleNamespace(
        ok=True, already_merged=True, commit_sha=LANE.commit_sha,
        merge_sha=MERGE_SHA, touched_files=("a.py",), warnings=(),
    )
    readiness = SimpleNamespace(
        ready=True, branch=LANE.branch, claim_error="", closed_out=False,
        repo_root=Path("/repo"), target="main", landed=LANE,
        review=SimpleNamespace(enters_review=False),
    )
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(cli, "refresh_recorded_head", lambda item, _read: (item, ""))
    monkeypatch.setattr(cli.readiness_gate, "assess", lambda *_a, **_k: readiness)
    monkeypatch.setattr(cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    monkeypatch.setattr(cli.report, "announce_phase", lambda *_a: None)
    monkeypatch.setattr(cli.converge, "converge", lambda **_k: outcome)
    monkeypatch.setattr(cli.landings, "close_out_lane", lambda **_k: (LANE, ""))
    monkeypatch.setattr(cli, "_session_holds_claim", lambda *_a: "no live work claim on this item")
    monkeypatch.setattr(cli.recovery, "claim_error", lambda *_a: "no live work claim on this item")
    recovery_calls = []

    def recover(**_kwargs):
        recovery_calls.append(True)
        return None, "INVALID_CLAIM: item is already terminal"

    monkeypatch.setattr(cli.recovery, "reacquire_landed_claim", recover)
    monkeypatch.setattr(evidence, "authoritative_status_is", lambda *_a: True)
    monkeypatch.setattr(evidence, "recorded", lambda *_a: None if recorded_sha is None else {
        "merge_sha": recorded_sha, "commit_sha": LANE.commit_sha,
        "touched_files": ["a.py"],
    })

    def forbidden(*_args, **_kwargs):
        pytest.fail("a done item must not attempt another close-out write")

    monkeypatch.setattr(cli.close_out, "record_execution_evidence", forbidden)
    monkeypatch.setattr(cli.release_flow, "continue_prepared_release", forbidden)
    monkeypatch.setattr(cli.merge_domain, "sync_item_to_github", forbidden)
    monkeypatch.setattr(cli, "run_terminal_transition", forbidden)
    retired = []
    monkeypatch.setattr(cli, "record_terminal_lane_close_out", lambda *a, **k: retired.append(k))

    assert cli.run([
        item["public_ref"], "--result", "landed", "--verification", "passed",
    ]) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert recovery_calls == [True]
    assert retired[0]["target_status"] == "done"
    assert envelope["ok"] is True
    assert envelope["status"] == "done"
    assert envelope["evidence_recorded"] is (recorded_sha == MERGE_SHA)
    assert "may not have continued" in envelope["prepared_release"]["message"]
    assert "claim" not in json.dumps(envelope)
    if recorded_sha == MERGE_SHA:
        assert envelope["warnings"] == []
    else:
        assert "does not cover" in envelope["warnings"][0]


def test_unfinished_item_keeps_ordinary_close_out(monkeypatch):
    monkeypatch.setattr(evidence, "authoritative_status_is", lambda *_a: False)
    monkeypatch.setattr(evidence, "recorded", lambda *_a: pytest.fail("not done"))
    assert cli.close_out.already_done_after_landing(
        item={"public_ref": "ITEM-1"}, outcome=None,
        public_ref="ITEM-1", branch="ITEM-1",
    ) is None
