"""What a release preview actually deploys, through the real dispatch seam.

The producer probes an origin derived from the deployment run, so the thing
that gets deployed has to be named the same way and carry the frozen
candidate. Mocking the dispatch cannot show that: it is a property of what
crosses the seam between the step-runner dispatcher and the ephemeral
deployer, so these drive that seam and read the arguments that arrive.

The branch-preview cases are here for the same reason — the release path
must not have changed what an ordinary development preview does.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_step_runners as step_runners
from yoke_core.domain.browser_qa_preview_identity import (
    PreviewIdentityTarget,
)
from yoke_core.domain.ephemeral_substrate import preview_url, slugify_branch


RUN_ID = "run-20260915-001"
CANDIDATE = "c" * 40
BRANCH_HEAD = "d" * 40
PREVIEW_DOMAIN = "preview.example.test"


def _stage(target: Dict[str, Any] | None) -> Dict[str, Any]:
    stage: Dict[str, Any] = {
        "name": "preview-deploy",
        "step_runner": "ephemeral-deploy",
        "config": {},
    }
    if target is not None:
        stage["target"] = target
    return stage


def _dispatch(stage: Dict[str, Any], *, branch: str = "YOK-3118") -> Dict[str, Any]:
    """Run the real dispatcher, capturing what reaches the deployer."""
    seen: Dict[str, Any] = {}

    def _fake_deploy(project: str, **kwargs: Any) -> int:
        seen.update(kwargs)
        seen["project"] = project
        return 0

    with mock.patch(
        "yoke_core.domain.deploy_ephemeral.exec_ephemeral_deploy", _fake_deploy
    ):
        step_runners._dispatch_step_runner(
            stage,
            run_id=RUN_ID,
            member_items=[],
            github_repo="upyoke/yoke",
            project="testproj",
            project_repo_path="/tmp/checkout",
            branch=branch,
            first_item="",
            timeout_min=10,
            fresh=False,
            gate_branch="main",
            release_lineage=CANDIDATE,
        )
    return seen


class TestReleasePreviewDispatch:
    def test_it_deploys_the_run_identity_and_the_frozen_candidate(self) -> None:
        """Both halves, together: the name that will be probed, and the
        commit the run pinned — not whatever the branch points at."""
        seen = _dispatch(_stage({"kind": "run_preview", "capability": "ephemeral-env"}))
        assert seen["preview_key"] == RUN_ID
        assert seen["revision"] == CANDIDATE

    def test_an_advancing_branch_cannot_move_the_candidate(self) -> None:
        """The branch argument is still passed for context, but the deployed
        revision is the pinned one, so a push during review changes nothing
        about what this preview serves."""
        seen = _dispatch(
            _stage({"kind": "run_preview", "capability": "ephemeral-env"}),
            branch="YOK-3118",
        )
        assert seen["revision"] == CANDIDATE
        assert seen["revision"] != BRANCH_HEAD

    def test_the_deployed_name_is_the_one_the_producer_probes(self) -> None:
        """The seam's key and the producer's origin must agree, or the
        producer probes a URL nothing deployed — which is precisely the
        defect a mocked dispatch could not see."""
        seen = _dispatch(_stage({"kind": "run_preview", "capability": "ephemeral-env"}))
        deployed_origin = preview_url(
            slugify_branch(str(seen["preview_key"])), PREVIEW_DOMAIN
        )
        probed = PreviewIdentityTarget(
            origin=preview_url(slugify_branch(RUN_ID), PREVIEW_DOMAIN),
            path="/candidate-revision",
        )
        assert deployed_origin == probed.origin


class TestBranchPreviewDispatchIsUnchanged:
    @pytest.mark.parametrize(
        "target",
        [None, {"kind": "persistent_environment", "environment": "stage"}],
    )
    def test_an_ordinary_preview_still_deploys_its_branch_head(
        self, target: Dict[str, Any] | None
    ) -> None:
        """A development preview names itself by branch and takes that
        branch's current head; nothing about the release path may change it."""
        seen = _dispatch(_stage(target))
        assert seen["branch"] == "YOK-3118"
        assert seen["preview_key"] == ""
        assert seen["revision"] == ""
