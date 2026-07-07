"""Tests for HC-historical-yok-n-cruft.

Covers the generated-output exemption: ``docs/archive/legacy-plan-artifacts/**`` and the
rendered harness agent adapters under ``runtime/harness/{claude,codex}/agents/``
are dropped at the HC record layer (their YOK-N tokens are snapshot/rendered
content, not authored provenance), while live tracked-source cruft — the HC's
real job — is still flagged. Also confirms the HC self-skips cleanly when no
repo root resolves and when the DB lacks an ``items`` table (minimal schema).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.engines import doctor_hc_historical_yok_n as hc
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

_CHECK_ID = "HC-historical-yok-n-cruft"
_DONE_TICKET = "YOK-100"


def _make_args(db_path: str) -> DoctorArgs:
    return DoctorArgs(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="yoke",
        db_path=db_path,
    )


def _seed_db_with_done_ticket(path: str) -> None:
    """Mark the witness ticket ``done`` in the ambient ``items`` table."""
    del path  # ambient Postgres authority; compatibility slot only
    conn = db_backend.connect()
    now = iso8601_now()
    try:
        conn.execute("DELETE FROM items WHERE id = %s", (100,))
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, created_at, updated_at,
                project_id, project_sequence)
               VALUES (%s, %s, 'issue', %s, 'medium', %s, %s, 1, %s)""",
            (100, "Historical cruft witness", "done", now, now, 100),
        )
        conn.commit()
    finally:
        conn.close()


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _run_hc(root: Path, db_path: str) -> RecordCollector:
    rec = RecordCollector()
    with mock.patch.object(hc, "_resolve_repo_root", return_value=str(root)):
        hc.hc_historical_yok_n_cruft(None, _make_args(db_path), rec)
    return rec


def _only_result(rec: RecordCollector):
    matching = [r for r in rec.results if r.check_id == _CHECK_ID]
    assert len(matching) == 1, matching
    return matching[0]


class TestGeneratedOutputExemption(unittest.TestCase):
    def test_live_source_flagged_generated_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = str(root / "lint.db")
            _seed_db_with_done_ticket(db_path)
            # Live tracked source — must still be flagged.
            _write(root, "docs/lifecycle-note.md", f"Historical note: implemented in {_DONE_TICKET}.\n")
            _write(root, "runtime/api/widget.py", f"# implemented in {_DONE_TICKET}\n")
            # Generated outputs — must be exempt.
            _write(root, "docs/archive/legacy-plan-artifacts/spec-history/snap.md", f"Snapshot mentions {_DONE_TICKET}.\n")
            _write(root, "runtime/harness/claude/agents/yoke-architect.md", f"Recipe: items get {_DONE_TICKET} spec.\n")
            rec = _run_hc(root, db_path)

        result = _only_result(rec)
        self.assertEqual(result.result, "WARN")
        # Live source surfaces are named.
        self.assertIn("docs/lifecycle-note.md", result.detail)
        self.assertIn("runtime/api/widget.py", result.detail)
        # Generated trees are suppressed.
        self.assertNotIn("legacy-plan-artifacts", result.detail)
        self.assertNotIn("harness/claude/agents", result.detail)

    def test_all_generated_yields_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = str(root / "lint.db")
            _seed_db_with_done_ticket(db_path)
            _write(root, "docs/archive/legacy-plan-artifacts/evidence.md", f"Mentions {_DONE_TICKET}.\n")
            _write(root, "runtime/harness/codex/agents/yoke-boss.md", f"Mentions {_DONE_TICKET}.\n")
            rec = _run_hc(root, db_path)

        result = _only_result(rec)
        self.assertEqual(result.result, "PASS", result.detail)

    def test_only_live_source_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = str(root / "lint.db")
            _seed_db_with_done_ticket(db_path)
            _write(root, "docs/lifecycle-note.md", f"Implemented in {_DONE_TICKET}.\n")
            rec = _run_hc(root, db_path)

        result = _only_result(rec)
        self.assertEqual(result.result, "WARN")
        self.assertIn("docs/lifecycle-note.md", result.detail)


class TestSelfSkip(unittest.TestCase):
    def test_skips_when_no_repo_root(self) -> None:
        rec = RecordCollector()
        with mock.patch.object(hc, "_resolve_repo_root", return_value=""):
            hc.hc_historical_yok_n_cruft(None, _make_args("unused"), rec)
        result = _only_result(rec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("No repo root resolved", result.detail)

    def test_self_skips_on_minimal_schema(self) -> None:
        # DB has no ``items`` table: every ticket resolves 'unknown', so the HC
        # cannot classify any reference as done-and-cruft → clean PASS, no crash.
        from runtime.api.fixtures import pg_testdb

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "docs/lifecycle-note.md", f"Mentions {_DONE_TICKET}.\n")
            name = pg_testdb.create_test_database()
            prior = os.environ.get(db_backend.PG_DSN_ENV)
            os.environ[db_backend.PG_DSN_ENV] = pg_testdb.dsn_for_test_database(name)
            try:
                rec = _run_hc(root, db_path="minimal")
            finally:
                if prior is not None:
                    os.environ[db_backend.PG_DSN_ENV] = prior
                else:
                    os.environ.pop(db_backend.PG_DSN_ENV, None)
                pg_testdb.drop_test_database(name)

        result = _only_result(rec)
        self.assertEqual(result.result, "PASS", result.detail)


class TestIsGeneratedOutputPath(unittest.TestCase):
    def test_exact_root_matches(self) -> None:
        self.assertTrue(hc._is_generated_output_path("docs/archive/legacy-plan-artifacts"))

    def test_nested_under_root_matches(self) -> None:
        self.assertTrue(
            hc._is_generated_output_path("docs/archive/legacy-plan-artifacts/atlas-boundary-inventory/x.md")
        )
        self.assertTrue(
            hc._is_generated_output_path("runtime/harness/claude/agents/yoke-x.md")
        )
        self.assertTrue(
            hc._is_generated_output_path("runtime/harness/codex/agents/yoke-x.toml")
        )

    def test_live_source_does_not_match(self) -> None:
        self.assertFalse(hc._is_generated_output_path("docs/lifecycle.md"))
        self.assertFalse(hc._is_generated_output_path("runtime/api/widget.py"))
        self.assertFalse(
            hc._is_generated_output_path("runtime/agents/architect.md")
        )

    def test_prefix_lookalike_does_not_match(self) -> None:
        # A sibling directory that merely shares the root's name prefix is not
        # under the exempt root and must still be scanned.
        self.assertFalse(
            hc._is_generated_output_path("docs/archive/legacy-plan-artifacts-notes/x.md")
        )


if __name__ == "__main__":
    unittest.main()
