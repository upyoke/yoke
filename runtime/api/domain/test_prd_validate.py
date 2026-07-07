"""Tests for ``yoke_core.domain.prd_validate`` — PRD-1..5 structural checks.

Original module covered every flavor of prd_validate. It is now split across
sibling files so each authored file stays under the 350-line limit:
heading variations + strict mode + DB-backed resolution live in
``test_prd_validate_variations``; edge-case triggers (PRD-6/7/8) and the CLI
surface live in ``test_prd_validate_triggers``. Heavy fixture/helper code
lives in ``prd_validate_test_helpers``.

TEST-N / PRD-N method name mapping is preserved for traceability.
"""

from __future__ import annotations

from yoke_core.domain.prd_validate_test_helpers import (
    COMPLETE_PRD,
    _validate,
    _with_default_acs,
)


class TestCompletePRD:
    def test_test1_complete_prd_passes_all_checks(self) -> None:
        """TEST 1: Complete PRD passes PRD-1..PRD-9 with 9 passed / 0 failures."""
        report = _validate(COMPLETE_PRD)
        assert report.fail_count == 0
        assert report.pass_count == 9
        # Every PRD-N should appear in passed list.
        passed_ids = "\n".join(report.passed)
        for prd in ("PRD-1", "PRD-2", "PRD-3", "PRD-4", "PRD-5", "PRD-9"):
            assert f"PASS: {prd}" in passed_ids

    def test_test2_empty_body_fails_structural_checks(self) -> None:
        """TEST 2: Body with no headings fails PRD-1, PRD-2, PRD-3, PRD-5 (+ PRD-9)."""
        report = _validate("Just some random text with no markdown headings.")
        assert report.fail_count == 5
        failed = "\n".join(report.failures)
        for prd in ("PRD-1", "PRD-2", "PRD-3", "PRD-5", "PRD-9"):
            assert f"FAIL: {prd}" in failed


class TestPRD1ProblemStatement:
    def test_test3_missing_problem_statement_fails(self) -> None:
        """TEST 3: Missing Problem Statement fails PRD-1."""
        body = (
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        failed = "\n".join(report.failures)
        assert "FAIL: PRD-1" in failed
        assert "Problem Statement" in failed

    def test_test4_too_brief_problem_statement_fails(self) -> None:
        """TEST 4: Problem Statement <20 chars fails PRD-1 with 'too brief' detail."""
        body = (
            "## Problem Statement\nShort.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        failed = "\n".join(report.failures)
        assert "FAIL: PRD-1" in failed
        assert "too brief" in failed

    def test_test5_empty_problem_statement_section_fails(self) -> None:
        """TEST 5: Empty Problem Statement section fails PRD-1."""
        body = (
            "## Problem Statement\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        failed = "\n".join(report.failures)
        assert "FAIL: PRD-1" in failed


class TestPRD2Requirements:
    def test_test6_missing_requirements_fails(self) -> None:
        """TEST 6: Missing Requirements fails PRD-2."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-2" in "\n".join(report.failures)

    def test_test7_empty_requirements_section_fails(self) -> None:
        """TEST 7: Empty Requirements section fails PRD-2."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-2" in "\n".join(report.failures)

    def test_test8_prose_requirements_no_items_fails(self) -> None:
        """TEST 8: Requirements with prose but no list items fails PRD-2."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\nThe system should do things that are important.\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-2" in "\n".join(report.failures)


class TestPRD3SuccessMetrics:
    def test_test9_missing_success_metrics_fails(self) -> None:
        """TEST 9: Missing Success Metrics fails PRD-3."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-3" in "\n".join(report.failures)

    def test_test10_non_measurable_success_metrics_warns(self) -> None:
        """TEST 10: Success Metrics without measurable language warns PRD-3."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Things should be better\n- Quality should be good"
        )
        report = _validate(_with_default_acs(body))
        assert "WARN: PRD-3" in "\n".join(report.warnings)
        assert report.fail_count == 0


class TestPRD4OpenQuestions:
    def test_test11_open_questions_with_items_warns(self) -> None:
        """TEST 11: Open Questions with items warns PRD-4 with count."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%\n\n"
            "## Open Questions\n"
            "- What about edge case X?\n- Should we handle Y?"
        )
        report = _validate(_with_default_acs(body))
        warnings = "\n".join(report.warnings)
        assert "WARN: PRD-4" in warnings
        assert "2 unresolved" in warnings
        assert report.fail_count == 0

    def test_test12_open_questions_none_passes(self) -> None:
        """TEST 12: Open Questions with 'None' literal passes PRD-4."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%\n\n"
            "## Open Questions\nNone"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-4" in "\n".join(report.passed)
        assert report.fail_count == 0


class TestPRD5Goals:
    def test_test13_missing_goals_fails(self) -> None:
        """TEST 13: Missing Goals section fails PRD-5."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-5" in "\n".join(report.failures)

    def test_test14_non_measurable_goals_warn(self) -> None:
        """TEST 14: Goals with no measurable language warns PRD-5."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Make things better\n- Help users more\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        warnings = "\n".join(report.warnings)
        assert "WARN: PRD-5" in warnings
        assert "may lack measurable" in warnings

    def test_test15_non_goals_does_not_match_goals(self) -> None:
        """TEST 15: Non-Goals does NOT satisfy the Goals check (word boundary)."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Non-Goals\n- We will not do X\n- We will not do Y\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "FAIL: PRD-5" in "\n".join(report.failures)

    def test_test16_both_non_goals_and_goals_present(self) -> None:
        """TEST 16: Goals present alongside Non-Goals passes PRD-5."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Non-Goals\n- We will not do X\n\n"
            "## Goals\n- Reduce errors by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-5" in "\n".join(report.passed)
        assert report.fail_count == 0
