"""Doctor function-call cursor and scope filtering tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import reads_misc
from yoke_core.engines.doctor_applicability import CheckApplicability
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
                # Cursor mechanics over a fixed roster: pinning the runtime
                # keeps the roster exactly the two patched checks, instead of
                # also collecting whatever this checkout declares in its own
                # .yoke/doctor/ folder.
                first = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "yoke",
                    "runtime": "hosted",
                    "max_checks": 1,
                }))
                second = reads_misc.handle_doctor_run(_request({
                    "quick": True,
                    "project": "yoke",
                    "runtime": "hosted",
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

    def test_source_tree_checks_report_not_applicable_without_a_checkout(self):
        # The checks declare on their own rows rather than borrowing real
        # slugs: what is being tested is the applicability contract, not
        # which slugs happen to be in the engine table today.
        source_tree = CheckApplicability(requires_source_checkout=True)
        fake_hcs = [
            HealthCheck(
                slug="reads-a-source-tree",
                name="Source-tree HC",
                fn=_record("source"),
                applicability=source_tree,
            ),
            HealthCheck(
                slug="reads-the-database",
                name="DB HC",
                fn=_record("db"),
                applicability=CheckApplicability(),
            ),
            HealthCheck(
                slug="reads-a-checkout",
                name="Checkout-dependent HC",
                fn=_record("checkout"),
                applicability=source_tree,
            ),
            HealthCheck(
                slug="scans-package-namespaces",
                name="Namespace source HC",
                fn=_record("namespaces"),
                applicability=source_tree,
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
                    "project": "yoke",
                    "runtime": "hosted",
                }))

        self.assertTrue(outcome.primary_success)
        rows = outcome.result_payload["results"]
        by_severity = {row["hc"]: row["severity"] for row in rows}
        self.assertEqual(by_severity["HC-db"], "PASS")
        # Named with a reason, not dropped: the report must be able to
        # distinguish "checked and clean" from "could not be checked here".
        for hc in (
            "HC-reads-a-source-tree",
            "HC-reads-a-checkout",
            "HC-scans-package-namespaces",
        ):
            self.assertEqual(by_severity[hc], "N/A")
        self.assertEqual(outcome.result_payload["na_count"], 3)
        self.assertEqual(outcome.result_payload["pass_count"], 1)
        self.assertEqual(outcome.result_payload["runtime"], "hosted")

    def test_project_safe_quick_uses_the_project_read_permission_subset(self):
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
                slug="project-gh-auth",
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
                    "project": "externalwebapp",
                    "runtime": "hosted",
                    "project_safe_quick": True,
                }))

        self.assertTrue(outcome.primary_success)
        executed = [
            row["hc"] for row in outcome.result_payload["results"]
            if row["severity"] != "N/A"
        ]
        self.assertEqual(executed, ["HC-token", "HC-flows", "HC-ci"])
