"""Tests for HC-terminal-recipe-residue.

Covers AC-14.4 (banned-literal list keyed off
RECIPE_RESIDUE_PATTERNS), AC-14.6 (fixture-based regression guard),
AC-14.7 (registry-aware second pass), and the allowlist contract
(docs/archive/**, docs/db-reference/**, runtime/api/**/test_*.py).
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.engines import doctor_hc_terminal_recipe_residue as hc
from yoke_core.engines.doctor_hc_terminal_recipe_residue_scan import (
    iter_scan_paths,
    path_in_allowlist,
    registry_choreography_findings,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# Path to the bundled fixture under runtime/api/engines/test_fixtures/.
_FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "test_fixtures"
    / "doctor_hc_terminal_recipe_residue"
)


def _make_args() -> DoctorArgs:
    return DoctorArgs(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="yoke",
        db_path=":memory:",
    )


def _copy_fixture_into(tmp_root: Path) -> None:
    """Copy the bundled fixture into a temporary scan root."""
    dest = tmp_root / "AGENTS.md"
    src = _FIXTURE_DIR / "AGENTS.md"
    shutil.copy2(src, dest)


class TestRecipeResidueScan(unittest.TestCase):
    """AC-14.4 + AC-14.6: banned-literal residue scan."""

    def test_fixture_flagged_outside_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _copy_fixture_into(tmp)
            findings = hc._scan_recipe_residue(tmp)
        self.assertTrue(findings, "fixture should produce banned-literal findings")
        # At least one of the recipe-residue substrings shows up in findings.
        joined = "\n".join(findings)
        self.assertIn("AGENTS.md", joined)

    def test_no_findings_in_clean_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "AGENTS.md").write_text(
                "# clean guidance\n\nNo banned recipes here.\n",
                encoding="utf-8",
            )
            findings = hc._scan_recipe_residue(tmp)
        self.assertFalse(findings)

    def test_findings_skipped_under_docs_archive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            archive = tmp / "docs" / "archive"
            archive.mkdir(parents=True)
            (archive / "decision.md").write_text(
                "Historical reference: sqlite3 data/yoke.db is retired.\n",
                encoding="utf-8",
            )
            findings = hc._scan_recipe_residue(tmp)
        self.assertFalse(findings, "docs/archive/** is allowlisted")

    def test_findings_skipped_under_docs_db_reference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ref = tmp / "docs" / "db-reference"
            ref.mkdir(parents=True)
            (ref / "cli.md").write_text(
                "Operator example: sqlite3 data/yoke.db 'SELECT *...'\n",
                encoding="utf-8",
            )
            findings = hc._scan_recipe_residue(tmp)
        self.assertFalse(findings, "docs/db-reference/** is allowlisted")


class TestRegistryChoreographyScan(unittest.TestCase):
    """AC-14.7 + AC-14.8 + AC-14.9: registry-aware second pass."""

    def test_fixture_flagged_for_function_covered_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _copy_fixture_into(tmp)
            findings = registry_choreography_findings(
                tmp,
                allowlist=("docs/archive/", "docs/db-reference/"),
                test_file_re=re.compile(r"runtime/api/.*test_.*\.py$"),
            )
        # Fixture contains a mutating adapter wrapped in command capture.
        self.assertTrue(findings)
        joined = "\n".join(findings)
        self.assertIn("function-covered recipe", joined)
        self.assertIn("yoke_core.cli.db_router", joined)

    def test_clean_invocation_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Bare adapter call without shell choreography is fine.
            (tmp / "AGENTS.md").write_text(
                "# clean docs\n\n"
                "Run `python3 -m yoke_core.cli.db_router items get YOK-N spec` "
                "to read the spec.\n",
                encoding="utf-8",
            )
            findings = registry_choreography_findings(
                tmp,
                allowlist=("docs/archive/", "docs/db-reference/"),
                test_file_re=re.compile(r"runtime/api/.*test_.*\.py$"),
            )
        self.assertFalse(findings)

    def test_read_shape_capture_not_flagged(self) -> None:
        # `read_shape=True` adapter captured in $() is a legit read pattern.
        # Witness: `projects.get` (added by YOK-1753, the regression that
        # exposed the hand-maintained allowlist drift).
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "AGENTS.md").write_text(
                "# guidance\n\n"
                '_repo=$(python3 -m yoke_core.cli.db_router projects get '
                '"$_item_project" repo_path)\n',
                encoding="utf-8",
            )
            findings = registry_choreography_findings(
                tmp,
                allowlist=("docs/archive/", "docs/db-reference/"),
                test_file_re=re.compile(r"runtime/api/.*test_.*\.py$"),
            )
        self.assertFalse(findings, findings)

    def test_readonly_set_derives_from_inventory(self) -> None:
        from yoke_core.engines.doctor_hc_terminal_recipe_residue_scan import (
            _READONLY_FUNCTION_IDS,
        )
        from yoke_core.api.service_client_structured_api_adapter_inventory import (
            CLI_ADAPTERS,
        )
        from yoke_core.api.service_client_structured_api_adapter_inventory_taught import (  # noqa: E501
            TAUGHT_ADAPTERS,
        )
        expected = {
            e.function_id
            for e in (*CLI_ADAPTERS, *TAUGHT_ADAPTERS)
            if e.read_shape
        }
        self.assertEqual(_READONLY_FUNCTION_IDS, frozenset(expected))
        # Every adapter the scanner historically allowlisted by literal
        # must remain covered via inventory derivation.
        legacy_allowlist = {
            "claims.work.holder_get",
            "claims.work.holder_list",
            "items.get.run",
            "items.section.get",
            "epic_tasks.list.run",
            "events.query.run",
            "path_claims.conflicts.list",
            "doctor.run.run",
            "projects.capability.has",
            "packets.check.run",
            "agents.render.check",
        }
        self.assertTrue(legacy_allowlist <= _READONLY_FUNCTION_IDS)


class TestIterScanPaths(unittest.TestCase):
    """Scan iterator covers the canonical guidance surfaces."""

    def test_root_files_yielded_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "AGENTS.md").write_text("hi\n", encoding="utf-8")
            (tmp / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
            paths = {p.name for p in iter_scan_paths(tmp)}
        self.assertIn("AGENTS.md", paths)
        self.assertIn("CLAUDE.md", paths)

    def test_directory_files_yielded_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "docs").mkdir()
            (tmp / "docs" / "lifecycle.md").write_text("hi\n", encoding="utf-8")
            paths = {p.name for p in iter_scan_paths(tmp)}
        self.assertIn("lifecycle.md", paths)


class TestPathInAllowlist(unittest.TestCase):
    def test_match(self) -> None:
        self.assertTrue(
            path_in_allowlist("docs/archive/decisions/x.md", ("docs/archive/",))
        )

    def test_no_match(self) -> None:
        self.assertFalse(
            path_in_allowlist("docs/lifecycle.md", ("docs/archive/",))
        )

    def test_empty(self) -> None:
        self.assertFalse(path_in_allowlist("anything", ()))


class TestHcFullRun(unittest.TestCase):
    """End-to-end HC run against a synthetic repo root."""

    def test_hc_fails_closed_on_fixture(self) -> None:
        rec = RecordCollector()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _copy_fixture_into(tmp)
            with mock.patch(
                "yoke_core.engines.doctor_hc_terminal_recipe_residue."
                "_resolve_repo_root",
                return_value=str(tmp),
            ):
                hc.hc_terminal_recipe_residue(None, _make_args(), rec)
        # Look up the recorded result.
        matching = [r for r in rec.results if r.check_id == "HC-terminal-recipe-residue"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].result, "FAIL")
        self.assertIn("Retired terminal-soup recipes", matching[0].detail)

    def test_hc_passes_on_clean_root(self) -> None:
        rec = RecordCollector()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "AGENTS.md").write_text(
                "# clean guidance\n\nNo banned recipes.\n", encoding="utf-8",
            )
            with mock.patch(
                "yoke_core.engines.doctor_hc_terminal_recipe_residue."
                "_resolve_repo_root",
                return_value=str(tmp),
            ):
                hc.hc_terminal_recipe_residue(None, _make_args(), rec)
        matching = [r for r in rec.results if r.check_id == "HC-terminal-recipe-residue"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].result, "PASS")

    def test_hc_skips_when_no_repo_root(self) -> None:
        rec = RecordCollector()
        with mock.patch(
            "yoke_core.engines.doctor_hc_terminal_recipe_residue."
            "_resolve_repo_root",
            return_value="",
        ):
            hc.hc_terminal_recipe_residue(None, _make_args(), rec)
        matching = [r for r in rec.results if r.check_id == "HC-terminal-recipe-residue"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].result, "PASS")


if __name__ == "__main__":
    unittest.main()
