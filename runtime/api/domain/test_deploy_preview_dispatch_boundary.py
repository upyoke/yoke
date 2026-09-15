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
    dispatched_preview_origin,
    release_preview_origin,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_FLOW,
    TRIGGER_GITHUB_PUSH,
    frozen_preview_slug,
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


def _resolve(stage):
    return dispatched_preview_origin(
        stage,
        project=PROJECT,
        run_id=RUN_ID,
        stage_name=STAGE,
        preview_domain=DOMAIN,
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
        origin, refusal = dispatched_preview_origin(
            _stage(),
            project=PROJECT,
            run_id=RUN_ID,
            stage_name=STAGE,
            preview_domain="",
        )
        assert origin == ""
        assert "preview_domain" in refusal


class TestTriggerRouting:
    def test_the_flow_trigger_keeps_the_origin_it_already_resolved(self):
        origin, refusal = release_preview_origin(
            {"step_runner": "ephemeral-deploy", "config": {}},
            project=PROJECT,
            run_id=RUN_ID,
            stage_name=STAGE,
            trigger=TRIGGER_FLOW,
            flow_origin="https://run-20260915-001.preview.example.com",
            preview_domain=DOMAIN,
        )
        assert refusal == ""
        assert origin == "https://run-20260915-001.preview.example.com"

    def test_the_workflow_trigger_ignores_the_flow_origin(self):
        """The flow origin names a slug the deploy workflow never publishes,
        so reusing it would probe a host that does not exist."""
        flow_origin = "https://run-20260915-001.preview.example.com"
        origin, refusal = release_preview_origin(
            _stage(),
            project=PROJECT,
            run_id=RUN_ID,
            stage_name=STAGE,
            trigger=TRIGGER_GITHUB_PUSH,
            flow_origin=flow_origin,
            preview_domain=DOMAIN,
        )
        assert refusal == ""
        assert origin != flow_origin
        assert origin.startswith("https://rel-")
