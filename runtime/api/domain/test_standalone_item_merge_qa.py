"""Standalone merges refuse before git when terminal QA cannot authorize HEAD."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_recovery as merge_recovery
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
        "worktrees": [
            {
                "branch": "YOK-10",
                "path": "/tmp/YOK-10",
                "commit_sha": MERGING_SHA,
            }
        ],
        "qa_plan_attachments": [{"case_count": 1, "materialized_count": 1}],
        "qa_requirements": requirements,
    }


def _requirement(
    *,
    verdict: str,
    sha: str,
    completed: bool = True,
    requirement_id: int = 77,
    transition_id: str | None = None,
) -> dict:
    return {
        "id": requirement_id,
        "blocking_mode": "blocking",
        "waived_at": None,
        "run_id": 88,
        "verdict": verdict,
        "case_outcome": "failed" if verdict != "pass" else "passed",
        "execution_status": "captured",
        "completed_at": "2026-01-01T00:00:00Z" if completed else None,
        "recorded_head_sha": sha,
        "workflow_transition_id": transition_id,
    }


@pytest.mark.parametrize(
    ("requirement", "message"),
    [
        (None, "no blocking QA requirement was materialized"),
        (_requirement(verdict="error", sha=MERGING_SHA), "concluded 'failed'"),
    ],
)
def test_merge_refuses_before_invoking_git(
    tmp_path: Path,
    monkeypatch,
    capsys,
    requirement,
    message,
):
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (_item(requirement), ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *a: (tmp_path, "main"),
    )
    merger = mock.Mock()
    monkeypatch.setattr(verify, "route_standalone_landing", merger)

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 1
    assert message in capsys.readouterr().err
    merger.assert_not_called()


def test_exact_commit_pass_reaches_the_merge_boundary(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="pass", sha=MERGING_SHA))
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *a: (tmp_path, "main"),
    )
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

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    assert merger.call_args.kwargs["commit_sha"] == MERGING_SHA


def test_skip_status_defers_only_done_phase_qa(tmp_path: Path, monkeypatch):
    item = _item(
        _requirement(
            verdict="error",
            sha=MERGING_SHA,
            transition_id="done",
        )
    )
    item["qa_plan_attachments"] = [
        {
            "transition_id": "done",
            "case_count": 1,
            "materialized_count": 1,
        }
    ]
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *a: (tmp_path, "main"),
    )
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

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    merger.assert_called_once()


def test_closeout_still_blocks_on_done_phase_qa(tmp_path: Path, monkeypatch, capsys):
    item = _item(
        _requirement(
            verdict="error",
            sha=MERGING_SHA,
            transition_id="done",
        )
    )
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *a: (tmp_path, "main"),
    )
    merger = mock.Mock()
    monkeypatch.setattr(verify, "route_standalone_landing", merger)

    assert (
        merge_cli.run(
            [
                "YOK-10",
                "--result",
                "landed",
                "--verification",
                "green",
            ]
        )
        == 1
    )
    assert "concluded 'failed'" in capsys.readouterr().err
    merger.assert_not_called()


@pytest.mark.parametrize("transition_id", [None, "reviewing-implementation", "future"])
def test_skip_status_keeps_non_done_requirements_fail_closed(
    tmp_path: Path,
    transition_id: str | None,
):
    item = _item(
        _requirement(
            verdict="error",
            sha=MERGING_SHA,
            transition_id=transition_id,
        )
    )
    scoped = merge_qa.item_for_merge_phase(item, leaves_status_unchanged=True)

    commit_sha, error = merge_qa.preflight(
        scoped,
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert "concluded 'failed'" in error


def test_skip_status_recovery_ignores_deferred_done_failure(
    tmp_path: Path,
    monkeypatch,
):
    review = _requirement(
        verdict="pass",
        sha=EARLIER_SHA,
        transition_id="reviewing-implementation",
    )
    done = _requirement(
        verdict="error",
        sha=MERGING_SHA,
        requirement_id=78,
        transition_id="done",
    )
    item = _item(None)
    item["qa_requirements"] = [review, done]
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *a: (tmp_path, "main"),
    )

    def rerecord(requirement, commit_sha):
        requirement["recorded_head_sha"] = commit_sha

    monkeypatch.setattr(verify.commit_bound, "rerecord_hand_run", rerecord)
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

    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    merger.assert_called_once()


def test_preflight_accepts_bound_hand_run_and_refuses_prose(tmp_path: Path):
    commit_sha, error = merge_qa.preflight(
        _item(_requirement(verdict="pass", sha=MERGING_SHA)),
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert error == ""
    commit_sha, error = merge_qa.preflight(
        _item(_requirement(verdict="pass", sha="")),
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert "recorded SHA" in error


def test_preflight_reads_raw_proof_from_an_older_item_detail_server(
    tmp_path: Path,
    monkeypatch,
):
    requirement = _requirement(verdict="pass", sha="")
    monkeypatch.setattr(
        merge_qa,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True,
            result={
                "rows": [
                    {
                        "id": 88,
                        "verdict": "pass",
                        "execution_status": "captured",
                        "case_outcome": "passed",
                        "completed_at": "2026-01-01T00:00:00Z",
                        "raw_result": '{"verification_tree":{"head_sha":"'
                        + MERGING_SHA
                        + '"}}',
                    }
                ]
            },
        ),
    )
    commit_sha, error = merge_qa.preflight(
        _item(requirement),
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == MERGING_SHA
    assert error == ""
