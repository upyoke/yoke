"""Merge admission evaluates verification only; post_deploy stays pending."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_qa as merge_qa
from yoke_core.domain import standalone_item_merge_recovery as merge_recovery
from yoke_core.domain import standalone_item_merge_verify as verify


MERGING_SHA = "b" * 40


def _item(*requirements: dict) -> dict:
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": [
            {
                "branch": "YOK-10",
                "path": "/tmp/YOK-10",
                "commit_sha": MERGING_SHA,
            }
        ],
        "qa_plan_attachments": [],
        "qa_requirements": list(requirements),
    }


def _requirement(*, phase: str, verdict: str, transition: str | None) -> dict:
    return {
        "id": 77,
        "blocking_mode": "blocking",
        "waived_at": None,
        "qa_phase": phase,
        "run_id": 88,
        "verdict": verdict,
        "case_outcome": "failed" if verdict != "pass" else "passed",
        "execution_status": "captured",
        "completed_at": "2026-01-01T00:00:00Z",
        "recorded_head_sha": MERGING_SHA,
        "workflow_transition_id": transition,
    }


def test_post_deploy_on_review_is_excluded_from_merge_preflight(tmp_path: Path):
    scoped = merge_qa.item_for_merge_phase(
        _item(
            _requirement(
                phase="post_deploy",
                verdict="error",
                transition="reviewing-implementation",
            )
        ),
        leaves_status_unchanged=False,
    )
    commit_sha, error = merge_qa.preflight(
        scoped,
        public_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert error == ""


def test_pending_post_deploy_does_not_block_a_closing_merge(
    tmp_path: Path, monkeypatch, capsys
):
    item = _item(
        _requirement(
            phase="verification",
            verdict="pass",
            transition="reviewing-implementation",
        ),
        _requirement(
            phase="post_deploy",
            verdict="error",
            transition="release",
        ),
    )
    item["qa_requirements"][1]["id"] = 78
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *a: (tmp_path, "main")
    )
    monkeypatch.setattr(
        merge_cli.close_out, "transition_to_done", lambda **_k: ("release", "")
    )
    monkeypatch.setattr(merge_cli.close_out, "record_execution_evidence", lambda **_k: ("", ""))
    outcome = mock.Mock(
        ok=True,
        already_merged=False,
        commit_sha=MERGING_SHA,
        merge_sha="c" * 40,
        touched_files=("file.py",),
        pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(verify, "route_standalone_landing", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)

    assert (
        merge_cli.run(
            ["YOK-10", "--result", "landed", "--verification", "green"]
        )
        == 0
    )
    merger.assert_called_once()
    assert "concluded 'failed'" not in capsys.readouterr().err
