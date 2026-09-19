"""A stage dispatches the commit its run recorded, and refuses without one.

Declared input bindings are resolved once when the run starts, so the
dispatch's whole job here is to substitute the recorded value. That is what
makes a retry, a --fresh retrigger and the delivery record agree on one
consumer commit: none of them can consult the branch again.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow


CONSUMER_B = "b" * 40
STAGE_CONFIG = {
    "workflow": "platform-release-bridge.yml",
    "dispatch_correlation_input": "yoke_dispatch_id",
    "ref": "main",
    "reconcile_by_head_sha": False,
    "wait_for_ci": False,
    "input_bindings": {"consumer_sha": {"project": "platform", "branch": "main"}},
    "inputs": {"product_sha": "{head_sha}", "consumer_sha": "{consumer_sha}"},
}


def _dispatch(*, config=None, bound_inputs=None, fresh=False, gh_calls):
    def _fake_gh(*args, **kwargs):
        gh_calls.append(args)
        if args and args[0] == "trigger":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="new-run-id\n",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

    with mock.patch.object(
        # Satisfies _resolve_release_lineage_sha's checkout verification,
        # unrelated to the recorded binding under test.
        deploy_pipeline_github_workflow, "_run_cmd",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="a" * 40 + "\n",
        ),
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_poll_github_actions",
        return_value=(0, "completed: success"),
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_emit_run_event",
    ):
        return deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
            STAGE_CONFIG if config is None else config,
            name="hosted-release",
            run_id="run-test",
            member_items=[],
            github_repo="upyoke/platform",
            project="yoke",
            project_repo_path="",
            timeout_min=30,
            fresh=fresh,
            gate_branch="main",
            release_lineage="a" * 40,
            bound_inputs=bound_inputs,
            sd="/tmp/sd",
        )


class TestRecordedInputBindingDispatch:
    def test_the_recorded_commit_becomes_the_trigger_input(self):
        gh_calls: list = []

        rc, diag = _dispatch(
            bound_inputs={"consumer_sha": CONSUMER_B}, gh_calls=gh_calls
        )

        assert (rc, diag) == (0, "")
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"consumer_sha={CONSUMER_B}" in trigger

    def test_a_fresh_retrigger_ships_the_same_recorded_commit(self):
        # --fresh mints a new dispatch key; it does not re-open the
        # question of which consumer revision this run carries.
        gh_calls: list = []

        rc, diag = _dispatch(
            bound_inputs={"consumer_sha": CONSUMER_B}, fresh=True, gh_calls=gh_calls
        )

        assert (rc, diag) == (0, "")
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"consumer_sha={CONSUMER_B}" in trigger

    def test_a_declared_binding_with_no_recorded_commit_stops_the_stage(self):
        gh_calls: list = []

        rc, diag = _dispatch(bound_inputs={}, gh_calls=gh_calls)

        assert rc == 1
        assert "consumer_sha" in diag and "recorded no source commit" in diag
        assert not [c for c in gh_calls if c and c[0] == "trigger"]

    def test_a_stage_without_input_bindings_needs_no_recorded_commit(self):
        gh_calls: list = []

        rc, diag = _dispatch(
            config={**STAGE_CONFIG, "input_bindings": {}, "inputs": {
                "product_sha": "{head_sha}",
            }},
            gh_calls=gh_calls,
        )

        assert (rc, diag) == (0, "")
        assert [c for c in gh_calls if c and c[0] == "trigger"]
