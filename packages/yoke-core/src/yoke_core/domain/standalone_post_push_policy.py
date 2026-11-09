"""Apply the project's declared CI policy to standalone push observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoke_core.domain.project_ci_workflow import project_ci_workflow_file

if TYPE_CHECKING:
    from yoke_core.domain.standalone_item_merge_post_push import PostPushVerdict


def observe_post_push_checks(
    project: str, merge_sha: str, authority: str, notes: list[str]
) -> tuple[PostPushVerdict, bool]:
    # Import at call time: the post-push owner also defines the verdict model.
    from yoke_core.domain import standalone_item_merge_post_push as post_push

    try:
        required = bool(project_ci_workflow_file(project))
    except RuntimeError as exc:
        notes.append(
            f"CI workflow declaration unreadable: {exc}; retaining the post-push "
            "CI gate. Repair the project's ci_workflow_file capability read."
        )
        required = True
    if required:
        return post_push.await_post_push_checks(project, merge_sha, authority), True

    runs, error = post_push.read_check_runs(project, merge_sha, authority)
    observed = "; ".join(run.describe() for run in (runs or ()))
    detail = error or observed or "no post-push checks discovered"
    warning = (
        "No ci_workflow_file is declared; post-push checks are receipt evidence "
        f"and do not gate close-out: {detail}"
    )
    notes.append(warning)
    return post_push.PostPushVerdict(
        "observed", runs=runs or (), detail=warning
    ), False
