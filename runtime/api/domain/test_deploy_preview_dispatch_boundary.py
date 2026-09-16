"""A run preview's dispatch must carry the candidate, and land where probed."""

from __future__ import annotations

import pytest

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    fresh_retrigger_scope,
)
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
    release_preview_origin,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_FLOW,
    TRIGGER_GITHUB_PUSH,
    is_release_preview_slug,
    preview_url,
)

PROJECT = "webapp"
RUN_ID = "run-20260915-001"
STAGE = "release-preview"
DOMAIN = "preview.example.com"


def _stage(target=None, **config):
    base = {
        "workflow": "webapp-ephemeral.yml",
        "dispatch_correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
        "inputs": {"commit_sha": "{head_sha}", "preview_slug": "{preview_slug}"},
    }
    base.update(config)
    return {
        "name": STAGE,
        "step_runner": "github-actions-workflow",
        "target": target or {"kind": "run_preview", "capability": "ephemeral-env"},
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
    def test_the_origin_is_the_run_the_preview_belongs_to(self):
        """The probe reads the URL the deploy workflow publishes, and the
        workflow publishes the name Yoke sends it verbatim. Deriving that
        name on either side is what once aimed the proof at a host nothing
        deployed."""
        origin, refusal = _resolve(_stage())
        assert refusal == ""
        assert origin == preview_url(RUN_ID, DOMAIN)

    def test_a_second_preview_in_one_run_is_distinguished_by_its_stage(self):
        origin, refusal = _resolve(
            _stage(
                target={
                    "kind": "run_preview",
                    "capability": "ephemeral-env",
                    "preview_discriminator": "web",
                }
            )
        )
        assert refusal == ""
        assert origin == preview_url(f"{RUN_ID}-web", DOMAIN)

    def test_a_fresh_retrigger_redeploys_the_same_preview(self):
        """``--fresh`` scopes the dispatch so it gets a new run, and the
        preview's name does not come from the dispatch, so the retrigger
        redeploys the same frozen candidate at the same URL the receipt
        probes."""
        first = fresh_retrigger_scope()
        second = fresh_retrigger_scope()
        assert first and second and first != second
        assert _resolve(_stage())[0] == preview_url(RUN_ID, DOMAIN)

    @pytest.mark.parametrize("spelling", ["{head_sha}", "$head_sha", "${head_sha}"])
    def test_every_head_sha_spelling_carries_the_candidate(self, spelling):
        origin, refusal = _resolve(
            _stage(inputs={"revision": spelling, "preview_slug": "{preview_slug}"})
        )
        assert refusal == ""
        assert origin

    @pytest.mark.parametrize(
        "spelling", ["{preview_slug}", "$preview_slug", "${preview_slug}"]
    )
    def test_every_preview_slug_spelling_carries_the_name(self, spelling):
        origin, refusal = _resolve(
            _stage(inputs={"commit_sha": "{head_sha}", "slug": spelling})
        )
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
        assert "could not be recovered" in refusal

    def test_a_stage_passing_no_frozen_candidate_is_refused(self):
        """Without it the workflow resolves its own revision, and the receipt
        would prove a preview of something else."""
        origin, refusal = _resolve(
            _stage(inputs={"environment": "preview", "slug": "{preview_slug}"})
        )
        assert origin == ""
        assert "{head_sha}" in refusal

    def test_a_stage_passing_no_preview_name_is_refused(self):
        """Without it the workflow names the preview itself, which is the
        drift that published one host and probed another."""
        origin, refusal = _resolve(_stage(inputs={"commit_sha": "{head_sha}"}))
        assert origin == ""
        assert "{preview_slug}" in refusal

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
        other way gave it a second one that its receipt never probed."""
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
        """Which is the whole separation: a branch resolving to this shape is
        refused, so a branch cannot take a release preview's occupancy."""
        for trigger, stage in (
            (TRIGGER_GITHUB_PUSH, _stage()),
            (TRIGGER_FLOW, {"step_runner": "ephemeral-deploy", "config": {}}),
        ):
            origin, _ = _resolve(stage, trigger=trigger)
            assert is_release_preview_slug(origin.split("//")[1].split(".")[0])

    def test_the_identity_is_the_one_the_deploy_paths_use(self):
        origin, _ = _resolve(_stage())
        identity = release_preview_identity(_stage(), run_id=RUN_ID)
        assert origin == preview_url(identity, DOMAIN)
