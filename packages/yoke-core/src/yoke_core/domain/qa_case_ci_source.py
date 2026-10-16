"""Validate CI source identity before lane preparation or publication."""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain import qa_case_ci_lane, verification_tree_binding
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def source_tree(case: dict, checkout: Path, branch: str, checked_out_branch: str, tree):
    """Bind the commit from the selected live lane or its recorded cleanup source."""
    if not checked_out_branch:
        checked_out_branch = branch if tree else "HEAD"
    selected_path = case.get("lane_path")
    selected_tree = (
        not selected_path or Path(selected_path).resolve() == checkout.resolve()
    )
    source_ref = (
        "HEAD"
        if selected_tree and checked_out_branch == branch
        else str(case.get("lane_commit_sha") or "").strip()
    )
    if not source_ref:
        raise QaCaseExecutionError(
            f"qa_ci_source_commit_missing: CI case for {branch!r} has no recorded commit "
            "after lane cleanup. Restore the selected registered lane under its "
            "matching item/task claim and rerun the normal gate with its exact "
            "checkout, branch and full SHA; a parent checkout HEAD is not its source."
        )
    head_sha = (
        tree.head_sha
        if source_ref == "HEAD" and tree is not None
        else qa_case_ci_lane.ref_sha(checkout, source_ref)
    )
    return verification_tree_binding.TreeIdentity(str(checkout), head_sha)


def require_source_agreement(
    case: dict,
    checkout: Path,
    *,
    expected_branch: str | None = None,
    expected_sha: str | None = None,
    explicit_checkout: bool = False,
) -> None:
    """An explicit source never authorizes publication under another identity."""
    reason = ""
    selected = case.get("lane_path")
    branch = str(case.get("lane_branch") or "").strip()
    if case.get("item_id") is not None and "lane_id" not in case:
        reason = "the control plane returned no authoritative lane identity"
    elif case.get("item_id") is not None and (not case.get("lane_id") or not branch):
        reason = "the item has no selected registered source lane"
    elif (
        explicit_checkout
        and selected
        and Path(selected).resolve() != checkout.resolve()
    ):
        reason = f"checkout {checkout} differs from selected registered lane {selected}"
    elif expected_branch and branch and expected_branch != branch:
        reason = f"expected branch {expected_branch!r} differs from selected branch {branch!r}"
    elif expected_sha and not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        reason = "expected SHA must be a full lowercase commit hash"
    if not reason and (
        expected_branch or expected_sha or (selected and Path(selected).is_dir())
    ):
        actual_branch = qa_case_ci_lane.checked_out_branch(checkout)
        required_branch = expected_branch or branch
        if required_branch and actual_branch != required_branch:
            reason = f"checkout branch {actual_branch!r} differs from selected branch {required_branch!r}"
        elif expected_sha:
            actual_sha = qa_case_ci_lane.ref_sha(checkout, "HEAD")
            if actual_sha != expected_sha:
                reason = f"checkout HEAD {actual_sha} differs from expected SHA {expected_sha}"
    if reason:
        raise QaCaseExecutionError(
            f"qa_ci_source_mismatch: {reason}. No source was published. Recovery: "
            "inspect the selected registered lane and its matching item/task claim, "
            "then rerun the normal gate with that lane's --checkout-path, "
            "--expected-branch and --expected-sha. If the lane contract is absent, "
            "ask the control-plane operator to serve the source-lane correction "
            "or use its sanctioned source-dev/admin authority. Preserve existing "
            "branches; conflicting remote work needs registered reconciliation."
        )
