"""CLI envelope coverage for the worktree preflight."""

from __future__ import annotations

import json

from runtime.api.domain.test_worktree_preflight import (
    _build_repo_layout,
    _patch_steps,
)
from yoke_core.domain import worktree_preflight as wp


def test_main_returns_2_on_invalid_item(capsys) -> None:
    result = wp.main(["--item", "not-a-number"])

    assert result == 2
    assert "Invalid --item" in capsys.readouterr().err


def test_main_emits_envelope_json_on_success(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from yoke_core.domain import worktree_create

    repo_layout = _build_repo_layout(tmp_path)
    _patch_steps(
        monkeypatch,
        create_result=worktree_create.CreateWorktreeResult(
            path=repo_layout.worktree,
            branch="YOK-9001",
            created=False,
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd",
        lambda: repo_layout.root,
    )
    monkeypatch.setattr(
        "yoke_core.domain.yok_n_parser.parse_item_argument",
        lambda *_args, **_kwargs: 9001,
    )
    monkeypatch.chdir(repo_layout.root)

    result = wp.main(["--item", "YOK-9001", "--session-id", "sess"])

    assert result == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    assert envelope["item_id"] == 9001
    assert envelope["worktree_path"] == repo_layout.worktree
