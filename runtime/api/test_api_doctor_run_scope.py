"""Doctor function-call cursor and scope filtering tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from yoke_core.domain.handlers import reads_misc
from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    DoctorContext,
    RUNTIME_LOCAL,
)
from yoke_core.engines.doctor_project_checks import Discovery
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


def _quick(project: str = "yoke", **extra):
    payload = {"quick": True, "project": project, "runtime": "hosted"}
    payload.update(extra)
    return _request(payload)


def _record(label):
    def _fake_hc_fn(conn, args, rec):
        rec.record(f"HC-{label}", f"{label} HC", "PASS", "all good")

    return _fake_hc_fn


class _Conn:
    def execute(self, *_args, **_kwargs):
        return self

    def commit(self):
        pass

    def close(self):
        pass


class _AbortedTransactionConn:
    def __init__(self):
        self.aborted = False

    def execute(self, statement, *_args):
        if self.aborted:
            raise RuntimeError("current transaction is aborted")
        if statement == "synthetic broken query":
            self.aborted = True
            raise RuntimeError("synthetic query failed")
        return self

    def fetchone(self):
        return None

    def rollback(self):
        self.aborted = False

    def commit(self):
        pass

    def close(self):
        pass


def _record_query_failure_without_raising(conn, args, rec):
    try:
        conn.execute("synthetic broken query")
    except RuntimeError:
        rec.record(
            "HC-query-failure",
            "Query-failure HC",
            "FAIL",
            "the original query failed",
        )


def _record_after_query_failure(conn, args, rec):
    conn.execute("synthetic healthy query")
    rec.record("HC-after-query", "After-query HC", "PASS", "query ran")


def _run_only_with_project_roster(
    *,
    context: DoctorContext,
    checks: list[HealthCheck],
    slug: str,
):
    with (
        patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", []),
        patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        patch(
            "yoke_core.engines.doctor_context.resolve_context",
            return_value=context,
        ),
        patch(
            "yoke_core.engines.doctor_roster.discover_project_checks",
            return_value=Discovery(checks, []),
        ),
    ):
        return reads_misc.handle_doctor_run(
            _request(
                {
                    "only": slug,
                    "project": context.project,
                    "runtime": context.runtime,
                }
            )
        )


class TestDoctorRunScope(unittest.TestCase):
    def test_only_accepts_a_check_from_the_target_project_roster(self):
        project_hc = HealthCheck(
            slug="project-policy",
            name="Project policy HC",
            fn=_record("project-policy"),
        )
        context = DoctorContext(
            project="yoke",
            runtime=RUNTIME_LOCAL,
            self_project="yoke",
            source_checkout=Path("/target/yoke"),
        )

        outcome = _run_only_with_project_roster(
            context=context,
            checks=[project_hc],
            slug="HC-project-policy",
        )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            [row["hc"] for row in outcome.result_payload["results"]],
            ["HC-project-policy"],
        )

    def test_only_does_not_borrow_checks_from_another_project_roster(self):
        context = DoctorContext(
            project="external",
            runtime=RUNTIME_LOCAL,
            self_project="yoke",
            source_checkout=Path("/target/external"),
        )

        outcome = _run_only_with_project_roster(
            context=context,
            checks=[],
            slug="HC-project-policy",
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_check")

    def test_returns_cursor_for_chunked_runs(self):
        fake_hcs = [
            HealthCheck(slug="first", name="First HC", fn=_record("first")),
            HealthCheck(slug="second", name="Second HC", fn=_record("second")),
        ]

        with (
            patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs),
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        ):
            first = reads_misc.handle_doctor_run(_quick(max_checks=1))
            second = reads_misc.handle_doctor_run(
                _quick(max_checks=1, cursor_after="first"),
            )

        self.assertTrue(first.primary_success)
        self.assertFalse(first.result_payload["done"])
        self.assertEqual(first.result_payload["cursor"], "first")
        self.assertEqual(first.result_payload["results"][0]["hc"], "HC-first")
        self.assertTrue(second.primary_success)
        self.assertTrue(second.result_payload["done"])
        self.assertEqual(second.result_payload["cursor"], "second")
        self.assertEqual(second.result_payload["results"][0]["hc"], "HC-second")

    def test_source_tree_checks_report_not_applicable_without_a_checkout(self):
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

        with (
            patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs),
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        ):
            outcome = reads_misc.handle_doctor_run(_quick())

        self.assertTrue(outcome.primary_success)
        rows = outcome.result_payload["results"]
        by_severity = {row["hc"]: row["severity"] for row in rows}
        self.assertEqual(by_severity["HC-db"], "PASS")
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

        with (
            patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs),
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        ):
            outcome = reads_misc.handle_doctor_run(
                _quick(project="externalwebapp", project_safe_quick=True),
            )

        self.assertTrue(outcome.primary_success)
        executed = [
            row["hc"]
            for row in outcome.result_payload["results"]
            if row["severity"] != "N/A"
        ]
        self.assertEqual(executed, ["HC-token", "HC-flows", "HC-ci"])

    def test_normal_return_with_aborted_transaction_does_not_poison_roster(self):
        conn = _AbortedTransactionConn()
        fake_hcs = [
            HealthCheck(
                slug="query-failure",
                name="Query-failure HC",
                fn=_record_query_failure_without_raising,
            ),
            HealthCheck(
                slug="after-query",
                name="After-query HC",
                fn=_record_after_query_failure,
            ),
        ]

        with (
            patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs),
            patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        ):
            outcome = reads_misc.handle_doctor_run(_quick())

        self.assertTrue(outcome.primary_success)
        by_hc = {row["hc"]: row for row in outcome.result_payload["results"]}
        self.assertEqual(by_hc["HC-query-failure"]["severity"], "FAIL")
        self.assertEqual(
            by_hc["HC-query-failure"]["detail"],
            "the original query failed",
        )
        self.assertEqual(by_hc["HC-after-query"]["severity"], "PASS")
