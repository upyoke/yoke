"""A project's own ``.yoke/doctor/`` folder contributes checks to a run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    DoctorContext,
    NOT_APPLICABLE,
    PROJECT_SCOPE_SELF,
    RUNTIME_HOSTED,
    RUNTIME_LOCAL,
)
from yoke_core.engines.doctor_project_checks import (
    Discovery,
    discover_project_checks,
    project_checks_dir,
    register_project_checks_package,
)
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_roster import (
    build_roster,
    record_discovery_failures,
    record_not_applicable,
    record_roster_collisions,
)


CONVENTION_MODULE = '''
from yoke_core.engines.doctor_applicability import (
    CheckApplicability, PROJECT_SCOPE_SELF,
)

APPLICABILITY = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF, requires_source_checkout=True,
)


def hc_release_pin_freshness(conn, args, rec):
    """Release pin matches the built artifact."""
    rec.record(
        "HC-release-pin-freshness",
        "Release pin matches the built artifact",
        "PASS",
        "",
    )


def helper_not_collected(conn, args, rec):
    raise AssertionError("only hc_* functions are collected")
'''

EXPLICIT_MODULE = '''
from yoke_core.engines.doctor_applicability import CheckApplicability
from yoke_core.engines.doctor_registry_types import HealthCheck


def _run(conn, args, rec):
    rec.record("HC-explicit", "Explicit row", "PASS", "")


PROJECT_HEALTH_CHECKS = [
    HealthCheck(
        slug="explicit",
        name="Explicit row",
        fn=_run,
        applicability=CheckApplicability(requires_source_checkout=True),
    ),
]
'''

# A self-project check legitimately inspects the engine roster. Importing it
# by name must not make the whole engine roster read as this project's own
# declaration — which is exactly what a shared attribute name would do.
INSPECTS_ENGINE_ROSTER_MODULE = '''
from yoke_core.engines.doctor_registry import HEALTH_CHECKS


def hc_roster_size(conn, args, rec):
    """Engine roster is non-empty."""
    rec.record("HC-roster-size", "Engine roster is non-empty", "PASS", "")
'''

BROKEN_MODULE = "import a_module_that_does_not_exist\n"


def _write_project_checks(root: Path, files: dict) -> None:
    folder = project_checks_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (folder / name).write_text(body, encoding="utf-8")


class TestProjectCheckDiscovery(unittest.TestCase):
    def test_no_folder_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            discovery = discover_project_checks(Path(tmp))
            self.assertEqual(discovery.checks, [])
            self.assertEqual(discovery.failures, [])

    def test_no_checkout_yields_nothing(self):
        discovery = discover_project_checks(None)
        self.assertEqual(discovery.checks, [])

    def test_collects_hc_functions_by_convention(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_project_checks(
                Path(tmp),
                {
                    "check_release.py": CONVENTION_MODULE,
                    "shared_helpers.py": "raise AssertionError('not imported')",
                    "README.md": "not a module",
                },
            )
            discovery = discover_project_checks(Path(tmp))

        self.assertEqual(discovery.failures, [])
        self.assertEqual(
            [hc.slug for hc in discovery.checks], ["release-pin-freshness"],
        )
        check = discovery.checks[0]
        self.assertEqual(check.name, "Release pin matches the built artifact.")
        self.assertEqual(check.applicability.project_scope, PROJECT_SCOPE_SELF)

    def test_collects_an_explicit_health_checks_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_project_checks(Path(tmp), {"check_x.py": EXPLICIT_MODULE})
            discovery = discover_project_checks(Path(tmp))

        self.assertEqual([hc.slug for hc in discovery.checks], ["explicit"])
        self.assertTrue(discovery.checks[0].applicability.requires_source_checkout)

    def test_one_file_keeps_one_module_object_across_discoveries(self):
        # A caller holding a reference — a test that patched a helper, a
        # paginating run between chunks — must not find its module swapped
        # out underneath it by the next discovery of the same folder.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project_checks(root, {"check_release.py": CONVENTION_MODULE})
            first = discover_project_checks(root).checks[0]
            second = discover_project_checks(root).checks[0]

        self.assertIs(first.fn.__globals__, second.fn.__globals__)

    def test_registering_a_second_folder_keeps_the_first_importable(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            _write_project_checks(Path(one), {"check_release.py": CONVENTION_MODULE})
            _write_project_checks(Path(two), {"check_x.py": EXPLICIT_MODULE})
            register_project_checks_package(project_checks_dir(Path(one)))
            register_project_checks_package(project_checks_dir(Path(two)))
            import sys

            package = sys.modules["yoke_project_checks"]
            self.assertIn(str(project_checks_dir(Path(one))), package.__path__)
            self.assertIn(str(project_checks_dir(Path(two))), package.__path__)

    def test_importing_the_engine_roster_declares_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_project_checks(
                Path(tmp), {"check_roster.py": INSPECTS_ENGINE_ROSTER_MODULE},
            )
            discovery = discover_project_checks(Path(tmp))

        self.assertEqual(discovery.failures, [])
        self.assertEqual([hc.slug for hc in discovery.checks], ["roster-size"])

    def test_an_unimportable_module_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_project_checks(Path(tmp), {"check_broken.py": BROKEN_MODULE})
            discovery = discover_project_checks(Path(tmp))

        self.assertEqual(discovery.checks, [])
        self.assertEqual(len(discovery.failures), 1)
        self.assertIn("a_module_that_does_not_exist", discovery.failures[0].error)

        rec = RecordCollector()
        roster_stub = type("R", (), {"discovery_failures": discovery.failures})()
        record_discovery_failures(roster_stub, rec)
        self.assertEqual(rec.fail_count, 1)


class TestRosterIntegration(unittest.TestCase):
    def _args(self) -> DoctorArgs:
        return DoctorArgs(quick=True, project="yoke")

    def test_project_checks_join_the_roster_when_the_checkout_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project_checks(root, {"check_release.py": CONVENTION_MODULE})
            context = DoctorContext(
                project="yoke",
                runtime=RUNTIME_LOCAL,
                self_project="yoke",
                source_checkout=root,
            )
            roster = build_roster([], self._args(), context)

        self.assertEqual(roster.slugs, ["release-pin-freshness"])
        self.assertEqual(roster.known_slugs, {"release-pin-freshness"})

    def test_a_duplicate_slug_is_reported_and_neither_declaration_runs(self):
        engine_check = HealthCheck(
            slug="shared", name="Engine declaration",
            fn=lambda conn, args, rec: None,
        )
        project_check = HealthCheck(
            slug="shared", name="Project declaration",
            fn=lambda conn, args, rec: None,
        )
        context = DoctorContext(
            project="yoke",
            runtime=RUNTIME_LOCAL,
            self_project="yoke",
            source_checkout=Path("/target/yoke"),
        )

        with patch(
            "yoke_core.engines.doctor_roster.discover_project_checks",
            return_value=Discovery([project_check], []),
        ):
            roster = build_roster([engine_check], self._args(), context)

        self.assertEqual(roster.known_slugs, {"shared"})
        self.assertEqual(roster.applicable, [])
        self.assertEqual(roster.not_applicable, [])
        self.assertEqual([c.slug for c in roster.collisions], ["shared"])

        rec = RecordCollector()
        record_roster_collisions(roster, rec)
        self.assertEqual(rec.fail_count, 1)
        self.assertIn("no declaration ran", rec.results[0].detail)

    def test_a_runner_without_the_checkout_discovers_nothing(self):
        context = DoctorContext(
            project="yoke",
            runtime=RUNTIME_HOSTED,
            self_project=None,
            source_checkout=None,
        )
        roster = build_roster([], self._args(), context)
        self.assertEqual(roster.applicable, [])
        self.assertEqual(roster.not_applicable, [])

    def test_out_of_scope_engine_checks_are_recorded_with_their_reason(self):
        checks = [
            HealthCheck(
                slug="needs-source",
                name="Needs source",
                fn=lambda conn, args, rec: None,
                applicability=CheckApplicability(requires_source_checkout=True),
            ),
            HealthCheck(
                slug="db-only",
                name="DB only",
                fn=lambda conn, args, rec: None,
                applicability=CheckApplicability(),
            ),
        ]
        context = DoctorContext(
            project="yoke",
            runtime=RUNTIME_HOSTED,
            self_project=None,
            source_checkout=None,
        )
        roster = build_roster(checks, self._args(), context)
        rec = RecordCollector()
        record_not_applicable(roster, rec)

        self.assertEqual(roster.slugs, ["db-only"])
        self.assertEqual(rec.na_count, 1)
        self.assertEqual(rec.results[0].check_id, "HC-needs-source")
        self.assertEqual(rec.results[0].result, NOT_APPLICABLE)
        self.assertIn("source tree", rec.results[0].detail)


class TestThisProjectsOwnCheckFolder(unittest.TestCase):
    """Discovery over the real ``.yoke/doctor/`` tree this repo ships.

    The synthetic-folder tests above prove the mechanism; this one proves
    the checks actually in the tree satisfy it. A module whose filename,
    declaration, or imports are wrong is otherwise only discovered when
    someone runs the doctor.
    """

    def _checkout(self) -> Path:
        # This file lives at <checkout>/runtime/api/engines/, so the
        # checkout is three parents up — resolved from the test's own
        # location rather than a cwd that varies per runner.
        return Path(__file__).resolve().parents[3]

    def test_every_check_module_loads_and_declares(self):
        checkout = self._checkout()
        folder = project_checks_dir(checkout)
        if not folder.is_dir():
            self.skipTest("no project check folder in this checkout")
        modules = sorted(folder.glob("check_*.py"))
        self.assertTrue(modules, "expected at least one project check module")

        discovery = discover_project_checks(checkout)

        self.assertEqual(
            [(f.module, f.error) for f in discovery.failures], [],
            "every project check module must import cleanly",
        )
        # Each module contributes at least one check, so a module that
        # silently declares nothing (misnamed function, missing
        # PROJECT_HEALTH_CHECKS) is caught rather than passing as clean.
        self.assertGreaterEqual(len(discovery.checks), len(modules))

    def test_declared_slugs_are_unique(self):
        checkout = self._checkout()
        if not project_checks_dir(checkout).is_dir():
            self.skipTest("no project check folder in this checkout")
        slugs = [check.slug for check in discover_project_checks(checkout).checks]
        self.assertEqual(sorted(slugs), sorted(set(slugs)))


if __name__ == "__main__":
    unittest.main()
