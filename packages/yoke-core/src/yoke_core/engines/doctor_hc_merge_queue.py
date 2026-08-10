"""Doctor health check — merge-queue binding coherence.

HC-merge-queue-binding verifies that a project declaring the
``merge_queue`` capability actually has the binding the queue route
depends on: a branch ruleset requiring the merge queue on the default
branch, and a CI workflow carrying the ``merge_group`` trigger the
queue's integration gate runs through. A declared capability without
either half would send landings into a queue that cannot validate or
merge them, so the drift is surfaced before a landing pays for it.

SKIPs cleanly when the project does not declare the capability, when
GitHub auth is unavailable on this host, or when the CI workflow
filename is undeclared — those are configuration states with their own
checks, not merge-queue drift.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.projects_seed_ci_workflow import (
    MERGE_QUEUE_CAPABILITY_TYPE,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

CHECK_ID = "merge-queue-binding"
CHECK_NAME = "Merge queue binding"

_MERGE_QUEUE_RULE_TYPE = "merge_queue"


def _marker(conn) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _project_row(conn, project: str) -> Tuple[Optional[int], str]:
    p = _marker(conn)
    row_id = query_scalar(
        conn, f"SELECT id FROM projects WHERE slug = {p}", (project,)
    )
    branch = query_scalar(
        conn,
        "SELECT COALESCE(default_branch, 'main') FROM projects "
        f"WHERE slug = {p}",
        (project,),
    )
    return (
        int(row_id) if row_id is not None else None,
        str(branch or "main"),
    )


def _declares_merge_queue(conn, project_id: int) -> bool:
    p = _marker(conn)
    count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM project_capabilities "
        f"WHERE project_id = {p} AND type = {p}",
        (project_id, MERGE_QUEUE_CAPABILITY_TYPE),
    )
    return int(count or 0) > 0


def _ruleset_requires_queue(
    token: str, owner: str, repo: str, branch: str
) -> Tuple[Optional[bool], str]:
    """Return (required?, detail); ``None`` when the read failed."""
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/rules/branches/{branch}",
            ),
            token=token,
        )
    except RestNotFoundError:
        return False, "no active branch rules found"
    except RestTransportError as exc:
        return None, str(exc)
    rules = response.body if isinstance(response.body, list) else []
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == _MERGE_QUEUE_RULE_TYPE:
            return True, "merge_queue rule active"
    return False, "no merge_queue rule among active branch rules"


def _workflow_has_merge_group_trigger(
    conn, token: str, owner: str, repo: str, project_id: int
) -> Tuple[Optional[bool], str]:
    """Check the declared CI workflow for a merge_group trigger."""
    from yoke_core.domain.qa_command_plan_registration import (
        declared_ci_workflow,
    )

    workflow_file = declared_ci_workflow(conn, project_id)
    if not workflow_file:
        return None, "no ci_workflow_file capability declared"
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=(
                    f"/repos/{owner}/{repo}/contents/"
                    f".github/workflows/{workflow_file}"
                ),
                accept="application/vnd.github.raw+json",
            ),
            token=token,
        )
    except RestTransportError as exc:
        return None, f"workflow read failed: {exc}"
    text = response.body if isinstance(response.body, str) else ""
    return ("merge_group" in text), workflow_file


def hc_merge_queue_binding(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-merge-queue-binding (project-scoped, GitHub-dependent)."""
    project = args.project or "yoke"
    project_id, default_branch = _project_row(conn, project)
    if project_id is None:
        rec.record(
            CHECK_ID, CHECK_NAME, "SKIP",
            f"project '{project}' not found in this control plane",
        )
        return
    if not _declares_merge_queue(conn, project_id):
        rec.record(
            CHECK_ID, CHECK_NAME, "SKIP",
            f"project '{project}' does not declare the merge_queue "
            "capability",
        )
        return

    try:
        auth = resolve_project_github_auth(
            project,
            db_path=args.db_path,
            required_permissions=GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as err:
        rec.record(
            CHECK_ID, CHECK_NAME, "SKIP",
            (
                f"Project GitHub auth unavailable for '{project}' "
                f"({err.code}): {err}\n"
                f"  Repair: {repair_command_hint(err, project)}"
            ),
        )
        return
    owner, repo = gh_rest_transport.split_repo(auth.repo)

    required, rule_detail = _ruleset_requires_queue(
        auth.token, owner, repo, default_branch
    )
    if required is None:
        rec.record(
            CHECK_ID, CHECK_NAME, "SKIP",
            f"branch rules unreadable for {owner}/{repo}: {rule_detail}",
        )
        return
    trigger, trigger_detail = _workflow_has_merge_group_trigger(
        conn, auth.token, owner, repo, project_id
    )

    problems = []
    if not required:
        problems.append(
            f"default branch '{default_branch}' has no merge_queue rule "
            f"({rule_detail}); add the queue ruleset or drop the capability"
        )
    if trigger is False:
        problems.append(
            f"CI workflow {trigger_detail} has no merge_group trigger; "
            "the queue's integration gate would never run"
        )
    if problems:
        rec.record(
            CHECK_ID, CHECK_NAME, "FAIL",
            "; ".join(problems),
        )
        return
    detail = f"merge_queue rule active on '{default_branch}'"
    if trigger is None:
        detail += f" (workflow trigger unverified: {trigger_detail})"
    else:
        detail += f"; merge_group trigger present in {trigger_detail}"
    rec.record(CHECK_ID, CHECK_NAME, "PASS", detail)


__all__ = ["CHECK_ID", "CHECK_NAME", "hc_merge_queue_binding"]
