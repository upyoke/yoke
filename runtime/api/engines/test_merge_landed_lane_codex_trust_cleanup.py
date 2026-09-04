"""Codex path trust retires with a landed worktree lane."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.engines import merge_landed_lane_cleanup as cleanup


def test_landed_lane_removes_only_its_codex_path_trust(monkeypatch, tmp_path: Path):
    lane = tmp_path / "repo/.worktrees/YOK-CLEANUP"
    lane.mkdir(parents=True)
    main = tmp_path / "repo"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text(
        f'''[hooks.state."{lane}/.codex/hooks.json:session_start:0:0"]
trusted_hash = "lane"

[projects."{lane}"]
trust_level = "trusted"

[projects."{main}"]
trust_level = "trusted"
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        cleanup,
        "assess_landed_lane",
        lambda **_kw: cleanup.LaneCleanupAssessment(
            True,
            worktree_path=lane,
            base="main",
            has_remote=False,
        ),
    )
    monkeypatch.setattr(
        cleanup,
        "assess_worktree_residue",
        lambda *_a: cleanup.WorktreeResidueAssessment(True),
    )
    monkeypatch.setattr(cleanup, "release_lane_row", lambda *_a, **_kw: None)

    preserved = cleanup.prune_landed_lane(
        repo_root=str(main),
        branch="YOK-CLEANUP",
        target="main",
        run_git=lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
        emit=lambda *_a, **_kw: None,
    )

    text = config.read_text(encoding="utf-8")
    assert preserved == ()
    assert str(lane) not in text
    assert f'[projects."{main}"]' in text
