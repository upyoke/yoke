"""Guarded deployment-run membership function coverage."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN
from yoke_core.domain.function_authz_scope import classify
from yoke_core.domain.function_authz_types import ORG
from yoke_core.domain.handlers import deployment_run_membership as membership
from yoke_core.domain.yoke_function_dispatch_target import resolve_target_public_ref


RUN_ID = "run-20260909-001"
RUN_PROJECT = "yoke_core.domain.deployment_runs_crud_query.cmd_get"
DEPLOY_LOCK = "yoke_core.domain.handlers.deployment_run_membership.deploy_lock_refusal"
ADD_ITEM = "yoke_core.domain.deployment_runs_crud_mutate.cmd_add_item"
VALIDATE = "yoke_core.domain.deployment_runs_validation.cmd_validate_composition"


def _add_request(item_id: int = 47):
    return _request(
        function="deployment_runs.add_item",
        target=TargetRef(kind="item", item_id=item_id),
        payload={"run_id": RUN_ID},
    )


def _validate_request():
    return _request(
        function="deployment_runs.validate_composition",
        target=TargetRef(kind="workflow_run", workflow_run_id=RUN_ID),
    )


class TestDeploymentRunMembership(unittest.TestCase):
    def test_membership_functions_are_registered(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        add_item = lookup("deployment_runs.add_item")
        validate = lookup("deployment_runs.validate_composition")
        self.assertIsNotNone(add_item)
        self.assertIsNotNone(validate)
        self.assertEqual(add_item.target_kinds, ("item",))
        self.assertEqual(validate.target_kinds, ("workflow_run",))

    def test_registered_family_requires_org_admin_authority(self):
        for function_id, side_effects in (
            ("deployment_runs.add_item", True),
            ("deployment_runs.validate_composition", False),
        ):
            spec = classify(
                function_id,
                side_effects=side_effects,
                project_permission=None,
            )
            self.assertEqual(spec.scope, ORG)
            self.assertEqual(spec.permission_key, PERM_ORG_ADMIN)

    def test_add_item_reuses_internal_integer_and_deploy_lock(self):
        with (
            patch(RUN_PROJECT, return_value="yoke"),
            patch(DEPLOY_LOCK, return_value=None) as lock,
            patch(ADD_ITEM, return_value="Added item 47") as add_item,
        ):
            outcome = membership.handle_deployment_run_add_item(_add_request())

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["item_id"], 47)
        add_item.assert_called_once_with(RUN_ID, 47)
        lock.assert_called_once_with(
            "yoke",
            operation="deployment_runs.add_item",
            session_id="s-1",
        )

    def test_add_item_forwards_explicit_intent_and_requirements(self):
        request = _request(
            function="deployment_runs.add_item",
            target=TargetRef(kind="item", item_id=47),
            payload={
                "run_id": RUN_ID,
                "delivery_intent": "progress",
                "requirement_ids": [11, 13],
                "plan_ids": [7],
            },
        )
        with (
            patch(RUN_PROJECT, return_value="yoke"),
            patch(DEPLOY_LOCK, return_value=None),
            patch(ADD_ITEM, return_value="Added item 47") as add_item,
        ):
            outcome = membership.handle_deployment_run_add_item(request)
        self.assertTrue(outcome.primary_success)
        add_item.assert_called_once_with(
            RUN_ID,
            47,
            delivery_intent="progress",
            requirement_ids=[11, 13],
            plan_ids=[7],
        )

    def test_add_item_refuses_without_the_run_project_deploy_lock(self):
        with (
            patch(RUN_PROJECT, return_value="yoke"),
            patch(DEPLOY_LOCK, return_value="Take DEPLOY:yoke first"),
            patch(ADD_ITEM) as add_item,
        ):
            outcome = membership.handle_deployment_run_add_item(_add_request())

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "deploy_lock_required")
        self.assertIn("DEPLOY:yoke", outcome.error.message)
        add_item.assert_not_called()

    def test_add_item_surfaces_created_only_and_project_guards(self):
        refusals = (
            "membership is mutable only while status='created'",
            "item YOK-47 belongs to project 'other'",
        )
        for refusal in refusals:
            with self.subTest(refusal=refusal):
                with (
                    patch(RUN_PROJECT, return_value="yoke"),
                    patch(DEPLOY_LOCK, return_value=None),
                    patch(ADD_ITEM, side_effect=ValueError(refusal)),
                ):
                    outcome = membership.handle_deployment_run_add_item(_add_request())
                self.assertFalse(outcome.primary_success)
                self.assertEqual(outcome.error.code, "membership_rejected")
                self.assertEqual(outcome.error.message, refusal)

    def test_validate_composition_returns_the_existing_result(self):
        with (
            patch(RUN_PROJECT, return_value="yoke"),
            patch(DEPLOY_LOCK, return_value=None),
            patch(VALIDATE, return_value=(True, "OK")) as validate,
        ):
            outcome = membership.handle_deployment_run_validate_composition(
                _validate_request()
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["message"], "OK")
        validate.assert_called_once_with(RUN_ID)

    def test_validate_composition_surfaces_the_existing_refusal(self):
        message = "FAIL: Composition validation failed: project mismatch"
        with (
            patch(RUN_PROJECT, return_value="yoke"),
            patch(DEPLOY_LOCK, return_value=None),
            patch(VALIDATE, return_value=(False, message)),
        ):
            outcome = membership.handle_deployment_run_validate_composition(
                _validate_request()
            )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "composition_invalid")
        self.assertEqual(outcome.error.message, message)


def test_external_public_ref_round_trip_keeps_internal_item_identity(
    test_db,
) -> None:
    test_db.execute("UPDATE projects SET public_item_prefix='EXT' WHERE id=2")
    test_db.commit()
    insert_item(
        test_db,
        id=9542,
        project_id=2,
        project_sequence=7,
        workflow_id="issue",
    )
    request = _request(
        function="deployment_runs.add_item",
        target=TargetRef(kind="item", public_ref="EXT-7"),
        payload={"run_id": RUN_ID},
    )
    assert resolve_target_public_ref(request) is None
    assert request.target.item_id == 9542
    with (
        patch(RUN_PROJECT, return_value="externalwebapp"),
        patch(DEPLOY_LOCK, return_value=None),
        patch(ADD_ITEM, return_value="Added item 9542") as add_item,
    ):
        outcome = membership.handle_deployment_run_add_item(request)
    assert outcome.primary_success
    assert outcome.result_payload["item_id"] == 9542
    add_item.assert_called_once_with(RUN_ID, 9542)


if __name__ == "__main__":
    unittest.main()
