"""Handler coverage for binding a project's verification command to its gate."""

from __future__ import annotations

import json
import unittest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_registered_command_writes as writes
from yoke_core.domain.projects_seed_ci_workflow import CI_WORKFLOW_CAPABILITY_TYPE
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    LOCAL_COMMAND_METHOD_ID,
)
from runtime.api.fixtures.pg_testdb import test_database


def _request(payload: dict, *, target_kind: str = "global") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.registered_command.set",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def _plan_case(conn, plan_id: int) -> tuple[str, dict]:
    row = conn.execute(
        "SELECT method_id, method_config FROM qa_plan_cases WHERE plan_id=%s",
        (int(plan_id),),
    ).fetchone()
    config = row["method_config"]
    if isinstance(config, str):
        config = json.loads(config)
    return str(row["method_id"]), config


class TestRegisteredCommandSet(unittest.TestCase):
    def test_binds_scope_without_naming_an_environment(self) -> None:
        """A command case runs in a worktree or in CI, never against a site."""
        with test_database() as conn:
            outcome = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest tests/",
                    }
                )
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            result = outcome.result_payload["result"]
            plan_id = int(result["plan_id"])
            slug = conn.execute(
                "SELECT slug FROM qa_plans WHERE id=%s", (plan_id,)
            ).fetchone()["slug"]
            method_id, config = _plan_case(conn, plan_id)

        self.assertEqual(slug, "registered-command-quick")
        self.assertEqual(config["command"], "python3 -m pytest tests/")
        self.assertEqual(method_id, LOCAL_COMMAND_METHOD_ID)
        self.assertEqual(result["method_id"], LOCAL_COMMAND_METHOD_ID)
        self.assertEqual(result["ci_workflow"], "")
        self.assertEqual(result["target_mode"], "project")
        self.assertIsNone(result["target_environment"])
        self.assertFalse(result["requires_base_url"])

    def test_local_deployed_scope_selects_one_explicit_target_mode(self) -> None:
        with test_database() as conn:
            runtime = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "e2e",
                        "command": "python3 -m pytest tests/e2e",
                        "requires_base_url": True,
                    }
                )
            )
            environment = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "smoke",
                        "command": "python3 -m pytest tests/smoke",
                        "target_environment": "development",
                    }
                )
            )
            runtime_case = _plan_case(
                conn, int(runtime.result_payload["result"]["plan_id"])
            )[1]

        self.assertTrue(runtime.primary_success, runtime.error)
        self.assertEqual(runtime.result_payload["result"]["target_mode"], "runtime-base-url")
        self.assertTrue(runtime_case["requires_base_url"])
        self.assertTrue(environment.primary_success, environment.error)
        self.assertEqual(environment.result_payload["result"]["target_mode"], "environment")
        self.assertEqual(
            environment.result_payload["result"]["target_environment"],
            "Yoke API/development",
        )

    def test_invalid_target_combinations_are_refused_before_plan_writes(self) -> None:
        payloads = [
            {
                "project": "yoke",
                "scope": "quick",
                "command": "true",
                "target_environment": "development",
            },
            {"project": "yoke", "scope": "e2e", "command": "true"},
            {
                "project": "yoke",
                "scope": "smoke",
                "command": "true",
                "target_environment": "development",
                "requires_base_url": True,
            },
        ]
        with test_database() as conn:
            outcomes = [
                writes.handle_registered_command_set(_request(payload))
                for payload in payloads
            ]
            plans = conn.execute(
                "SELECT COUNT(*) AS n FROM qa_plans "
                "WHERE slug LIKE 'registered-command-%'"
            ).fetchone()["n"]

        self.assertTrue(all(not outcome.primary_success for outcome in outcomes))
        self.assertIn("project-targeted", outcomes[0].error.message)
        self.assertIn("exactly one target", outcomes[1].error.message)
        self.assertIn("exactly one target", outcomes[2].error.message)
        self.assertEqual(int(plans), 0)

    def test_quick_and_full_preserve_distinct_arbitrary_commands(self) -> None:
        commands = {
            "quick": "mvn -q -DskipITs test",
            "full": "docker compose run --rm tests mvn verify",
        }
        stored: dict[str, tuple[str, str]] = {}

        with test_database() as conn:
            for scope, command in commands.items():
                outcome = writes.handle_registered_command_set(
                    _request(
                        {
                            "project": "yoke",
                            "scope": scope,
                            "command": command,
                        }
                    )
                )
                self.assertTrue(outcome.primary_success, outcome.error)
                result = outcome.result_payload["result"]
                method_id, config = _plan_case(conn, int(result["plan_id"]))
                stored[scope] = (method_id, config["command"])

        self.assertEqual(stored["quick"], (LOCAL_COMMAND_METHOD_ID, commands["quick"]))
        self.assertEqual(stored["full"], (LOCAL_COMMAND_METHOD_ID, commands["full"]))

    def test_binding_converges_the_project_default_attachments(self) -> None:
        """The gate reads project defaults; binding must write them itself."""
        with test_database() as conn:
            outcome = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest tests/",
                    }
                )
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            result = outcome.result_payload["result"]
            defaults = conn.execute(
                "SELECT workflow_id, transition_id FROM qa_plan_project_defaults "
                "WHERE plan_id=%s ORDER BY workflow_id",
                (int(result["plan_id"]),),
            ).fetchall()

        self.assertTrue(defaults, "quick must attach at a gating transition")
        self.assertTrue(result["workflow_ids"])
        for row in defaults:
            self.assertEqual(
                result["transitions"][str(row["workflow_id"])],
                str(row["transition_id"]),
            )

    def test_declared_ci_workflow_routes_the_case_to_ci(self) -> None:
        with test_database() as conn:
            conn.execute(
                "INSERT INTO project_capabilities (project_id, type, settings) "
                "VALUES (1, %s, %s)",
                (CI_WORKFLOW_CAPABILITY_TYPE, json.dumps({"workflow_file": "ci.yml"})),
            )
            conn.commit()
            outcome = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest tests/",
                    }
                )
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            result = outcome.result_payload["result"]
            method_id, _ = _plan_case(conn, int(result["plan_id"]))

        self.assertEqual(method_id, CI_COMMAND_METHOD_ID)
        self.assertEqual(result["method_id"], CI_COMMAND_METHOD_ID)
        self.assertEqual(result["ci_workflow"], "ci.yml")

    def test_rebinding_the_same_scope_reuses_its_plan(self) -> None:
        with test_database() as conn:
            first = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest tests/",
                    }
                )
            )
            second = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest runtime/",
                    }
                )
            )
            self.assertTrue(second.primary_success, second.error)
            plan_id = int(second.result_payload["result"]["plan_id"])
            _, config = _plan_case(conn, plan_id)

        self.assertEqual(plan_id, int(first.result_payload["result"]["plan_id"]))
        self.assertEqual(config["command"], "python3 -m pytest runtime/")

    def test_unsupported_scope_is_refused_with_a_named_reason(self) -> None:
        with test_database():
            outcome = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "yoke",
                        "scope": "smoke-test",
                        "command": "python3 -m pytest",
                    }
                )
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "incompatible")
        self.assertIn("smoke-test", outcome.error.message)

    def test_unknown_project_is_refused_before_any_write(self) -> None:
        with test_database() as conn:
            outcome = writes.handle_registered_command_set(
                _request(
                    {
                        "project": "not-a-project",
                        "scope": "quick",
                        "command": "python3 -m pytest",
                    }
                )
            )
            plans = conn.execute(
                "SELECT COUNT(*) AS n FROM qa_plans "
                "WHERE slug='registered-command-quick'"
            ).fetchone()["n"]

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")
        self.assertEqual(int(plans), 0)

    def test_non_global_target_is_refused(self) -> None:
        outcome = writes.handle_registered_command_set(
            _request(
                {"project": "yoke", "scope": "quick", "command": "x"},
                target_kind="item",
            )
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_empty_command_is_refused(self) -> None:
        outcome = writes.handle_registered_command_set(
            _request({"project": "yoke", "scope": "quick", "command": ""})
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
