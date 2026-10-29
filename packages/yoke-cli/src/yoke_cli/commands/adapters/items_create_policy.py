"""Posture limits for workflow-selected item intake."""

from __future__ import annotations

import argparse
from typing import Optional


TASK_VERIFICATION_REFUSAL = (
    "TASK_VERIFICATION_POSTURE_UNSUPPORTED: task v1 has no verification "
    "posture or review stage. File work needing a selected verification plan "
    "or method with yoke dash --title TEXT --spec-file PATH."
)
TASK_PATH_CLAIMS_REFUSAL = (
    "TASK_PATH_CLAIMS_POSTURE_UNSUPPORTED: task v1 does not allow a path-claims "
    "posture. File repository work needing reserved paths with yoke dash "
    "--title TEXT --spec-file PATH."
)
TASK_APPROVAL_REFUSAL = (
    "TASK_APPROVAL_POSTURE_UNSUPPORTED: approval-gated postures are Dash-only "
    "today; task v1 declares approvals=none and no item posture allowlist. "
    "File approval-gated work with yoke dash --title TEXT --spec-file PATH. Task approval "
    "gates await the approvals, notifications, and inbox design."
)
TASK_DEPLOYMENT_REFUSAL = (
    "TASK_DEPLOYMENT_POSTURE_UNSUPPORTED: task v1 is merge-free and has no "
    "deploy-after-merge posture. File work needing item-bound delivery with "
    "yoke dash --title TEXT --spec-file PATH."
)


def _unsupported_posture(parsed: argparse.Namespace) -> Optional[str]:
    if parsed.verification_plan is not None or parsed.verification_method:
        return TASK_VERIFICATION_REFUSAL
    if parsed.path_claims:
        return TASK_PATH_CLAIMS_REFUSAL
    if parsed.approval_on_done:
        return TASK_APPROVAL_REFUSAL
    if parsed.deployment:
        return TASK_DEPLOYMENT_REFUSAL
    return None
