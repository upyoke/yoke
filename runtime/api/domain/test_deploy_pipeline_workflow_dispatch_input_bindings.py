"""Declared external input bindings integrated into the github-actions-workflow
stage dispatch: a stage resolves a value (e.g. a hosted consumer's trunk sha)
from another registered project's branch tip, recovering a prior durable
dispatch's already-bound value before ever resolving fresh.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow
from yoke_core.domain import github_workflow_dispatch_intents as intents


CONSUMER_B = "b" * 40
CONSUMER_C = "c" * 40
STAGE_CONFIG = {
    "workflow": "platform-release-bridge.yml",
    "dispatch_correlation_input": "yoke_dispatch_id",
    "ref": "main",
    "reconcile_by_head_sha": False,
    "wait_for_ci": False,
    "input_bindings": {"consumer_sha": {"project": "platform", "branch": "main"}},
    "inputs": {"product_sha": "{head_sha}", "consumer_sha": "{consumer_sha}"},
}


def _intent(*, state: str, inputs: dict) -> intents.DispatchIntent:
    return intents.DispatchIntent(
        request_id="deploy:yoke:run-test:hosted-release",
        attempt=1,
        actor_id="1",
        authorization_scope="project:1",
        payload_checksum="checksum",
        correlation_id="yoke-dispatch:abc",
        state=state,
        workflow_run_id="9001",
        run_url=None,
        html_url=None,
        inputs=inputs,
    )


def _dispatch(*, fresh=False, gh_calls):
    def _fake_gh(*args, **kwargs):
        gh_calls.append(args)
        if args and args[0] == "trigger":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="new-run-id\n",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

    with mock.patch.object(
        # Satisfies _resolve_release_lineage_sha's checkout verification,
        # unrelated to the input-binding resolution under test.
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
            STAGE_CONFIG,
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
            sd="/tmp/sd",
        )


class TestDeclaredInputBindingDispatch:
    def test_fresh_resolution_binds_into_the_trigger_inputs(self):
        gh_calls: list = []
        with mock.patch.object(
            intents, "latest_intent", return_value=None,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            return_value=({"consumer_sha": CONSUMER_B}, ""),
        ) as resolve:
            rc, diag = _dispatch(gh_calls=gh_calls)

        assert (rc, diag) == (0, "")
        resolve.assert_called_once_with(
            STAGE_CONFIG["input_bindings"],
            request_id="deploy:yoke:run-test:hosted-release",
        )
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"consumer_sha={CONSUMER_B}" in trigger

    def test_retry_recovers_the_bound_pair_without_reresolving(self):
        # The wiring itself never touches latest_intent directly — that
        # lookup is resolve_declared_input_bindings' own responsibility,
        # already covered by test_deploy_pipeline_github_workflow_bindings.
        # This proves the dispatcher passes through whatever it returns.
        gh_calls: list = []
        with mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            return_value=({"consumer_sha": CONSUMER_B}, ""),
        ) as resolve:
            rc, diag = _dispatch(gh_calls=gh_calls)

        assert (rc, diag) == (0, "")
        assert resolve.call_args.kwargs["request_id"] == (
            "deploy:yoke:run-test:hosted-release"
        )
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"consumer_sha={CONSUMER_B}" in trigger

    def test_fresh_retrigger_resolves_with_no_recovery_request_id(self):
        # An explicit --fresh retrigger mints its own dispatch key, so the
        # binding resolver gets an empty request_id — nothing to recover.
        gh_calls: list = []
        with mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            return_value=({"consumer_sha": CONSUMER_C}, ""),
        ) as resolve:
            rc, diag = _dispatch(fresh=True, gh_calls=gh_calls)

        assert (rc, diag) == (0, "")
        assert resolve.call_args.kwargs["request_id"] == ""
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"consumer_sha={CONSUMER_C}" in trigger

    def test_binding_resolution_failure_stops_the_stage_before_dispatch(self):
        gh_calls: list = []
        with mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            return_value=({}, "no machine-config checkout is registered for 'platform'"),
        ):
            rc, diag = _dispatch(gh_calls=gh_calls)

        assert rc == 1
        assert "platform" in diag and "registered" in diag
        assert not [c for c in gh_calls if c and c[0] == "trigger"]

    def test_a_collision_with_a_concurrent_resolver_recovers_and_retries_once(self):
        # A concurrent resolver for the identical logical request won the
        # underlying claim with a different (also freshly-resolved) bound
        # pair -- e.g. the declared branch moved between the two callers'
        # independent reads. The first trigger attempt reports the DB-level
        # collision that produces; recovery must re-derive bound inputs
        # (the second resolve call, standing in for what now reads the
        # winner's durable intent) and retry the dispatch exactly once with
        # the recovered pair, succeeding rather than failing permanently.
        gh_calls: list = []
        trigger_attempts = {"n": 0}

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                trigger_attempts["n"] += 1
                if trigger_attempts["n"] == 1:
                    return subprocess.CompletedProcess(
                        args=args, returncode=4, stdout="",
                        stderr="Error: idempotency_key_collision: request_id "
                        "was already bound to a different canonical "
                        "workflow payload",
                    )
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="new-run-id\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
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
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            side_effect=[
                ({"consumer_sha": CONSUMER_C}, ""),  # this caller's own read
                ({"consumer_sha": CONSUMER_B}, ""),  # recovered winner's pair
            ],
        ) as resolve:
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                STAGE_CONFIG,
                name="hosted-release", run_id="run-test", member_items=[],
                github_repo="upyoke/platform", project="yoke",
                project_repo_path="", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40, sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        assert resolve.call_count == 2
        triggers = [c for c in gh_calls if c and c[0] == "trigger"]
        assert len(triggers) == 2
        assert f"consumer_sha={CONSUMER_C}" in triggers[0]
        assert f"consumer_sha={CONSUMER_B}" in triggers[1]

    def test_a_persistent_collision_after_recovery_stays_bounded_and_refuses(self):
        # The recovery-and-retry mechanism can only ever fix a collision
        # caused by a benign race over a value that legitimately varies
        # between reads (the declared binding). It has no way to fix -- and
        # must never paper over -- a collision whose real cause is a
        # different actor/authorization scope or a different reserved/
        # static input (head_sha/run_id/target_environment) already bound
        # to that exact request id: the one retry uses recovered bound
        # values but the SAME caller identity and SAME reserved inputs, so
        # a mismatch on either of those collides again at the dispatch
        # layer's own actor/scope/payload check. That second collision
        # must not trigger a further retry -- exactly one recovery attempt,
        # then a clean refusal, with bindings declared throughout.
        gh_calls: list = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(
                    args=args, returncode=4, stdout="",
                    stderr="Error: idempotency_key_collision: request_id "
                    "was already bound to a different actor, authorized "
                    "scope, or canonical workflow payload",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="a" * 40 + "\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event",
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
            side_effect=[
                ({"consumer_sha": CONSUMER_C}, ""),  # this caller's own read
                ({"consumer_sha": CONSUMER_B}, ""),  # recovery still succeeds
            ],
        ) as resolve:
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                STAGE_CONFIG,
                name="hosted-release", run_id="run-test", member_items=[],
                github_repo="upyoke/platform", project="yoke",
                project_repo_path="", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40, sd="/tmp/sd",
            )

        assert rc == 1
        assert "idempotency_key_collision" in diag
        assert resolve.call_count == 2
        triggers = [c for c in gh_calls if c and c[0] == "trigger"]
        assert len(triggers) == 2, "bounded to exactly one recovery retry"
        assert f"consumer_sha={CONSUMER_C}" in triggers[0]
        assert f"consumer_sha={CONSUMER_B}" in triggers[1]

    def test_a_collision_with_no_declared_bindings_is_not_retried(self):
        # Without declared bindings, a collision names a genuine
        # authority/actor/scope mismatch, not a race over a value that can
        # legitimately vary between reads -- retrying with identical args
        # can never resolve it, so it must fail rather than loop.
        gh_calls: list = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(
                    args=args, returncode=4, stdout="",
                    stderr="Error: idempotency_key_collision",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="a" * 40 + "\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event",
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
        ) as resolve:
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {**STAGE_CONFIG, "input_bindings": {}},
                name="hosted-release", run_id="run-test", member_items=[],
                github_repo="upyoke/platform", project="yoke",
                project_repo_path="", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40, sd="/tmp/sd",
            )

        assert rc == 1
        assert "idempotency_key_collision" in diag
        resolve.assert_not_called()
        assert len([c for c in gh_calls if c and c[0] == "trigger"]) == 1

    def test_a_stage_without_input_bindings_never_calls_the_resolver(self):
        gh_calls: list = []
        with mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="a" * 40 + "\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions",
            side_effect=lambda *a, **k: (
                gh_calls.append(a)
                or subprocess.CompletedProcess(
                    args=a, returncode=0,
                    stdout="new-run-id\n" if a and a[0] == "trigger" else "",
                )
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event",
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "resolve_declared_input_bindings",
        ) as resolve:
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {**STAGE_CONFIG, "input_bindings": {}},
                name="hosted-release", run_id="run-test", member_items=[],
                github_repo="upyoke/platform", project="yoke",
                project_repo_path="", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40, sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        resolve.assert_not_called()
