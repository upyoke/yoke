"""Deploy pipeline dispatcher coverage.

Covers diagnostic propagation from the github-actions-workflow executor onto
``DeploymentRunStageFailed`` and reconcile-from-truth resume behavior when a
prior workflow run for the same head_sha already concluded success.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow


_STAGE_CONFIG = {
    "workflow": "deploy.yml",
    "timeout_min": 30,
    "dispatch_correlation_input": "yoke_dispatch_id",
}


class TestExecutorDiagnosticPropagation:
    """gh poll output must reach the failure event.

    The github-actions-workflow executor preserves the poll diagnostic; the
    pipeline includes it on ``DeploymentRunStageFailed`` so operators can
    root-cause without manual log archaeology.
    """

    def _dispatch_with_poll(self, poll_result):
        """Run _dispatch_github_actions_workflow with a stubbed poll."""
        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="abc1234\n"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
            return_value=("", False, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="999\n"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=poll_result,
        ):
            return deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                _STAGE_CONFIG,
                name="prod-deploy",
                run_id="run-test",
                member_items=["42"],
                github_repo="owner/repo",
                project="externalwebapp",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                release_lineage="a" * 40,
                sd="/tmp/sd",
            )

    def test_executor_returns_diagnostic_tuple_on_poll_failure(self):
        # When poll fails, the executor surfaces the gh CLI diagnostic
        # alongside the exit code so the caller can route it onward.
        rc, diag = self._dispatch_with_poll(
            (1, "completed: failure\nstep `deploy` exited 137"),
        )
        assert rc == 1
        assert "completed: failure" in diag
        assert "exited 137" in diag

    def test_executor_returns_empty_diagnostic_on_poll_success(self):
        # Successful polls do not carry a diagnostic — payload stays clean.
        rc, diag = self._dispatch_with_poll((0, "completed: success"))
        assert rc == 0
        assert diag == ""


class TestReconcileFromTruth:
    """Post-give-up resume reconciles from GitHub workflow truth.

    When _find_existing_workflow_run discovers the prior run for the same
    head_sha already concluded success, the dispatcher emits the retroactive
    DeploymentRunStageCompleted event and short-circuits without re-firing
    workflow_dispatch.
    """

    def test_prior_success_skips_workflow_dispatch(self):
        # A prior run that concluded success must NOT cause a second
        # workflow_dispatch — the dispatcher returns the already-emitted
        # sentinel and run_pipeline does not re-fire the trigger.
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        captured_events = []

        def _capture_event(name, outcome, ctx, **kwargs):
            captured_events.append((name, dict(ctx)))

        prior_run_id = "26099035592"
        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="abc1234\n"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
            return_value=(prior_run_id, True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "should not be called"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event", side_effect=_capture_event,
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                _STAGE_CONFIG,
                name="prod-deploy",
                run_id="run-test",
                member_items=["42"],
                github_repo="owner/repo",
                project="externalwebapp",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                release_lineage="a" * 40,
                sd="/tmp/sd",
            )

        # No workflow_dispatch (gh trigger) fired.
        trigger_calls = [c for c in gh_calls if c and c[0] == "trigger"]
        assert trigger_calls == [], (
            f"workflow_dispatch fired during reconcile-from-truth: {trigger_calls}"
        )

        # The dispatcher self-emitted the retroactive completion event with
        # the prior workflow run reference so the resume is observable.
        completion_events = [
            (n, c) for n, c in captured_events if n == "DeploymentRunStageCompleted"
        ]
        assert len(completion_events) == 1
        _, ctx = completion_events[0]
        assert ctx.get("reconciled") is True
        assert ctx.get("workflow_run") == prior_run_id
        assert ctx.get("reason") == "prior-run-success"

        # -3 sentinel tells run_pipeline the event was already emitted; diag empty.
        assert rc == -3
        assert diag == ""

    def test_fresh_flag_bypasses_reconcile_path(self):
        # --fresh skips the existing-run search entirely, so reconcile cannot
        # fire even when a prior successful run exists.  The dispatcher must
        # trigger workflow_dispatch normally.
        gh_calls = []
        gh_projects = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            gh_projects.append(kwargs.get("project"))
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="new-run-id\n",
            )

        find_existing_called = []

        def _record_find_existing(*args, **kwargs):
            find_existing_called.append(args)
            return ("ignored", True, "")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="abc1234\n"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
            side_effect=_record_find_existing,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ) as poll_actions, mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event",
        ), mock.patch.object(
            deploy_pipeline_github_workflow.uuid,
            "uuid4",
            return_value=mock.Mock(hex="explicit-retrigger"),
        ):
            rc, _diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                _STAGE_CONFIG,
                name="prod-deploy",
                run_id="run-test",
                member_items=["42"],
                github_repo="owner/repo",
                project="externalwebapp",
                project_repo_path="",
                timeout_min=30,
                fresh=True,
                gate_branch="main",
                release_lineage="a" * 40,
                sd="/tmp/sd",
            )

        # _find_existing_workflow_run NOT called because --fresh short-circuits.
        assert find_existing_called == []
        # Workflow trigger DID fire.
        trigger_calls = [c for c in gh_calls if c and c[0] == "trigger"]
        assert len(trigger_calls) == 1
        trigger = trigger_calls[0]
        assert trigger[trigger.index("--request-id") + 1] == (
            "deploy:externalwebapp:run-test:prod-deploy:fresh:explicit-retrigger"
        )
        assert trigger[-2:] == ("--correlation-input", "yoke_dispatch_id")
        assert gh_projects == ["externalwebapp"]
        assert poll_actions.call_args.kwargs["project"] == "externalwebapp"
        # Polled the fresh run and returned its rc (0 from the mock).
        assert rc == 0
