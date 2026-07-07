"""Report rendering for PRD validation.

Sibling of :mod:`yoke_core.domain.prd_validate`. Owns the human-facing
report printer.

``Report`` is owned by the entry-point module; we import it for type-checking
only to avoid a circular import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yoke_core.domain.prd_validate import Report


def print_report(item_label: str, report: "Report") -> None:
    print(f"PRD Validation: {item_label}")
    print("========================================")
    print()
    if report.failures:
        print("--- FAILURES ---")
        print("\n".join(report.failures))
        print()
    if report.warnings:
        print("--- WARNINGS ---")
        print("\n".join(report.warnings))
        print()
    if report.passed:
        print("--- PASSED ---")
        print("\n".join(report.passed))
        print()
    print("========================================")
    print(f"Results: {report.pass_count} passed, {report.warn_count} warnings, {report.fail_count} failures")
    print("========================================")
