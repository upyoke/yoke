"""A detached worktree is named by its commit, never by an empty branch.

The health check used to keep the worktree and leave ``branch`` unset, so
the prune batch received ``""`` and rejected every lane.
"""

from __future__ import annotations

from yoke_core.engines.doctor_hc_worktrees_health import _worktree_entries
from yoke_core.engines.git_worktree_registry import (
    detached_lane_branch,
    parse_worktree_porcelain,
)


HEAD = "cc3027aefd8153719bee234ba15af03ba28dfddf"


def test_detached_porcelain_names_the_commit():
    porcelain = (
        f"worktree /repo/.worktrees/YOK-4131\nHEAD {HEAD}\ndetached\n\n"
        "worktree /repo/.worktrees/YOK-1\nHEAD abc\nbranch refs/heads/YOK-1\n\n"
    )

    parsed = parse_worktree_porcelain(porcelain)
    entries = _worktree_entries(porcelain)

    assert parsed[0].branch == detached_lane_branch(HEAD)
    assert parsed[0].branch != ""
    assert parsed[1].branch == "YOK-1"
    assert [entry["branch"] for entry in entries] == [
        parsed[0].branch,
        parsed[1].branch,
    ]


def test_a_record_with_no_branch_and_no_head_stays_empty():
    porcelain = "worktree /repo/.worktrees/odd\n\n"

    parsed = parse_worktree_porcelain(porcelain)

    assert parsed[0].branch == ""
    assert parsed[0].path == "/repo/.worktrees/odd"
