"""Claim-coverage classifier tests for idea_readiness_repair.

Sibling of ``test_idea_readiness_repair.py`` (near 350-line cap). Covers
the regression: pure claim-coverage readiness gaps must classify as
recoverable, not as ``CLASS_UNRECOVERABLE``.

AC traceability:
- AC-1: pure ``FILE_BUDGET_NOT_IN_CLAIM`` -> recoverable.
- AC-2: pure ``CLAIM_NOT_IN_FILE_BUDGET`` -> recoverable.
- AC-3: mixed claim-coverage (both recoverable codes, no STALE_LINE_COUNT)
  -> recoverable.
- AC-4: existing pure-stale-count / stale-plus-claim / unrecoverable
  surfaces remain intact.
- AC-6: pure ``FILE_BUDGET_NOT_IN_CLAIM`` readiness evidence is
  not classified as terminal.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import idea_readiness_repair


def _claim_issue(code: str, path: str = "x.py") -> dict:
    return {"code": code, "context": {"path": path}}


class TestClassifyClaimOnly(unittest.TestCase):
    """Pure claim-coverage issue sets are recoverable."""

    def test_pure_file_budget_not_in_claim_is_recoverable(self):
        # AC-1 + AC-6.
        issues = [_claim_issue("FILE_BUDGET_NOT_IN_CLAIM", "a.py")]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )

    def test_pure_claim_not_in_file_budget_is_recoverable(self):
        # AC-2.
        issues = [_claim_issue("CLAIM_NOT_IN_FILE_BUDGET", "a.py")]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )

    def test_mixed_claim_codes_no_stale_is_recoverable(self):
        # AC-3.
        issues = [
            _claim_issue("FILE_BUDGET_NOT_IN_CLAIM", "a.py"),
            _claim_issue("CLAIM_NOT_IN_FILE_BUDGET", "b.py"),
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )

    def test_multiple_file_budget_not_in_claim_is_recoverable(self):
        # Multiple pure FILE_BUDGET_NOT_IN_CLAIM issues classify as
        # recoverable, not unrecoverable.
        issues = [
            _claim_issue("FILE_BUDGET_NOT_IN_CLAIM", f"file_{i}.py")
            for i in range(8)
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )


class TestClassifyMixedWithUnrecoverable(unittest.TestCase):
    """Claim codes mixed with non-recoverable codes stay terminal."""

    def test_claim_plus_unresolved_function_is_unrecoverable(self):
        issues = [
            _claim_issue("FILE_BUDGET_NOT_IN_CLAIM", "a.py"),
            {"code": "UNRESOLVED_FUNCTION", "context": {}},
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_UNRECOVERABLE,
        )

    def test_claim_plus_missing_sibling_is_unrecoverable(self):
        issues = [
            _claim_issue("CLAIM_NOT_IN_FILE_BUDGET", "a.py"),
            {"code": "MISSING_SIBLING_PLAN", "context": {"path": "x"}},
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_UNRECOVERABLE,
        )


class TestStaleCountInvariants(unittest.TestCase):
    """The new claim-only branch must not perturb prior classifications."""

    def test_empty_still_pass(self):
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues([]),
            idea_readiness_repair.CLASS_PASS,
        )

    def test_pure_stale_count_unchanged(self):
        issues = [{"code": "STALE_LINE_COUNT",
                   "context": {"path": "a.py", "recorded": 1, "actual": 2}}]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_PURE_STALE_COUNT,
        )

    def test_stale_plus_claim_still_mixed(self):
        issues = [
            {"code": "STALE_LINE_COUNT",
             "context": {"path": "a.py", "recorded": 1, "actual": 2}},
            _claim_issue("FILE_BUDGET_NOT_IN_CLAIM", "b.py"),
        ]
        self.assertEqual(
            idea_readiness_repair.classify_readiness_issues(issues),
            idea_readiness_repair.CLASS_MIXED_STALE_COUNT,
        )


if __name__ == "__main__":
    unittest.main()
