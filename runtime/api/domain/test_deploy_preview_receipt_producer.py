"""The run-preview receipt producer: deploy, then require proof.

What a receipt for a preview has to be worth is the whole subject here. A
deploy step exiting zero says a step ran; only the preview answering with
the frozen candidate says the thing QA is about to browse is that
candidate. These cover both, plus every way the question can go
unanswered.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain import browser_qa_preview_identity as preview_identity
from yoke_core.domain import deploy_preview_receipt_producer as producer
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    workflow_dispatch_request_id,
)
from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
    ProducerContext,
    RECEIPT_PRODUCERS,
    SUPPORTED_TARGET_KINDS,
)
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
)
from yoke_core.domain.ephemeral_substrate import (
    frozen_preview_slug,
    is_frozen_preview_slug,
    preview_url,
    slugify_branch,
)


SHA = "a" * 40
OTHER_SHA = "b" * 40
RUN_ID = "run-20260915-001"
STAGE = "preview"
PROJECT = "testproj"
DOMAIN = "preview.example.test"
#: Where this run's preview lands — derived the way the producer derives it,
#: from the release identity rather than from any readable name, so a test
#: that passes here is asserting the same rule the code applies.
ORIGIN = preview_url(
    frozen_preview_slug(release_preview_identity(PROJECT, RUN_ID, STAGE)), DOMAIN
)


def _context(dispatch_result=(0, "preview deployed"), **overrides) -> ProducerContext:
    calls: list = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return dispatch_result

    context = ProducerContext(
        dispatch=_dispatch,
        stage={
            "name": "preview",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        },
        target={"kind": "run_preview", "source_stage": "preview"},
        run_id="run-20260915-001",
        stage_name="preview",
        project="testproj",
        correlation_id="corr-1",
        dispatch_environment="stage",
        release_lineage=SHA,
        **overrides,
    )
    context.dispatch.calls = calls  # type: ignore[attr-defined]
    return context


def _resolved(**kwargs):
    """Pin what the project's preview policy resolves to.

    Policy only: no origin. The producer derives this run's preview origin
    from the release identity, so a resolver that named one would be naming
    a different preview.
    """
    kwargs.setdefault("trigger", "flow")
    kwargs.setdefault("preview_domain", "preview.example.test")
    kwargs.pop("origin", None)
    return mock.patch.object(
        preview_identity,
        "resolve_preview_policy",
        return_value=preview_identity.PreviewIdentityTarget(**kwargs),
    )


class TestRunPreviewProducer:
    def test_it_is_registered_as_a_supported_target_kind(self) -> None:
        """The registry's key set is the supported list, so this is the whole
        registration — there is no second constant to also update."""
        assert "run_preview" in RECEIPT_PRODUCERS
        assert "run_preview" in SUPPORTED_TARGET_KINDS

    def test_a_proving_preview_yields_the_observation_qa_needs(self) -> None:
        """The receipt carries url, name and served revision, which is
        exactly what the consuming QA stage resolves its target from."""
        with _resolved(path="/candidate-revision"), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(
                f"{ORIGIN}/candidate-revision", served=SHA
            ),
        ):
            rc, diag, observation = producer.run_preview_producer(_context())
        assert rc == 0
        assert observation is not None
        assert observation.observed_url == ORIGIN
        assert observation.observed_release_lineage == SHA
        assert observation.target_name == "run-20260915-001"
        assert SHA in diag

    def test_the_probed_origin_is_out_of_any_branch_reach(self) -> None:
        """A candidate is frozen; a branch-keyed preview would move under it.

        The policy read is asked only what the project configures, and is
        given no preview to name — an origin it returned would be about a
        different preview, and the one this receipt is about lands in the
        reserved namespace no branch name can produce.
        """
        asked: list = []

        def _policy(project):
            asked.append(project)
            return preview_identity.PreviewIdentityTarget(
                path="/candidate-revision", trigger="flow", preview_domain=DOMAIN,
            )

        with mock.patch.object(
            preview_identity, "resolve_preview_policy", _policy
        ), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(ORIGIN, served=SHA),
        ) as probed:
            producer.run_preview_producer(_context())
        assert asked == [PROJECT]
        assert is_frozen_preview_slug(probed.call_args.args[0].split("//")[1].split(".")[0])
        assert slugify_branch(RUN_ID) not in probed.call_args.args[0]

    def test_a_preview_serving_another_commit_produces_no_receipt(self) -> None:
        """The deploy succeeded; the preview is not this candidate."""
        with _resolved(path="/candidate-revision"), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(
                ORIGIN, probe.MISMATCH, OTHER_SHA, served=OTHER_SHA
            ),
        ):
            rc, diag, observation = producer.run_preview_producer(_context())
        assert observation is None
        assert rc == 1
        assert "did not prove this candidate" in diag
        assert OTHER_SHA in diag

    @pytest.mark.parametrize(
        "outcome_kind,detail",
        [(probe.UNREACHABLE, "connection refused"), (probe.MALFORMED, "'<html>'")],
    )
    def test_an_unanswerable_preview_produces_no_receipt(
        self, outcome_kind: str, detail: str
    ) -> None:
        """Unverified is not a pass, and it is not a mismatch either."""
        with _resolved(path="/candidate-revision"), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(ORIGIN, outcome_kind, detail),
        ):
            rc, diag, observation = producer.run_preview_producer(_context())
        assert observation is None
        assert rc == 1
        assert outcome_kind in diag

    def test_a_failed_deploy_never_reaches_the_probe(self) -> None:
        """Nothing is asked of a preview that was not stood up."""
        probed: list = []
        with _resolved(path="/candidate-revision"), mock.patch.object(
            probe, "probe_served_revision",
            side_effect=lambda *a, **k: probed.append(a),
        ):
            rc, diag, observation = producer.run_preview_producer(
                _context(dispatch_result=(2, "deploy failed"))
            )
        assert (rc, observation) == (2, None)
        assert probed == []

    def test_an_unconfigured_project_refuses_before_deploying(self) -> None:
        """Standing a preview up that cannot be proved wastes the deploy."""
        context = _context()
        with _resolved(unconfigured=True):
            rc, diag, observation = producer.run_preview_producer(context)
        assert (rc, observation) == (1, None)
        assert context.dispatch.calls == []  # type: ignore[attr-defined]
        assert "configures no identity_path" in diag
        assert "capability-settings merge" in diag

    def test_unreadable_configuration_is_not_reported_as_unconfigured(self) -> None:
        with _resolved(unreadable="permission denied"):
            rc, diag, observation = producer.run_preview_producer(_context())
        assert (rc, observation) == (1, None)
        assert "unverified rather than unconfigured" in diag
        assert "permission denied" in diag

    def test_a_stage_without_a_capability_refuses(self) -> None:
        context = _context()
        context.stage["target"].pop("capability")  # type: ignore[union-attr]
        rc, diag, observation = producer.run_preview_producer(context)
        assert (rc, observation) == (1, None)
        assert "names no preview capability" in diag


class TestAProjectWhoseWorkflowDeploysThePreview:
    """Not every project's previews are deployed by the flow itself.

    Where the project's own GitHub workflow publishes them, the run's frozen
    candidate and the preview's name travel as dispatch inputs, and the
    preview lands at an origin derived from that dispatch rather than from
    the run id. The producer has to probe the one that was actually
    deployed.
    """

    @staticmethod
    def _dispatching_context(**overrides):
        context = _context(**overrides)
        context.stage["step_runner"] = "github-actions-workflow"
        context.stage["config"] = {
            "workflow": "webapp-ephemeral.yml",
            "dispatch_correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
            "inputs": {"commit_sha": "{head_sha}"},
        }
        return context

    def test_it_probes_the_one_origin_both_paths_publish(self) -> None:
        """One run, one preview, one URL: the workflow derives the name by
        hashing the dispatch identity it receives, and the receipt derives
        the same name from the same identity before the deploy answers."""
        context = self._dispatching_context()
        with _resolved(
            path="/candidate-revision",
            trigger="github-push",
        ), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(f"{ORIGIN}/candidate-revision", served=SHA),
        ) as probed:
            rc, _diag, observation = producer.run_preview_producer(context)
        assert rc == 0
        assert probed.call_args.args[0] == ORIGIN
        assert observation is not None
        assert observation.observed_url == ORIGIN
        assert ORIGIN == preview_url(
            frozen_preview_slug(
                workflow_dispatch_request_id(PROJECT, RUN_ID, STAGE)
            ),
            DOMAIN,
        )

    def test_a_stage_that_cannot_carry_the_candidate_deploys_nothing(self) -> None:
        """A stage passing no frozen revision would let the workflow resolve
        its own, so the refusal lands before the dispatch rather than after
        a preview of the wrong commit is standing."""
        context = self._dispatching_context()
        context.stage["config"]["inputs"] = {}
        with _resolved(
            path="/candidate-revision",
            trigger="github-push",
        ):
            rc, diag, observation = producer.run_preview_producer(context)
        assert (rc, observation) == (1, None)
        assert context.dispatch.calls == []  # type: ignore[attr-defined]
        assert "frozen candidate" in diag

    def test_a_step_runner_that_takes_no_inputs_deploys_nothing(self) -> None:
        """The other ephemeral runner deploys a branch from a push: it takes
        neither the run's key nor a pinned revision, so standing it up would
        deploy one thing while the receipt claimed another."""
        context = _context()
        context.stage["step_runner"] = "ephemeral-deploy"
        with _resolved(
            path="/candidate-revision",
            trigger="github-push",
        ):
            rc, diag, observation = producer.run_preview_producer(context)
        assert (rc, observation) == (1, None)
        assert context.dispatch.calls == []  # type: ignore[attr-defined]
        assert "takes no dispatch inputs" in diag
