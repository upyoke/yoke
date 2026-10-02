"""Publication and check-proof narration for a standalone merge outcome."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from yoke_core.domain.standalone_item_merge_post_push import PostPushVerdict


def refusal_message(
    verdict: PostPushVerdict,
    *,
    merge_sha: str,
    resume_command: str,
) -> str:
    observed = "; ".join(run.describe() for run in verdict.runs)
    if verdict.kind == "failed":
        reason = f"post-push CI failed for {merge_sha}: {observed}"
    elif verdict.kind == "timed_out":
        reason = f"post-push CI remained pending for {merge_sha}: {observed}"
    else:
        reason = verdict.detail or f"post-push CI was unreadable for {merge_sha}"
    return (
        f"{reason}. The merge is landed; the work claim and lane are retained. "
        f"Commit the fix in the same lane, then resume with `{resume_command}`."
    )


def publication_narration(
    *,
    pushed: bool,
    push_warning: str,
    verdict: Optional[PostPushVerdict],
) -> str:
    if push_warning:
        return push_warning
    if not pushed:
        return (
            "Publication: no remote; merge remains local-only. "
            "Merged locally; not pushed because GitHub is not connected."
        )
    kind = None if verdict is None else verdict.kind
    return {
        None: "Publication: target pushed; post-push checks were not run.",
        "passed": "Publication: target pushed; post-push checks passed.",
        "no_checks": "Publication: target pushed; no post-push checks discovered.",
    }.get(kind, "")


def missing_merge_identity_message(branch: str, target: str) -> str:
    return (
        f"post-push checks skipped: no merge commit records {branch!r} "
        f"landing on {target!r}, so there is nothing to prove. Re-run "
        "the merge once the branch has a commit the target does not already contain."
    )
