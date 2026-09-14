"""Declarative external-project input bindings for github-actions-workflow stages.

The failure this exists to prevent: a stage resolves a value from another
project's branch tip on every call, including retries, so a retry after that
branch moved could silently dispatch (or collide on) a different logical
pair than the one already in flight.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow_bindings as bindings
from yoke_core.domain import deploy_pipeline_run_context
from yoke_core.domain import github_workflow_dispatch_intents as intents


CONSUMER_B = "b" * 40
CONSUMER_C = "c" * 40


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


class TestResolveBranchHeadSha:
    def test_resolves_the_remote_branch_tip(self):
        with mock.patch.object(
            bindings, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=f"{CONSUMER_B}\trefs/heads/main\n",
            ),
        ) as run_cmd:
            sha, error = bindings.resolve_branch_head_sha("/platform", "main")

        assert (sha, error) == (CONSUMER_B, "")
        run_cmd.assert_called_once_with(
            ["git", "-C", "/platform", "ls-remote", "origin", "refs/heads/main"]
        )

    def test_unreachable_remote_fails_clearly_rather_than_binding_empty(self):
        with mock.patch.object(
            bindings, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="Host key verification failed",
            ),
        ):
            sha, error = bindings.resolve_branch_head_sha("/platform", "main")

        assert sha == ""
        assert "main" in error and "/platform" in error


class TestResolveDeclaredInputBindings:
    def test_no_bindings_is_a_no_op(self):
        resolved, error = bindings.resolve_declared_input_bindings(
            {}, request_id="deploy:yoke:run-test:hosted-release",
        )

        assert (resolved, error) == ({}, "")

    def test_fresh_resolution_when_no_prior_intent_exists(self):
        with mock.patch.object(
            intents, "latest_intent", return_value=None,
        ), mock.patch.object(
            deploy_pipeline_run_context, "resolve_project_checkout_path",
            return_value="/platform",
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha", return_value=(CONSUMER_B, ""),
        ) as resolve_head:
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        resolve_head.assert_called_once_with("/platform", "main")

    def test_recovers_a_pending_intent_s_bound_pair_without_reresolving(self):
        with mock.patch.object(
            intents, "latest_intent",
            return_value=_intent(state="pending", inputs={"consumer_sha": CONSUMER_B}),
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha",
        ) as resolve_head:
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        resolve_head.assert_not_called()

    def test_recovers_a_completed_intent_s_bound_pair_too(self):
        with mock.patch.object(
            intents, "latest_intent",
            return_value=_intent(state="completed", inputs={"consumer_sha": CONSUMER_B}),
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha",
        ) as resolve_head:
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert resolved == {"consumer_sha": CONSUMER_B}
        resolve_head.assert_not_called()

    def test_a_rejected_intent_recovers_its_bound_pair_not_a_fresh_one(self):
        # Rejection means GitHub refused the POST -- a retry may attempt it
        # again -- not that the bound payload itself may now differ. Trunk
        # having advanced B -> C since must not change what this retry
        # binds: it recovers the rejected attempt's own B, never C.
        with mock.patch.object(
            intents, "latest_intent",
            return_value=_intent(state="rejected", inputs={"consumer_sha": CONSUMER_B}),
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha", return_value=(CONSUMER_C, ""),
        ) as resolve_head:
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        resolve_head.assert_not_called()

    def test_no_request_id_always_resolves_fresh(self):
        # An explicit --fresh retrigger mints its own key; nothing durable
        # for that key can exist yet, so there is nothing to recover.
        with mock.patch.object(
            intents, "latest_intent",
        ) as latest_intent, mock.patch.object(
            deploy_pipeline_run_context, "resolve_project_checkout_path",
            return_value="/platform",
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha", return_value=(CONSUMER_B, ""),
        ):
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="",
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        latest_intent.assert_not_called()

    def test_missing_checkout_registration_fails_clearly(self):
        with mock.patch.object(
            intents, "latest_intent", return_value=None,
        ), mock.patch.object(
            deploy_pipeline_run_context, "resolve_project_checkout_path",
            return_value="",
        ):
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert resolved == {}
        assert "platform" in error and "registered" in error

    def test_a_malformed_binding_fails_clearly(self):
        with mock.patch.object(intents, "latest_intent", return_value=None):
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert resolved == {}
        assert "consumer_sha" in error

    def test_a_binding_name_reserved_for_a_built_in_placeholder_is_refused(self):
        resolved, error = bindings.resolve_declared_input_bindings(
            {"head_sha": {"project": "platform", "branch": "main"}},
            request_id="deploy:yoke:run-test:hosted-release",
        )

        assert resolved == {}
        assert "head_sha" in error

    def test_a_non_rejected_intent_missing_the_binding_fails_closed(self):
        # The intent exists and is still live, but does not record
        # consumer_sha (an older shape, or a different declared binding
        # set) -- resolving fresh here would risk rebinding a logical
        # dispatch that already exists under this exact request id.
        with mock.patch.object(
            intents, "latest_intent",
            return_value=_intent(state="pending", inputs={"other_key": "x"}),
        ), mock.patch.object(
            bindings, "resolve_branch_head_sha",
        ) as resolve_head:
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id="deploy:yoke:run-test:hosted-release",
            )

        assert resolved == {}
        assert "consumer_sha" in error
        resolve_head.assert_not_called()


class TestResolveDeclaredInputBindingsAgainstTheRealIntentStore:
    """Bounded integration coverage against the actual durable intent store,
    not a mocked latest_intent -- proves the recovery path holds for a real
    claimed intent, not just a hand-built stand-in.
    """

    REQUEST_ID = "deploy:yoke:run-42:hosted-release"

    @staticmethod
    def _claim_pending(request_id: str, *, consumer_sha: str) -> None:
        from yoke_core.domain.github_workflow_dispatch_intents import claim_attempt

        assert claim_attempt(
            request_id=request_id,
            attempt=1,
            actor_id="2",
            authorization_scope="project:1",
            payload_checksum="checksum",
            repo="upyoke/platform",
            workflow="platform-release-pin-check.yml",
            workflow_ref=consumer_sha,
            inputs={"consumer_sha": consumer_sha},
            correlation_id=f"correlation-{request_id}",
        )

    def test_a_lost_response_restart_recovers_the_already_claimed_pair(
        self, tmp_path,
    ) -> None:
        from runtime.api.fixtures.file_test_db import init_test_db

        with init_test_db(tmp_path), mock.patch.object(
            bindings, "resolve_branch_head_sha",
        ) as resolve_head:
            self._claim_pending(self.REQUEST_ID, consumer_sha=CONSUMER_B)

            # The restart: the same logical dispatch is asked to resolve
            # again, as if the first POST's response never made it back.
            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id=self.REQUEST_ID,
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        resolve_head.assert_not_called()

    def test_a_second_caller_racing_a_moved_trunk_never_diverges(
        self, tmp_path,
    ) -> None:
        # First caller already claimed and bound B. A second caller for the
        # exact same logical request races in after trunk has moved to C;
        # it must recover B, never resolve or bind C.
        from runtime.api.fixtures.file_test_db import init_test_db

        with init_test_db(tmp_path), mock.patch.object(
            bindings, "resolve_branch_head_sha", return_value=(CONSUMER_C, ""),
        ) as resolve_head:
            self._claim_pending(self.REQUEST_ID, consumer_sha=CONSUMER_B)

            resolved, error = bindings.resolve_declared_input_bindings(
                {"consumer_sha": {"project": "platform", "branch": "main"}},
                request_id=self.REQUEST_ID,
            )

        assert (resolved, error) == ({"consumer_sha": CONSUMER_B}, "")
        assert resolved.get("consumer_sha") != CONSUMER_C
        resolve_head.assert_not_called()

    def test_two_callers_reading_before_either_claims_the_loser_recovers_the_winner(
        self, tmp_path,
    ) -> None:
        # Real interleaving, not sequential recovery: BOTH callers read
        # latest_intent and see nothing durable yet -- neither has claimed --
        # before either attempts to claim. Trunk moved between their two
        # independent reads, so they resolve different fresh pairs. Only one
        # claim_attempt can win the shared (request_id, attempt) row; the
        # loser's own second resolve call -- what a collision-retry drives --
        # must recover the winner's exact bound pair, never its own losing
        # resolution, and never fail permanently.
        from runtime.api.fixtures.file_test_db import init_test_db
        from yoke_core.domain.github_workflow_dispatch_intents import claim_attempt

        with init_test_db(tmp_path), mock.patch.object(
            deploy_pipeline_run_context, "resolve_project_checkout_path",
            return_value="/platform",
        ):
            with mock.patch.object(
                bindings, "resolve_branch_head_sha", return_value=(CONSUMER_B, ""),
            ):
                resolved_a, error_a = bindings.resolve_declared_input_bindings(
                    {"consumer_sha": {"project": "platform", "branch": "main"}},
                    request_id=self.REQUEST_ID,
                )
            with mock.patch.object(
                bindings, "resolve_branch_head_sha", return_value=(CONSUMER_C, ""),
            ):
                resolved_b, error_b = bindings.resolve_declared_input_bindings(
                    {"consumer_sha": {"project": "platform", "branch": "main"}},
                    request_id=self.REQUEST_ID,
                )
            # Both read no intent (real interleaving); both resolved fresh,
            # and they diverged, exactly the shape a bare retry can't heal.
            assert (resolved_a, error_a) == ({"consumer_sha": CONSUMER_B}, "")
            assert (resolved_b, error_b) == ({"consumer_sha": CONSUMER_C}, "")

            winner = claim_attempt(
                request_id=self.REQUEST_ID, attempt=1, actor_id="1",
                authorization_scope="project:1", payload_checksum="checksum-a",
                repo="upyoke/platform", workflow="platform-release-pin-check.yml",
                workflow_ref=CONSUMER_B, inputs=resolved_a,
                correlation_id=f"correlation-a-{self.REQUEST_ID}",
            )
            loser = claim_attempt(
                request_id=self.REQUEST_ID, attempt=1, actor_id="1",
                authorization_scope="project:1", payload_checksum="checksum-b",
                repo="upyoke/platform", workflow="platform-release-pin-check.yml",
                workflow_ref=CONSUMER_C, inputs=resolved_b,
                correlation_id=f"correlation-b-{self.REQUEST_ID}",
            )
            assert (winner, loser) == (True, False)

            # The loser's collision-retry re-resolves under the same request
            # id -- this is the call the real dispatcher makes after an
            # idempotency_key_collision.
            with mock.patch.object(bindings, "resolve_branch_head_sha") as resolve_head:
                recovered, error = bindings.resolve_declared_input_bindings(
                    {"consumer_sha": {"project": "platform", "branch": "main"}},
                    request_id=self.REQUEST_ID,
                )

        assert (recovered, error) == ({"consumer_sha": CONSUMER_B}, "")
        assert recovered.get("consumer_sha") != CONSUMER_C
        resolve_head.assert_not_called()
