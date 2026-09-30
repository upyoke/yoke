"""Queue retunes are admitted against the candidate's declaration."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, ctx, dispatch_for
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain.merge_queue_live_drift import LiveDriftReport


@pytest.mark.parametrize("has_lane", [True, False])
def test_landing_compares_candidate_declaration_before_arming(
    monkeypatch,
    tmp_path,
    has_lane,
):
    main = tmp_path / "main"
    candidate = tmp_path / "candidate"
    expected = candidate if has_lane else main
    merge_ctx = ctx(repo_root=str(main))
    observed = []

    def compare(project, *, checkout, branch, item_id):
        observed.append(Path(checkout))
        if Path(checkout) != expected:
            return LiveDriftReport(drift=("old required checks",))
        return LiveDriftReport()

    monkeypatch.setattr(route_mod, "drift_check_before_landing", compare)
    monkeypatch.setattr(
        selection_mod,
        "_find_worktree",
        lambda branch, repo_root: str(candidate) if has_lane else repo_root,
    )
    monkeypatch.setattr(
        selection_mod,
        "project_declares_merge_queue",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(
        selection_mod,
        "candidate_review_refusal",
        lambda **kwargs: "",
    )
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda *_args, **_kwargs: (None, "queue lookup after comparison"),
    )
    branch = merge_ctx.args.branch
    outcome = selection_mod.route_standalone_landing(
        item_id=1,
        branch=branch,
        target="main",
        repo_root=str(main),
        project=merge_ctx.project,
        commit_sha=LANE_SHA,
        dispatch=dispatch_for({branch: {}}),
    )

    assert observed == [expected]
    assert outcome.error == "queue lookup after comparison"
