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
from yoke_core.domain.ephemeral_substrate import (
    frozen_preview_slug,
    preview_url,
)


SHA = "a" * 40
OTHER_SHA = "b" * 40
ORIGIN = "https://run-20260915-001.preview.example.test"


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
    kwargs.setdefault("trigger", "flow")
    """Pin what the project's preview policy resolves to.

    The producer imports the resolver at call time, so patching it on its
    owning module is what the running code actually sees.
    """
    return mock.patch.object(
        preview_identity,
        "resolve_preview_identity_target",
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
        with _resolved(origin=ORIGIN, path="/candidate-revision"), mock.patch.object(
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

    def test_the_probed_origin_is_derived_from_the_run_not_a_branch(self) -> None:
        """A candidate is frozen; a branch-keyed preview would move under it."""
        seen: list = []

        def _resolve(project, preview_key):
            seen.append((project, preview_key))
            return preview_identity.PreviewIdentityTarget(
                origin=ORIGIN, path="/candidate-revision"
            )

        with mock.patch.object(
            preview_identity, "resolve_preview_identity_target", _resolve
        ), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(ORIGIN, served=SHA),
        ):
            producer.run_preview_producer(_context())
        assert seen == [("testproj", "run-20260915-001")]

    def test_a_preview_serving_another_commit_produces_no_receipt(self) -> None:
        """The deploy succeeded; the preview is not this candidate."""
        with _resolved(origin=ORIGIN, path="/candidate-revision"), mock.patch.object(
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
        with _resolved(origin=ORIGIN, path="/candidate-revision"), mock.patch.object(
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
        with _resolved(origin=ORIGIN, path="/candidate-revision"), mock.patch.object(
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

    def test_it_probes_the_dispatched_origin_not_the_run_named_one(self) -> None:
        """This is the defect the separation exists to prevent: the flow
        origin names a slug this deploy path never publishes, so probing it
        would read a host that does not exist — or worse, someone else's."""
        context = self._dispatching_context()
        expected = preview_url(
            frozen_preview_slug(
                workflow_dispatch_request_id(
                    context.project, context.run_id, context.stage_name
                )
            ),
            "preview.example.test",
        )
        with _resolved(
            origin=ORIGIN,
            path="/candidate-revision",
            trigger="github-push",
            preview_domain="preview.example.test",
        ), mock.patch.object(
            probe, "probe_served_revision",
            return_value=probe.ProbeOutcome(
                f"{expected}/candidate-revision", served=SHA
            ),
        ) as probed:
            rc, _diag, observation = producer.run_preview_producer(context)
        assert rc == 0
        assert probed.call_args.args[0] == expected
        assert observation is not None
        assert observation.observed_url == expected
        assert observation.observed_url != ORIGIN

    def test_a_stage_that_cannot_carry_the_candidate_deploys_nothing(self) -> None:
        """A stage passing no frozen revision would let the workflow resolve
        its own, so the refusal lands before the dispatch rather than after
        a preview of the wrong commit is standing."""
        context = self._dispatching_context()
        context.stage["config"]["inputs"] = {}
        with _resolved(
            origin=ORIGIN,
            path="/candidate-revision",
            trigger="github-push",
            preview_domain="preview.example.test",
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
            origin=ORIGIN,
            path="/candidate-revision",
            trigger="github-push",
            preview_domain="preview.example.test",
        ):
            rc, diag, observation = producer.run_preview_producer(context)
        assert (rc, observation) == (1, None)
        assert context.dispatch.calls == []  # type: ignore[attr-defined]
        assert "takes no dispatch inputs" in diag
