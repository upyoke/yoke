"""Doctor health check — merge-queue binding coherence + declared drift.

HC-merge-queue-binding verifies that a project declaring the
``merge_queue`` capability actually has the binding the queue route
depends on: a branch ruleset requiring the merge queue on the default
branch, and a CI workflow carrying the ``merge_group`` trigger the
queue's integration gate runs through. It also diffs live merge_queue
parameters, required checks, ``allow_auto_merge``, and (when readable)
bypass actors against ``.yoke/merge-queue.json`` so parameter drift
turns red. The declaration is fetched only from the repository at the
project's gate branch, so local and hosted runners compare the same rules.

SKIPs cleanly when the project does not declare the capability, when
GitHub auth is unavailable on this host, or when the CI workflow
filename is undeclared — those are configuration states with their own
checks, not merge-queue drift.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
    GITHUB_METADATA_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import (
    gh_rest_transport,
    github_merge_queue_rest as mq_rest,
)
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.github_actions_workflow_inspection import (
    declares_merge_group,
)
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.gh_rest_transport import (
    RestTransportError,
)
from yoke_core.domain.merge_queue_live_drift import (
    ADMINISTRATION_RECOVERY,
    MERGE_QUEUE_RULE_TYPE as _MERGE_QUEUE_RULE_TYPE,
    compare_declared_against_live,
    live_branch_rules,
)
from yoke_core.domain.merge_queue_declaration import (
    DECLARATION_RELATIVE_PATH,
    MergeQueueDeclarationError,
    parse_declaration,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    MissingPermission,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.projects_seed_ci_workflow import (
    MERGE_QUEUE_CAPABILITY_TYPE,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.domain.project_attribution import resolved_project

CHECK_ID = "merge-queue-binding"
CHECK_NAME = "Merge queue binding"


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


def _workflow_has_merge_group_trigger(
    conn, token: str, owner: str, repo: str, project_id: int, ref: str,
) -> Tuple[Optional[bool], str]:
    """Check the declared CI workflow for a merge_group trigger."""
    from yoke_core.domain.qa_command_plan_registration import (
        declared_ci_workflow,
    )

    workflow_file = declared_ci_workflow(conn, project_id)
    if not workflow_file:
        return None, "no ci_workflow_file capability declared"
    try:
        text = mq_rest.fetch_file_text(
            owner,
            repo,
            f".github/workflows/{workflow_file}",
            ref=ref,
            token=token,
        )
    except RestTransportError as exc:
        return None, f"workflow read failed: {exc}"
    if text is None:
        return None, f"no {workflow_file} at {owner}/{repo}@{ref}"
    try:
        has_trigger = declares_merge_group(text)
    except Exception as exc:  # noqa: BLE001 — unreadable workflow is SKIP-ish
        return None, f"workflow unreadable: {exc}"
    return has_trigger, workflow_file


def _repo_declaration(
    owner: str, repo: str, ref: str, token: str,
) -> Tuple[Optional[dict], str]:
    """Return (declared, detail) read from the repository at ``ref``."""
    source = f"{owner}/{repo}@{ref}:{DECLARATION_RELATIVE_PATH}"
    try:
        raw = mq_rest.fetch_file_text(
            owner, repo, DECLARATION_RELATIVE_PATH, ref=ref, token=token,
        )
    except RestTransportError as exc:
        return None, f"declaration unreadable: {source}: {exc}"
    if raw is None:
        return None, f"no declaration at {source}"
    try:
        return parse_declaration(raw, source=source), source
    except MergeQueueDeclarationError as exc:
        return None, f"declaration unreadable: {exc}"


def hc_merge_queue_binding(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-merge-queue-binding (project-scoped, GitHub-dependent)."""
    project = resolved_project(args.project)
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

    access_problem = ""
    read_permissions = {
        **GITHUB_METADATA_READ_PERMISSION_LEVELS,
        **GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    }
    try:
        # GitHub hides bypass actors without write authority, even on GET.
        auth = resolve_project_github_auth(
            project,
            db_path=args.db_path,
            required_permissions={
                **read_permissions,
                **GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
            },
        )
    except MissingPermission as err:
        access_problem = (
            f"administrative settings unreadable: {err}. {ADMINISTRATION_RECOVERY}"
        )
        try:
            auth = resolve_project_github_auth(
                project, db_path=args.db_path, required_permissions=read_permissions,
            )
        except ProjectGithubAuthError as err:
            rec.record(
                CHECK_ID, CHECK_NAME, "FAIL",
                f"{access_problem} Read access also unavailable: {err}",
            )
            return
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

    live_rules, rules_error = live_branch_rules(
        owner, repo, default_branch, token=auth.token,
    )
    if live_rules is None:
        rec.record(
            CHECK_ID, CHECK_NAME, "FAIL" if access_problem else "SKIP",
            f"{access_problem} {rules_error}".strip(),
        )
        return

    has_queue = any(
        isinstance(rule, dict) and rule.get("type") == _MERGE_QUEUE_RULE_TYPE
        for rule in live_rules
    )
    trigger, trigger_detail = _workflow_has_merge_group_trigger(
        conn, auth.token, owner, repo, project_id, default_branch
    )

    problems = [access_problem] if access_problem else []
    if not has_queue:
        problems.append(
            f"default branch '{default_branch}' has no merge_queue rule; "
            "add the queue ruleset or drop the capability"
        )
    if trigger is False:
        problems.append(
            f"CI workflow {trigger_detail} has no merge_group trigger; "
            "the queue's integration gate would never run"
        )

    declared, decl_detail = _repo_declaration(
        owner, repo, default_branch, auth.token
    )
    if declared is not None:
        report = compare_declared_against_live(
            declared,
            owner=owner,
            repo=repo,
            rules=live_rules,
            token=auth.token,
        )
        problems.extend(report.unreadable)
        problems.extend(report.drift)
    elif "declaration unreadable" in decl_detail:
        problems.append(decl_detail)

    if problems:
        rec.record(CHECK_ID, CHECK_NAME, "FAIL", "; ".join(problems))
        return
    detail = f"merge_queue rule active on '{default_branch}'"
    if trigger is None:
        detail += f" (workflow trigger unverified: {trigger_detail})"
    else:
        detail += f"; merge_group trigger present in {trigger_detail}"
    if declared is not None:
        detail += f"; matches {DECLARATION_RELATIVE_PATH} ({decl_detail})"
    else:
        detail += f" ({decl_detail}; parameter drift not checked)"
    rec.record(CHECK_ID, CHECK_NAME, "PASS", detail)

__all__ = ["CHECK_ID", "CHECK_NAME", "hc_merge_queue_binding"]
