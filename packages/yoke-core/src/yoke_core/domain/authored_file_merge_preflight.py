"""Local authored-file contract before a merge-queue lane is published."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.file_line_git_scope import (
    FileLineGitScope,
    resolve_file_line_git_scope,
)
from yoke_harness.git_hooks import file_line_check
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def _base_ref(target: str) -> str:
    return target if target.startswith("origin/") else f"origin/{target}"


def _movement_detail(
    checkout: Path,
    *,
    base_ref: str,
    scope: FileLineGitScope,
    change: file_line_check.ChangedFile,
    limit: int,
) -> str:
    """Explain when base growth, rather than the lane alone, caused an overage."""
    item_base_count = file_line_check.git_show_line_count(
        scope.item_base_sha,
        change.path,
        repo_root=checkout,
    )
    current_base_count = file_line_check.git_show_line_count(
        base_ref,
        change.path,
        repo_root=checkout,
    )
    lane_delta = change.new_line_count - current_base_count
    recorded_base_result = item_base_count + lane_delta
    base_delta = current_base_count - item_base_count
    if (
        scope.configured_item_base
        and base_delta > 0
        and recorded_base_result <= limit < change.new_line_count
    ):
        return (
            f"{base_ref} moved this file from {item_base_count} to "
            f"{current_base_count} lines since the lane's recorded base "
            f"(+{base_delta}). The same net lane delta would have produced "
            f"{recorded_base_result} lines on that base; after the base "
            f"movement the rebased result is {change.new_line_count}."
        )
    return (
        f"Against {base_ref}, the rebased lane changes this file from "
        f"{current_base_count} to {change.new_line_count} lines."
    )


def enforce_authored_file_limit(checkout: Path, *, target: str) -> None:
    """Refuse a rebased queue lane that violates the authored-file limit."""
    base_ref = _base_ref(target)
    verdict = file_line_check.changed_files_check(
        repo_root=checkout,
        base=base_ref,
        staged=False,
    )
    inspect_command = f"yoke check file-line --base {base_ref} --repo {checkout}"
    if verdict.ok:
        return
    if not verdict.hard_fails:
        raise QaCaseExecutionError(
            "authored-file merge preflight could not inspect the rebased "
            f"lane: {verdict.summary}. Run `{inspect_command}` to diagnose "
            "the checkout, repair the named git/base condition, and rerun "
            "the QA case; the lane was not published."
        )

    policy = file_line_check.resolved_policy(checkout)
    try:
        scope = resolve_file_line_git_scope(checkout, base_ref)
    except (FileNotFoundError, RuntimeError) as exc:
        raise QaCaseExecutionError(
            "authored-file merge preflight found a line-limit violation but "
            f"could not resolve its base movement: {exc}. Run "
            f"`{inspect_command}` to re-inspect, then rerun the QA case; "
            "the lane was not published."
        ) from exc

    lines = [
        "authored-file merge preflight refused the rebased lane before "
        "publication or CI:"
    ]
    for change in verdict.hard_fails:
        movement = _movement_detail(
            checkout,
            base_ref=base_ref,
            scope=scope,
            change=change,
            limit=policy.limit,
        )
        lines.append(
            f"- {change.path}: {change.new_line_count} authored lines, "
            f"limit {policy.limit}. {movement}"
        )
    lines.extend(
        [
            f"Run `{inspect_command}` to re-inspect.",
            "Split the offending file(s), commit the result, and rerun the "
            "QA case; the lane was not pushed and no landing pull request "
            "was opened or armed.",
        ]
    )
    raise QaCaseExecutionError("\n".join(lines))


__all__ = ["enforce_authored_file_limit"]
