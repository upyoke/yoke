"""Standalone merges refuse before git when terminal QA cannot authorize HEAD."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_qa as merge_qa


MERGING_SHA = "b" * 40
EARLIER_SHA = "a" * 40


def _item(requirement: dict | None) -> dict:
    requirements = [] if requirement is None else [requirement]
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": [{
            "branch": "YOK-10",
            "path": "/tmp/YOK-10",
            "commit_sha": MERGING_SHA,
        }],
        "qa_plan_attachments": [{"case_count": 1, "materialized_count": 1}],
        "qa_requirements": requirements,
    }


def _requirement(*, verdict: str, sha: str, completed: bool = True) -> dict:
    return {
        "id": 77,
        "blocking_mode": "blocking",
        "waived_at": None,
        "run_id": 88,
        "verdict": verdict,
        "case_outcome": "failed" if verdict != "pass" else "passed",
        "execution_status": "captured",
        "completed_at": "2026-01-01T00:00:00Z" if completed else None,
        "recorded_head_sha": sha,
    }


@pytest.mark.parametrize(
    ("requirement", "message"),
    [
        (None, "no blocking QA requirement was materialized"),
        (_requirement(verdict="error", sha=MERGING_SHA), "concluded 'failed'"),
        (_requirement(verdict="pass", sha=EARLIER_SHA), "recorded SHA " + EARLIER_SHA),
    ],
)
def test_merge_refuses_before_invoking_git(
    tmp_path: Path, monkeypatch, capsys, requirement, message,
):
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (_item(requirement), ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *a: (tmp_path, "main"),
    )
    merger = mock.Mock()
    monkeypatch.setattr(merge_cli, "merge_standalone_branch", merger)

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 1
    assert message in capsys.readouterr().err
    merger.assert_not_called()


def test_exact_commit_pass_reaches_the_merge_boundary(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="pass", sha=MERGING_SHA))
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *a: (tmp_path, "main"),
    )
    outcome = mock.Mock(
        ok=True, already_merged=False, commit_sha=MERGING_SHA,
        merge_sha="c" * 40, touched_files=("file.py",), pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(merge_cli, "merge_standalone_branch", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    assert merger.call_args.kwargs["commit_sha"] == MERGING_SHA


def test_preflight_reads_raw_proof_from_an_older_item_detail_server(
    tmp_path: Path, monkeypatch,
):
    requirement = _requirement(verdict="pass", sha="")
    monkeypatch.setattr(
        merge_qa, "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True,
            result={"rows": [{
                "id": 88,
                "verdict": "pass",
                "execution_status": "captured",
                "case_outcome": "passed",
                "completed_at": "2026-01-01T00:00:00Z",
                "raw_result": '{"verification_tree":{"head_sha":"'
                + MERGING_SHA + '"}}',
            }]},
        ),
    )
    commit_sha, error = merge_qa.preflight(
        _item(requirement), item_ref="YOK-10", repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert error == ""
