"""Codex path trust retires with a landed worktree lane."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

from yoke_core.engines import merge_landed_lane_cleanup as cleanup
from yoke_core.engines.worktree_removal import WorktreeRemoval
from yoke_core.engines.branch_landed_evidence import (
    ANCESTOR_PROOF,
    BranchLandedEvidence,
)
from yoke_core.engines.merge_worktree_cleanliness import LaneResidueAssessment


def test_landed_lane_removes_only_its_codex_path_trust(monkeypatch, tmp_path: Path):
    lane = tmp_path / "repo/.worktrees/YOK-CLEANUP"
    lane.mkdir(parents=True)
    main = tmp_path / "repo"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    # Codex keys trust by OS-native paths; JSON quoting is valid TOML quoting
    # and escapes Windows backslashes.
    hook_key = json.dumps(f"{lane / '.codex' / 'hooks.json'}:session_start:0:0")
    config.write_text(
        f'''[hooks.state.{hook_key}]
trusted_hash = "lane"

[projects.{json.dumps(str(lane))}]
trust_level = "trusted"

[projects.{json.dumps(str(main))}]
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
            landed=BranchLandedEvidence(True, proof=ANCESTOR_PROOF),
        ),
    )
    monkeypatch.setattr(
        cleanup, "assess_lane_residue", lambda *_a: LaneResidueAssessment(True)
    )
    monkeypatch.setattr(cleanup, "release_lane_row", lambda *_a, **_kw: None)
    monkeypatch.setattr(cleanup, "remove_worktree", lambda *_a: WorktreeRemoval(True))

    preserved = cleanup.prune_landed_lane(
        repo_root=str(main),
        branch="YOK-CLEANUP",
        target="main",
        run_git=lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
        emit=lambda *_a, **_kw: None,
    )

    text = config.read_text(encoding="utf-8")
    assert preserved == ()
    document = tomllib.loads(text)
    assert document.get("hooks", {}).get("state", {}) == {}
    assert set(document["projects"]) == {str(main)}
    assert f"[projects.{json.dumps(str(main))}]" in text
