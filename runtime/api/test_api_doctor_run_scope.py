"""Doctor function-call cursor and scope filtering tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import reads_misc
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="doctor.run.run",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _record(label):
    def _fake_hc_fn(conn, args, rec):
        rec.record(f"HC-{label}", f"{label} HC", "PASS", "all good")
    return _fake_hc_fn


class _Conn:
    def close(self):
        pass


class TestDoctorRunScope(unittest.TestCase):
    def test_returns_cursor_for_chunked_runs(self):
        fake_hcs = [
            HealthCheck(slug="first", name="First HC", fn=_record("first")),
            HealthCheck(slug="second", name="Second HC", fn=_record("second")),
        ]

        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
            ):
                first = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "yoke",
                    "max_checks": 1,
                }))
                second = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "yoke",
                    "max_checks": 1,
                    "cursor_after": "first",
                }))

        self.assertTrue(first.primary_success)
        self.assertFalse(first.result_payload["done"])
        self.assertEqual(first.result_payload["cursor"], "first")
        self.assertEqual(first.result_payload["results"][0]["hc"], "HC-first")
        self.assertTrue(second.primary_success)
        self.assertTrue(second.result_payload["done"])
        self.assertEqual(second.result_payload["cursor"], "second")
        self.assertEqual(second.result_payload["results"][0]["hc"], "HC-second")

    def test_can_skip_source_tree_checks(self):
        fake_hcs = [
            HealthCheck(
                slug="workspace-anchored-writer-authority",
                name="Source-tree HC",
                fn=_record("source"),
            ),
            HealthCheck(slug="status-consistency", name="DB HC", fn=_record("db")),
        ]

        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
            ):
                outcome = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "yoke",
                    "skip_source_tree_checks": True,
                }))

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            [row["hc"] for row in outcome.result_payload["results"]],
            ["HC-db"],
        )

    def test_project_quick_with_source_tree_skip_uses_product_safe_subset(self):
        fake_hcs = [
            HealthCheck(slug="status-consistency", name="Global", fn=_record("global")),
            HealthCheck(
                slug="project-repo-exists",
                name="Server-local project repo",
                fn=_record("repo"),
            ),
            HealthCheck(
                slug="server-checkout-independence",
                name="Server checkout",
                fn=_record("server"),
            ),
            HealthCheck(
                slug="project-gh-token",
                name="Project token",
                fn=_record("token"),
            ),
            HealthCheck(
                slug="project-deploy-flows",
                name="Project flows",
                fn=_record("flows"),
            ),
            HealthCheck(
                slug="projects-ci-workflow-configured",
                name="Project CI",
                fn=_record("ci"),
            ),
        ]

        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
            ):
                outcome = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "buzz",
                    "skip_source_tree_checks": True,
                }))

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            [row["hc"] for row in outcome.result_payload["results"]],
            ["HC-token", "HC-flows", "HC-ci"],
        )
