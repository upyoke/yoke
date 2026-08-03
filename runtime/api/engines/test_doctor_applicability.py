"""Applicability declarations decide what a doctor run can honestly answer."""

from __future__ import annotations

import unittest
from pathlib import Path

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    DoctorContext,
    NOT_APPLICABLE,
    PROJECT_SCOPE_EXTERNAL,
    PROJECT_SCOPE_SELF,
    RUNTIME_HOSTED,
    RUNTIME_LOCAL,
    RUNTIME_SERVER,
    UNIVERSAL,
    not_applicable_reason,
)
from yoke_core.engines.doctor_applicability_declarations import (
    DECLARATIONS,
    applicability_for,
    undeclared_slugs,
)
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import RecordCollector


def _context(**overrides) -> DoctorContext:
    defaults = dict(
        project="acme",
        runtime=RUNTIME_LOCAL,
        self_project="yoke",
        source_checkout=Path("/checkouts/acme"),
        capabilities=frozenset(),
    )
    defaults.update(overrides)
    return DoctorContext(**defaults)


class TestApplicabilityAxes(unittest.TestCase):
    def test_universal_check_applies_everywhere(self):
        for runtime in (RUNTIME_LOCAL, RUNTIME_SERVER, RUNTIME_HOSTED):
            context = _context(runtime=runtime, source_checkout=None)
            self.assertIsNone(not_applicable_reason(UNIVERSAL, context))

    def test_source_tree_check_needs_a_checkout(self):
        declaration = CheckApplicability(requires_source_checkout=True)
        reason = not_applicable_reason(
            declaration, _context(runtime=RUNTIME_HOSTED, source_checkout=None),
        )
        self.assertIsNotNone(reason)
        self.assertIn("source tree", reason)
        self.assertIn("acme", reason)

    def test_source_tree_check_runs_where_the_checkout_lives(self):
        declaration = CheckApplicability(requires_source_checkout=True)
        self.assertIsNone(not_applicable_reason(declaration, _context()))

    def test_self_scoped_check_skips_another_project(self):
        declaration = CheckApplicability(project_scope=PROJECT_SCOPE_SELF)
        reason = not_applicable_reason(declaration, _context(project="acme"))
        self.assertIn("owns this Yoke installation", reason)

    def test_self_scoped_check_runs_for_the_self_project(self):
        declaration = CheckApplicability(project_scope=PROJECT_SCOPE_SELF)
        context = _context(project="yoke", self_project="yoke")
        self.assertIsNone(not_applicable_reason(declaration, context))

    def test_self_project_is_resolved_by_binding_not_by_a_literal_slug(self):
        # A renamed self project still matches: the context carries the
        # resolved binding, not a compiled-in name.
        declaration = CheckApplicability(project_scope=PROJECT_SCOPE_SELF)
        context = _context(project="renamed", self_project="renamed")
        self.assertIsNone(not_applicable_reason(declaration, context))

    def test_external_scoped_check_skips_the_self_project(self):
        declaration = CheckApplicability(project_scope=PROJECT_SCOPE_EXTERNAL)
        context = _context(project="yoke", self_project="yoke")
        reason = not_applicable_reason(declaration, context)
        self.assertIn("other than", reason)

    def test_runtime_restriction_names_the_declared_runtimes(self):
        declaration = CheckApplicability(runtimes=frozenset({RUNTIME_LOCAL}))
        reason = not_applicable_reason(
            declaration, _context(runtime=RUNTIME_HOSTED),
        )
        self.assertIn(RUNTIME_LOCAL, reason)
        self.assertIn(RUNTIME_HOSTED, reason)

    def test_missing_capability_is_named(self):
        declaration = CheckApplicability(
            required_capabilities=("migration_model",),
        )
        reason = not_applicable_reason(declaration, _context())
        self.assertIn("migration_model", reason)

    def test_declared_capability_lets_the_check_run(self):
        declaration = CheckApplicability(
            required_capabilities=("migration_model",),
        )
        context = _context(capabilities=frozenset({"migration_model"}))
        self.assertIsNone(not_applicable_reason(declaration, context))

    def test_rejects_an_unknown_project_scope(self):
        with self.assertRaises(ValueError):
            CheckApplicability(project_scope="somewhere")

    def test_rejects_an_unknown_runtime(self):
        with self.assertRaises(ValueError):
            CheckApplicability(runtimes=frozenset({"moon"}))


class TestDeclarationTable(unittest.TestCase):
    def test_every_registered_check_declares_its_applicability(self):
        missing = undeclared_slugs(hc.slug for hc in HEALTH_CHECKS)
        self.assertEqual(missing, [], f"undeclared checks: {missing}")

    def test_a_source_tree_check_is_declared_as_one(self):
        self.assertTrue(
            applicability_for("worktree-health").requires_source_checkout,
        )

    def test_self_project_checks_are_not_in_the_engine_table(self):
        # They live in the project's own .yoke/doctor/ folder and declare on
        # their own rows, so the engine table has nothing to say about them.
        self.assertNotIn("atlas-integrity", DECLARATIONS)
        self.assertNotIn("doc-drift", DECLARATIONS)

    def test_the_pending_migrations_check_answers_everywhere(self):
        # Deliberately the inverse of the check it replaced, which needed a
        # source checkout and a declared migration capability. The history
        # ships in the wheel and the ledger is a table, so "is this database
        # behind its code?" is answerable on a hosted runner that has neither
        # — and a check that self-skipped there would be blind to exactly the
        # installs most likely to drift.
        declaration = applicability_for("pending-migrations")
        self.assertEqual(declaration.required_capabilities, ())
        self.assertFalse(declaration.requires_source_checkout)


class TestNotApplicableReporting(unittest.TestCase):
    def test_not_applicable_is_counted_and_sectioned_separately(self):
        rec = RecordCollector()
        rec.record("HC-a", "Ran", "PASS", "")
        rec.record("HC-b", "Could not run here", NOT_APPLICABLE, "no checkout")
        report = rec.format_report()

        self.assertEqual(rec.pass_count, 1)
        self.assertEqual(rec.na_count, 1)
        self.assertIn("1 checks run: 1 passed", report)
        self.assertIn("1 not applicable", report)
        self.assertIn("## Not Applicable", report)
        self.assertIn("no checkout", report)

    def test_a_clean_run_reports_no_not_applicable_section(self):
        rec = RecordCollector()
        rec.record("HC-a", "Ran", "PASS", "")
        self.assertNotIn("## Not Applicable", rec.format_report())


if __name__ == "__main__":
    unittest.main()
