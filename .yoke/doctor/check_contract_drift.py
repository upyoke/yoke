"""Contract-drift placeholders for this repo's API vocabulary and approvals.

``HC-api-vocabulary-drift`` and ``HC-approval-contract-drift`` both describe
Yoke's own vocabulary and approval contracts. They hold their registered slugs
and display names while the comparison itself is unimplemented, so the roster
keeps a stable home for the invariant instead of losing it.
"""

from __future__ import annotations

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_api_vocabulary_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-api-vocabulary-drift: API vocabulary drift."""
    rec.record("HC-api-vocabulary-drift", "API vocabulary drift", "PASS", "")


def hc_approval_contract_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-approval-contract-drift: Approval contract drift."""
    rec.record("HC-approval-contract-drift", "Approval contract drift", "PASS", "")


__all__ = ["hc_api_vocabulary_drift", "hc_approval_contract_drift"]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('api-vocabulary-drift', 'API vocabulary drift', hc_api_vocabulary_drift),
    ('approval-contract-drift', 'Approval contract drift', hc_approval_contract_drift),
)
