"""prd_validate — edge cases, measurable patterns, statefulness triggers, CLI.

Split out of ``test_prd_validate.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yoke_core.domain import prd_validate
from yoke_core.domain.prd_validate_test_helpers import (
    COMPLETE_PRD,
    _validate,
    _with_default_acs,
)


class TestEdgeCasesAndTriggers:
    def test_test26_empty_body_handled_gracefully(self) -> None:
        """TEST 26: Empty string body handled gracefully (FAILs PRD-1)."""
        report = _validate("")
        assert "FAIL: PRD-1" in "\n".join(report.failures)

    def test_test28_measurable_patterns_coverage(self) -> None:
        """TEST 28: Measurable pattern list (SLA, KPI, ms, req/s, %, etc.) passes PRD-3/PRD-5."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n"
            "- Reduce latency by 200ms\n"
            "- Increase throughput to 1000 req/s\n"
            "- Automate validation process\n"
            "- Track error rate below 0.1%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n"
            "- Reduce error rate to 0.1% baseline\n"
            "- Meet SLA of 99.9% uptime\n"
            "- KPI target: 50% improvement"
        )
        report = _validate(_with_default_acs(body))
        passed = "\n".join(report.passed)
        assert "PASS: PRD-3" in passed
        assert "PASS: PRD-5" in passed
        assert report.fail_count == 0

    def test_test29_goals_bulleted_but_not_measurable_warns(self) -> None:
        """TEST 29: Goals are bulleted but lack measurable language → WARN PRD-5."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Better user experience\n- Cleaner codebase\n- Faster development\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "WARN: PRD-5" in "\n".join(report.warnings)

    def test_test30_stateful_work_requires_failure_recovery(self) -> None:
        """TEST 30: Deployment language triggers PRD-6 failure when no recovery coverage."""
        body = (
            "## Problem Statement\nProduction deployment currently fails without rollback guidance.\n\n"
            "## Goals\n- Reduce deployment failure confusion by 50%\n\n"
            "## Requirements\n1. FR-1: Deploy the new pipeline to production\n\n"
            "## Success Metrics\n- Reduce failed deployment investigation time by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-6" in "\n".join(report.failures)

    def test_test31_replacement_work_requires_cleanup_and_discovery(self) -> None:
        """TEST 31: Replacement/removal language triggers PRD-7 + PRD-8 failures."""
        body = (
            "## Problem Statement\nThe legacy CLI command should be removed and replaced.\n\n"
            "## Goals\n- Eliminate the legacy command path this sprint\n\n"
            "## Requirements\n"
            "1. FR-1: Remove the old command and replace it with the new entrypoint\n"
            "2. FR-2: Keep user workflows working\n\n"
            "## Success Metrics\n- Zero uses of the legacy command remain"
        )
        report = _validate(_with_default_acs(body))
        failed = "\n".join(report.failures)
        assert "FAIL: PRD-7" in failed
        assert "FAIL: PRD-8" in failed

    def test_test32_stateful_replacement_with_full_coverage_passes(self) -> None:
        """TEST 32: Full coverage (Blast Radius + Cleanup + Failure/Recovery) passes PRD-6/7/8."""
        body = (
            "## Problem Statement\nThe legacy deployment command should be replaced with a safer path.\n\n"
            "## Goals\n- Reduce deployment confusion by 50%\n\n"
            "## Requirements\n1. FR-1: Replace the legacy deployment command\n\n"
            "## Blast Radius\n- Use rg to find all consumers of the legacy command and update every caller.\n\n"
            "## Cleanup and Removal\n- Remove the legacy command, stale docs, old tests, and compatibility shim.\n\n"
            "## Failure and Recovery\n- If deployment fails, leave the old release active and instruct the operator to retry from the previous known-good state.\n\n"
            "## Success Metrics\n"
            "- Zero remaining references to the legacy command\n"
            "- Reduce deployment confusion by 50%"
        )
        report = _validate(_with_default_acs(body))
        passed = "\n".join(report.passed)
        assert "PASS: PRD-6" in passed
        assert "PASS: PRD-7" in passed
        assert "PASS: PRD-8" in passed
        assert report.fail_count == 0


class TestCliSurface:
    """Cover the ``main()`` CLI entrypoint (argparse, usage, exit codes)."""

    def test_test33_no_arguments_shows_usage(self) -> None:
        """TEST 33: Calling main with no body/item ref exits 2 with usage message."""
        env = os.environ.copy()
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.prd_validate"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert "Usage" in combined

    def test_main_body_text_complete_prd_exits_zero(self) -> None:
        """Calling main with --body-text COMPLETE_PRD exits 0."""
        try:
            prd_validate.main(["--body-text", COMPLETE_PRD])
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("main() must call sys.exit")

    def test_main_body_text_failing_body_exits_one(self) -> None:
        """Calling main with a body that fails PRD-1 exits 1."""
        try:
            prd_validate.main(["--body-text", "Just plain text with no headings."])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("main() must call sys.exit")
