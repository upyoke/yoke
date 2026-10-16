"""The registered pre-lane route prepares and reuses authoritative Epic lanes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_worktree_create_multiworktree import (
    seed_multiworktree_epic,
)
from runtime.api.domain.test_worktree_preflight import _patch_steps
from yoke_cli.commands import direct_workflow_worktree as adapter
from yoke_core.domain import worktree_create, worktree_preflight as preflight


@pytest.mark.parametrize("refusal", ["", "owner", "path", "upstream"])
def test_pre_lane_registered_epic_route(
    git_repo, yoke_db, monkeypatch, capsys, refusal
):
    item_id = 99301
    item_ref = f"YOK-{item_id}"
    branches = ["worker-a", "worker-b"]
    entries = seed_multiworktree_epic(yoke_db, item_id, branches, str(git_repo))
    assert all(not Path(path).exists() for _, path in entries)
    _patch_steps(
        monkeypatch,
        branch_and_lane=(item_ref, None),
        claim_outcome=(False, "foreign session owns claim")
        if refusal == "owner"
        else (True, "owned"),
        activate_outcome=(False, "incompatible path claim", [])
        if refusal == "path"
        else (True, "", []),
    )
    monkeypatch.setattr(
        "yoke_core.domain.yok_n_parser.parse_item_argument",
        lambda *_args, **_kwargs: item_ref,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda *_args, **_kwargs: git_repo,
    )
    if refusal == "upstream":
        monkeypatch.setattr(
            preflight,
            "gate_upstream_for_preparation",
            lambda *_args, **_kwargs: SimpleNamespace(
                freshness=None,
                block_kind="upstream-unverified",
                narrative="Unreadable upstream; restore remote access and rerun.",
            ),
        )
    original = worktree_create.create_worktree

    def create(**kwargs):
        kwargs.update(db_path=yoke_db, config_path=str(git_repo / "runtime/config"))
        return original(**kwargs)

    monkeypatch.setattr(worktree_create, "create_worktree", create)

    def run(argv, **_kwargs):
        assert argv[1:3] == ["-m", "yoke_core.domain.worktree_preflight"]
        return SimpleNamespace(returncode=preflight.main(argv[3:]))

    monkeypatch.setattr(adapter, "subprocess", SimpleNamespace(run=run))
    monkeypatch.chdir(git_repo)
    arguments = ["--item", item_ref, "--project", "yoke"]
    result = adapter.worktree_prepare(arguments)
    output = capsys.readouterr().out
    if refusal:
        expected = {
            "owner": "work-claim-conflict",
            "path": "path-claim-blocked",
            "upstream": "upstream-unverified",
        }
        assert result == 1
        assert f'"block_kind": "{expected[refusal]}"' in output
        assert all(not Path(path).exists() for _, path in entries)
        return
    assert result == 0, output
    assert all(Path(path).is_dir() for _, path in entries)
    assert (git_repo / ".worktrees" / item_ref).is_dir()
    assert adapter.worktree_prepare(arguments) == 0
    output = capsys.readouterr().out
    receipt = json.loads(output[output.rfind("\n{") + 1 :])
    assert "worktree:reused" in receipt["actions_taken"]
    assert receipt["worktree_path"] == str(git_repo / ".worktrees" / item_ref)
