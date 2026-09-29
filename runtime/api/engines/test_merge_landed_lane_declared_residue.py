"""A project-declared render is disposable residue; an undeclared one is not.

The pair matters because a product surface that renders a gitignored view into
every checkout leaves it in every lane. Undeclared, it is unknown residue that
refuses the retirement and strands the worktree AND the merged remote branch.
Declared through the project's ``disposable_generated_paths`` policy, the same
lane retires completely.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from runtime.api.engines._merge_landed_lane_test_helpers import (
    BRANCH,
    _land_on_main,
    _local_branches,
    _remote_branches,
    _run_git,
)
from yoke_core.engines import merge_landed_lane_cleanup as cleanup
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane


def test_undeclared_generated_residue_strands_the_whole_lane(landed_lane):
    """Ignored is not disposable: a repository ignore rule says "do not track
    this", not "this may be deleted".

    The machine-wide sweep reads the same classification, so a lane is never
    disposable to one retirement boundary and precious to the other.
    """
    _land_on_main(landed_lane.repo)
    generated = landed_lane.worktree / "webapp" / "generated" / "bundle.js"
    generated.parent.mkdir()
    generated.write_text("built\n", encoding="utf-8")

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo),
        branch=BRANCH,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert len(preserved) == 1
    assert "unknown ignored files present: webapp/generated/" in preserved[0]
    assert landed_lane.worktree.is_dir()
    assert f"refs/heads/{BRANCH}" in _remote_branches(landed_lane.repo)


def test_declared_generated_residue_does_not_strand_the_lane(
    landed_lane, monkeypatch
):
    """The other half of the reading above: a declared render IS disposable.

    A product that renders a gitignored view into every checkout leaves it in
    every lane, and an undeclared one is unknown residue that refuses the
    retirement — worktree and merged remote branch both survive. Declaring it
    through the project's ``disposable_generated_paths`` policy is what makes
    the same lane retire, all four parts of it.
    """
    _land_on_main(landed_lane.repo)
    generated = landed_lane.worktree / "webapp" / "generated" / "bundle.js"
    generated.parent.mkdir()
    generated.write_text("built\n", encoding="utf-8")
    monkeypatch.setattr(
        cleanup,
        "declared_disposable_roots",
        lambda _root: frozenset({PurePosixPath("webapp/generated")}),
    )

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo),
        branch=BRANCH,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not landed_lane.worktree.exists()
    assert BRANCH not in _local_branches(landed_lane.repo)
    assert f"refs/heads/{BRANCH}" not in _remote_branches(landed_lane.repo)
