"""CLI coverage for ``yoke_core.engines.doctor``.

Focused on the ``--json`` adapter: explicit scope
enforcement, JSON shape parity with ``doctor.run.run``, structured
invalid-check error, and no orphan watcher / tail subprocess survivors
when scope validation fails. Sibling per-HC test modules
(``test_doctor_hc_*``) cover the human report path; this file owns the
JSON adapter contract.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

# Make the worktree's runtime package importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER
from yoke_core.engines import doctor as doctor_engine
from yoke_core.engines.doctor_registry_types import HealthCheck


def _fake_pass_hc(conn, args, rec):
    rec.record("HC-fake", "Fake HC", "PASS", "all good")


def _fake_fail_hc(conn, args, rec):
    rec.record("HC-fail-hc", "Failing HC", "FAIL", "synthetic failure")


def _fake_foo_pass_hc(conn, args, rec):
    rec.record("HC-foo", "Foo HC", "PASS", "ok")


def _fake_bar_warn_hc(conn, args, rec):
    rec.record("HC-bar", "Bar HC", "WARN", "needs attention")


class _StubConn:
    def close(self):
        pass


class _StreamingProgressTests(unittest.TestCase):
    """``run_checks`` emits per-HC start and terminal-status lines."""

    def test_per_hc_lines_precede_final_report(self):
        # `run_checks` iterates the star-imported binding in
        # `yoke_core.engines.doctor`, not the registry module's copy.
        with patch(
            "yoke_core.engines.doctor.HEALTH_CHECKS",
            [
                HealthCheck(slug="foo", name="Foo HC", fn=_fake_foo_pass_hc),
                HealthCheck(slug="bar", name="Bar HC", fn=_fake_bar_warn_hc),
            ],
        ):
            with patch(
                "yoke_core.engines.doctor._should_run_hc", return_value=True,
            ):
                with patch(
                    "yoke_core.engines.doctor.connect", return_value=_StubConn(),
                ):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = doctor_engine.run_checks(
                            doctor_engine.DoctorArgs(quick=True, project="yoke")
                        )
        output = buf.getvalue()
        report_idx = output.index("# Ouroboros Health Report")
        before_report = output[:report_idx]
        # All four streaming lines appear before the aggregated report.
        for expected in (
            "running HC-foo",
            "HC-foo: PASS",
            "running HC-bar",
            "HC-bar: WARN",
        ):
            self.assertIn(expected, before_report)
        # Ordering: start line comes before its own terminal-status line.
        self.assertLess(
            before_report.index("running HC-foo"),
            before_report.index("HC-foo: PASS"),
        )
        self.assertLess(
            before_report.index("HC-foo: PASS"),
            before_report.index("running HC-bar"),
        )
        # Aggregated report content is preserved (rc=0 because no FAILs).
        self.assertEqual(rc, 0)
        self.assertIn("2 checks run", output)

    def test_file_output_contains_aggregated_report_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "doctor-report.md"
            with patch(
                "yoke_core.engines.doctor.HEALTH_CHECKS",
                [HealthCheck(slug="foo", name="Foo HC", fn=_fake_foo_pass_hc)],
            ):
                with patch(
                    "yoke_core.engines.doctor._should_run_hc", return_value=True,
                ):
                    with patch(
                        "yoke_core.engines.doctor.connect",
                        return_value=_StubConn(),
                    ):
                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            rc = doctor_engine.run_checks(
                                doctor_engine.DoctorArgs(
                                    quick=True,
                                    project="yoke",
                                    file=str(report_path),
                                )
                            )

            output = buf.getvalue()
            report_idx = output.index("# Ouroboros Health Report")
            saved_idx = output.index("\nReport saved to:")
            report_from_stdout = output[report_idx:saved_idx].rstrip("\n")
            file_report = report_path.read_text(encoding="utf-8")

            self.assertEqual(rc, 0)
            self.assertEqual(file_report, report_from_stdout)
            self.assertNotIn("running HC-foo", file_report)
            self.assertNotIn("HC-foo: PASS", file_report)


class _JsonAdapterTests(unittest.TestCase):
    """``python3 -m yoke_core.engines.doctor --json`` adapter."""

    @classmethod
    def setUpClass(cls):
        # Make sure handlers are registered before dispatching.
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers

        register_all_handlers()

    def test_json_requires_explicit_scope(self):
        # --json without --quick / --full / --only / --list-checks
        # must error out (argparse exits 2), preventing silent gh-quota
        # burn. SystemExit(2) is the documented contract.
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stderr(io.StringIO()):
                doctor_engine.main(["--json"])
        self.assertEqual(ctx.exception.code, 2)

    def test_json_quick_emits_structured_envelope(self):
        # --json must emit the dispatcher response envelope.
        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS",
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_pass_hc)],
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_StubConn(),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = doctor_engine.main(["--json", "--quick"])
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["success"], payload)
        self.assertEqual(payload["function"], "doctor.run.run")
        self.assertEqual(payload["result"]["scope"], "quick")
        self.assertEqual(payload["result"]["fail_count"], 0)
        self.assertEqual(rc, 0)

    def test_json_returns_invalid_check_for_unknown_slug(self):
        # A bad slug surfaces the structured error envelope.
        # No HCs run, so no watcher / tail processes can leak.
        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS",
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_pass_hc)],
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_StubConn(),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = doctor_engine.main([
                        "--json",
                        "--only",
                        "HC-this-check-does-not-exist",
                    ])
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "invalid_check")
        # Engine exits 1 on a structured error so shell scripts can
        # branch on success without parsing JSON.
        self.assertEqual(rc, 1)

    def test_json_full_with_failing_hc_exits_one(self):
        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS",
            [
                HealthCheck(slug="fake", name="Fake HC", fn=_fake_pass_hc),
                HealthCheck(
                    slug="fail-hc", name="Failing HC", fn=_fake_fail_hc,
                ),
            ],
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_StubConn(),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = doctor_engine.main(["--json", "--full"])
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["result"]["fail_count"], 1)
        self.assertEqual(rc, 1)


class _RemediationFooterTests(unittest.TestCase):
    """AC-14: every HC remediation prompt in the Markdown report ends with
    the field-note footer. Applied at the doctor result-render layer
    so per-HC modules need no edits."""

    def test_remediation_with_footer_appends_when_absent(self):
        wrapped = doctor_engine.remediation_with_footer("fix the column drift")
        self.assertTrue(wrapped.startswith("fix the column drift"))
        self.assertTrue(wrapped.endswith(FIELD_NOTE_FOOTER))

    def test_remediation_with_footer_is_idempotent(self):
        once = doctor_engine.remediation_with_footer("first prompt")
        twice = doctor_engine.remediation_with_footer(once)
        # Re-wrapping must not double-append; the second call sees the
        # footer already present and returns the input unchanged.
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(FIELD_NOTE_FOOTER), 1)

    def test_fail_detail_in_rendered_report_carries_footer(self):
        with patch(
            "yoke_core.engines.doctor.HEALTH_CHECKS",
            [HealthCheck(slug="fail-hc", name="Failing HC", fn=_fake_fail_hc)],
        ):
            with patch(
                "yoke_core.engines.doctor._should_run_hc", return_value=True,
            ):
                with patch(
                    "yoke_core.engines.doctor.connect", return_value=_StubConn(),
                ):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = doctor_engine.run_checks(
                            doctor_engine.DoctorArgs(quick=True, project="yoke")
                        )
        output = buf.getvalue()
        self.assertEqual(rc, 1)
        # The FAIL section's detail block in the Markdown report carries
        # the footer right after the synthetic failure prompt.
        self.assertIn("synthetic failure", output)
        self.assertIn(FIELD_NOTE_FOOTER, output)

    def test_warn_detail_in_rendered_report_carries_footer(self):
        with patch(
            "yoke_core.engines.doctor.HEALTH_CHECKS",
            [HealthCheck(slug="bar", name="Bar HC", fn=_fake_bar_warn_hc)],
        ):
            with patch(
                "yoke_core.engines.doctor._should_run_hc", return_value=True,
            ):
                with patch(
                    "yoke_core.engines.doctor.connect", return_value=_StubConn(),
                ):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        doctor_engine.run_checks(
                            doctor_engine.DoctorArgs(quick=True, project="yoke")
                        )
        output = buf.getvalue()
        # WARN section detail carries the footer too.
        self.assertIn("needs attention", output)
        self.assertIn(FIELD_NOTE_FOOTER, output)

    def test_pass_results_do_not_carry_footer(self):
        # PASS entries are diagnostics, not remediation prompts. Adding the
        # footer to every passing line would dilute the channel — the footer
        # belongs only on actionable FAIL / WARN remediation text.
        with patch(
            "yoke_core.engines.doctor.HEALTH_CHECKS",
            [HealthCheck(slug="foo", name="Foo HC", fn=_fake_foo_pass_hc)],
        ):
            with patch(
                "yoke_core.engines.doctor._should_run_hc", return_value=True,
            ):
                with patch(
                    "yoke_core.engines.doctor.connect", return_value=_StubConn(),
                ):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        doctor_engine.run_checks(
                            doctor_engine.DoctorArgs(quick=True, project="yoke")
                        )
        output = buf.getvalue()
        # Pass-only run: footer must NOT show up in the rendered report
        # (we slice after the streaming-progress lines).
        report_idx = output.index("# Ouroboros Health Report")
        self.assertNotIn(FIELD_NOTE_FOOTER, output[report_idx:])


class _CliExplicitScopePreservedTests(unittest.TestCase):
    """Existing human-CLI guard must continue to refuse no-scope calls."""

    def test_human_cli_still_requires_scope(self):
        # The pre-existing hotfix behavior is unchanged: a bare invocation
        # exits 2. Defends against the regression of "JSON path adds a
        # default scope at the human CLI too."
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stderr(io.StringIO()):
                doctor_engine.main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
