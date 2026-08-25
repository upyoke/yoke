"""Commit-bound merge preflight refusals recover, then land."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_commit_bound as commit_bound
from yoke_core.domain import standalone_item_merge_recovery as merge_recovery
from runtime.api.domain.test_standalone_item_merge_qa import (
    EARLIER_SHA,
    MERGING_SHA,
    _item,
    _requirement,
)


def _run_merge(tmp_path: Path, monkeypatch, item, *, rerecord, run_case=None):
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(merge_cli, "_resolve_checkout", lambda *a: (tmp_path, "main"))
    monkeypatch.setattr(
        commit_bound, "rerecord_hand_run", rerecord,
    )
    if run_case is not None:
        monkeypatch.setattr(commit_bound, "rerun_command_case", run_case)
    outcome = mock.Mock(
        ok=True, already_merged=False, commit_sha=MERGING_SHA,
        merge_sha="c" * 40, touched_files=("file.py",), pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(verify, "route_standalone_landing", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)
    return merge_cli.run(["YOK-10", "--skip-status"]), merger


def test_missing_sha_is_re_recorded_then_lands(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="pass", sha=""))
    recorded = []

    def rerecord(requirement, commit_sha):
        recorded.append((requirement["id"], commit_sha))
        requirement["recorded_head_sha"] = commit_sha
        requirement["verdict"] = "pass"
        requirement["completed_at"] = "2026-01-01T00:00:00Z"
        requirement["run_id"] = 88

    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 0
    assert recorded == [(77, MERGING_SHA)]
    merger.assert_called_once()
    assert merger.call_args.kwargs["commit_sha"] == MERGING_SHA


def test_stale_sha_is_re_recorded_then_lands(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="pass", sha=EARLIER_SHA))
    recorded = []

    def rerecord(requirement, commit_sha):
        recorded.append(commit_sha)
        requirement["recorded_head_sha"] = commit_sha
        requirement["verdict"] = "pass"
        requirement["completed_at"] = "2026-01-01T00:00:00Z"
        requirement["run_id"] = 88

    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 0
    assert recorded == [MERGING_SHA]
    merger.assert_called_once()


def test_command_case_is_re_run_then_lands(tmp_path: Path, monkeypatch):
    requirement = _requirement(verdict="pass", sha="")
    requirement["method_id"] = "command-ci"
    item = _item(requirement)
    ran = []

    def run_case(requirement_id):
        ran.append(requirement_id)

    def rerecord(_requirement, _commit_sha):
        raise AssertionError("hand re-record is not the command-case path")

    code, merger = _run_merge(
        tmp_path, monkeypatch, item, rerecord=rerecord, run_case=run_case,
    )
    assert code == 0
    assert ran == [77]
    merger.assert_called_once()


def test_failed_verdict_is_not_a_commit_bound_recovery(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="error", sha=MERGING_SHA))
    rerecord = mock.Mock(side_effect=AssertionError("must not recover"))
    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 1
    merger.assert_not_called()
    rerecord.assert_not_called()
