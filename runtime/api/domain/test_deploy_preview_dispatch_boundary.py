"""A run preview's dispatch must carry the candidate, and land where probed."""

from __future__ import annotations

import pytest

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    fresh_retrigger_scope,
    workflow_dispatch_request_id,
)
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
    release_preview_origin,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_FLOW,
    TRIGGER_GITHUB_PUSH,
    frozen_preview_slug,
    is_frozen_preview_slug,
    preview_url,
)

PROJECT = "webapp"
RUN_ID = "run-20260915-001"
STAGE = "release-preview"
DOMAIN = "preview.example.com"


def _stage(**config):
    base = {
        "workflow": "webapp-ephemeral.yml",
        "dispatch_correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
        "inputs": {"commit_sha": "{head_sha}"},
    }
    base.update(config)
    return {
        "name": STAGE,
        "step_runner": "github-actions-workflow",
        "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        "config": base,
    }


def _resolve(stage, *, trigger=TRIGGER_GITHUB_PUSH, preview_domain=DOMAIN):
    return release_preview_origin(
        stage,
        project=PROJECT,
        run_id=RUN_ID,
        stage_name=STAGE,
        trigger=trigger,
        preview_domain=preview_domain,
    )


class TestWhereTheDispatchedPreviewLands:
    def test_origin_matches_the_identity_the_dispatcher_will_send(self):
        """The probe reads the URL the deploy workflow publishes, which the
        workflow derives from the dispatch identity Yoke sends it. Computing
        that identity any other way here would aim the proof at a host
        nothing deployed."""
        origin, refusal = _resolve(_stage())
        assert refusal == ""
        assert origin == preview_url(
            frozen_preview_slug(
                workflow_dispatch_request_id(PROJECT, RUN_ID, STAGE)
            ),
            DOMAIN,
        )

    def test_a_fresh_retrigger_does_not_move_the_preview(self):
        """``--fresh`` scopes an ordinary dispatch so it gets a new run. A
        release preview is addressed by that identity, so scoping it would
        deploy to one URL while the receipt probed another — and the
        candidate is frozen, so redeploying the same preview is the whole
        intent anyway."""
        pinned = workflow_dispatch_request_id(
            PROJECT,
            RUN_ID,
            STAGE,
            retrigger_scope=fresh_retrigger_scope(release_preview=True),
        )
        assert pinned == workflow_dispatch_request_id(PROJECT, RUN_ID, STAGE)

    def test_an_ordinary_fresh_retrigger_still_gets_a_new_identity(self):
        first = fresh_retrigger_scope(release_preview=False)
        second = fresh_retrigger_scope(release_preview=False)
        assert first and second and first != second

    @pytest.mark.parametrize("spelling", ["{head_sha}", "$head_sha", "${head_sha}"])
    def test_every_head_sha_spelling_carries_the_candidate(self, spelling):
        origin, refusal = _resolve(_stage(inputs={"revision": spelling}))
        assert refusal == ""
        assert origin


class TestRefusalsBeforeAnythingDeploys:
    def test_a_step_runner_that_takes_no_inputs_is_refused(self):
        stage = _stage()
        stage["step_runner"] = "ephemeral-deploy"
        origin, refusal = _resolve(stage)
        assert origin == ""
        assert "takes no dispatch inputs" in refusal

    def test_a_stage_without_the_correlation_input_is_refused(self):
        origin, refusal = _resolve(_stage(dispatch_correlation_input=""))
        assert origin == ""
        assert "no dispatch identity to name this preview" in refusal

    def test_a_stage_passing_no_frozen_candidate_is_refused(self):
        """Without it the workflow resolves its own revision, and the receipt
        would prove a preview of something else."""
        origin, refusal = _resolve(_stage(inputs={"environment": "preview"}))
        assert origin == ""
        assert "{head_sha}" in refusal

    def test_a_stage_with_no_inputs_at_all_is_refused(self):
        origin, refusal = _resolve(_stage(inputs={}))
        assert origin == ""
        assert "frozen candidate" in refusal

    def test_a_project_with_no_preview_domain_is_refused(self):
        origin, refusal = _resolve(_stage(), preview_domain="")
        assert origin == ""
        assert "preview_domain" in refusal


class TestOneNameWhicheverPathDeploysIt:
    def test_both_triggers_resolve_the_same_origin(self):
        """One run's preview has one URL. Deriving the flow path's name some
        other way gave it a second one that its receipt never probed — and
        put it in a namespace a branch could reach."""
        dispatched, _ = _resolve(_stage(), trigger=TRIGGER_GITHUB_PUSH)
        flowed, refusal = _resolve(
            {"step_runner": "ephemeral-deploy", "config": {}}, trigger=TRIGGER_FLOW
        )
        assert refusal == ""
        assert flowed == dispatched

    def test_the_flow_trigger_needs_no_dispatch_inputs(self):
        """It deploys the preview itself, so there is no workflow to hand
        the candidate to — the refusals that guard that hand-off would be
        refusing something that never happens."""
        _origin, refusal = _resolve(
            {"step_runner": "ephemeral-deploy", "config": {}}, trigger=TRIGGER_FLOW
        )
        assert refusal == ""

    def test_the_name_always_lands_in_the_reserved_namespace(self):
        """Which is the whole separation: a branch cannot produce this shape,
        so a branch cannot take a release preview's occupancy."""
        for trigger, stage in (
            (TRIGGER_GITHUB_PUSH, _stage()),
            (TRIGGER_FLOW, {"step_runner": "ephemeral-deploy", "config": {}}),
        ):
            origin, _ = _resolve(stage, trigger=trigger)
            assert is_frozen_preview_slug(origin.split("//")[1].split(".")[0])

    def test_the_identity_is_the_one_the_deploy_paths_use(self):
        origin, _ = _resolve(_stage())
        identity = release_preview_identity(PROJECT, RUN_ID, STAGE)
        assert origin == preview_url(frozen_preview_slug(identity), DOMAIN)
