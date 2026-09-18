"""The run-completing stage is not recorded completed over unresolved QA.

A deployment run's stage bar drawn green to its end says the run
delivered. A run once drew every bar — the flow's final ``complete``
stage included — while two blocking run-level obligations had no pass,
so the card reported delivery the status would not confirm.

The gate under test evaluates those obligations *before* the final stage
starts. The stage never runs, so it is never drawn complete, and the card
shows work outstanding exactly while it is. Earlier stages are untouched:
their completion says nothing about the run as a whole.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deploy_pipeline_stage_checks as stage_checks
from yoke_core.domain import deployment_run_completion_preconditions as precond

RUN = "run-20260101-004"
STAGE_FAILED_EXIT = 3
AWAITING_QA_EXIT = 5


class TestRunCompletingStageHold:
    """What the gate does at each stage of a two-stage flow."""

    STAGES = [{"name": "deploy"}, {"name": "complete"}]

    @pytest.fixture
    def unresolved(self, monkeypatch):
        """Stub the control plane's unresolved-obligation read."""
        from yoke_core.domain import deploy_pipeline_control_plane as cp

        def _install(details):
            monkeypatch.setattr(cp, "unresolved_qa", lambda run_id: list(details))

        return _install

    def test_the_final_stage_is_held_while_an_obligation_is_open(
        self, unresolved, capsys
    ):
        unresolved(["requirement #4101 (plan_case): no passing run"])

        exit_code = stage_checks.check_completion_stage_qa(
            self.STAGES[-1],
            self.STAGES,
            RUN,
            usage_exit=STAGE_FAILED_EXIT,
            awaiting_qa_exit=AWAITING_QA_EXIT,
        )

        assert exit_code == AWAITING_QA_EXIT
        report = capsys.readouterr().err
        assert precond.HELD_STAGE_PREFIX in report
        assert "#4101" in report
        assert "'complete'" in report

    def test_an_earlier_stage_is_never_held_by_run_level_qa(self, unresolved):
        """Only the run-completing stage claims the run delivered."""
        unresolved(["check 'smoke-test' is pending"])

        assert (
            stage_checks.check_completion_stage_qa(
                self.STAGES[0],
                self.STAGES,
                RUN,
                usage_exit=STAGE_FAILED_EXIT,
                awaiting_qa_exit=AWAITING_QA_EXIT,
            )
            is None
        )

    def test_resolving_the_obligation_lets_the_final_stage_run(self, unresolved):
        unresolved([])

        assert (
            stage_checks.check_completion_stage_qa(
                self.STAGES[-1],
                self.STAGES,
                RUN,
                usage_exit=STAGE_FAILED_EXIT,
                awaiting_qa_exit=AWAITING_QA_EXIT,
            )
            is None
        )

    def test_an_unreadable_control_plane_is_not_read_as_no_obligations(
        self, monkeypatch, capsys
    ):
        from yoke_core.domain import deploy_pipeline_control_plane as cp

        def _raise(run_id):
            raise cp.DeploymentControlPlaneError("no route to control plane")

        monkeypatch.setattr(cp, "unresolved_qa", _raise)

        exit_code = stage_checks.check_completion_stage_qa(
            self.STAGES[-1],
            self.STAGES,
            RUN,
            usage_exit=STAGE_FAILED_EXIT,
            awaiting_qa_exit=AWAITING_QA_EXIT,
        )

        assert exit_code == STAGE_FAILED_EXIT
        assert "no route to control plane" in capsys.readouterr().err

    def test_the_last_declared_stage_is_the_boundary_whatever_its_name(self):
        stages = [{"name": "deploy"}, {"name": "hosted-release"}]

        assert stage_checks.stage_completes_run(stages[-1], stages)
        assert not stage_checks.stage_completes_run(stages[0], stages)

    def test_the_held_report_does_not_claim_the_stages_completed(self):
        lines = precond.held_stage_report_lines(
            "run-1", "complete", ["check 'x' is pending"]
        )

        assert "stages complete" not in "\n".join(lines)
        assert "succeeded" not in "\n".join(lines)
        assert "stays pending" in lines[0]
        assert "re-drive run-1" in lines[-1]
