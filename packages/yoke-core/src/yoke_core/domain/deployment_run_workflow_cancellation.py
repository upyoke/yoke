"""Cancel the GitHub workflows an ended deployment run dispatched.

Every correlated workflow a run dispatches is a durable dispatch intent whose
request id starts ``deploy:<project>:<run>:`` (see
:func:`yoke_core.domain.deploy_pipeline_github_workflow_inputs.workflow_dispatch_request_id`)
and which records the GitHub run id once the run is identified. When the run
ends — terminalized, failed, rejected or taken over — those workflows are
stale: one left queued would deploy later beside the run that replaced it.

:func:`cancel_run_workflows` runs strictly after the close has committed and
asks GitHub to cancel each recorded workflow. It never raises: the close is
already the durable outcome, so a cancellation that fails is returned and
logged with its reason and recovery command instead of undoing anything.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.github_actions_run_cancel import RunCancelError, cancel_run
from yoke_core.domain.github_workflow_dispatch_intents import INTENT_TABLE


_LOG = logging.getLogger(__name__)

#: The dispatch was recorded but GitHub never named its run, so there is no
#: run id to cancel; the correlation id finds it.
RUN_UNIDENTIFIED = "run_unidentified"
CANCEL_FAILED = "cancel_failed"


@dataclass(frozen=True)
class WorkflowCancellation:
    repo: str
    workflow_run_id: str
    outcome: str
    detail: str = ""


def _recorded_dispatches(conn: Any, run_id: str) -> List[Dict[str, str]]:
    owner = query_one(
        conn,
        "SELECT p.slug FROM deployment_runs dr "
        "JOIN projects p ON p.id = dr.project_id WHERE dr.id = %s",
        (run_id,),
    )
    if owner is None:
        return []
    prefix = f"deploy:{owner[0]}:{run_id}:"
    # The newest attempt of each logical request is the one GitHub may still
    # be running; earlier attempts concluded before a retry was allowed.
    rows = query_rows(
        conn,
        f"SELECT DISTINCT ON (i.request_id) i.repo, i.workflow_run_id, "
        "i.correlation_id, i.state, p.slug "
        f"FROM {INTENT_TABLE} i "
        "LEFT JOIN projects p "
        "ON i.authorization_scope = 'project:' || p.id::text "
        "WHERE LEFT(i.request_id, %s) = %s "
        "ORDER BY i.request_id, i.attempt DESC",
        (len(prefix), prefix),
    )
    return [
        {
            "repo": str(row[0]),
            "workflow_run_id": str(row[1] or ""),
            "correlation_id": str(row[2]),
            "state": str(row[3]),
            "project": str(row[4] or ""),
        }
        for row in rows
        if str(row[3]) != "rejected"
    ]


def _token(project: str, repo: str) -> str:
    from yoke_core.domain.project_github_auth import resolve_project_github_auth

    resolved = resolve_project_github_auth(
        project, required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS
    )
    if resolved.repo.casefold() != repo.casefold():
        raise RunCancelError(
            f"project {project!r} is bound to {resolved.repo!r}, not {repo!r}"
        )
    return resolved.token


def _cancel_one(dispatch: Dict[str, str]) -> WorkflowCancellation:
    repo = dispatch["repo"]
    run = dispatch["workflow_run_id"]
    if not run:
        return WorkflowCancellation(
            repo,
            "",
            RUN_UNIDENTIFIED,
            "GitHub never named the run for dispatch correlation "
            f"{dispatch['correlation_id']}; find it in {repo}'s Actions runs "
            "by that id and cancel it there.",
        )
    try:
        outcome = cancel_run(
            repo=repo, run_id=run, token=_token(dispatch["project"], repo)
        )
    except Exception as exc:  # noqa: BLE001 - the close stands; report instead
        return WorkflowCancellation(
            repo,
            run,
            CANCEL_FAILED,
            f"{exc}. Recovery: restore the project's GitHub Actions write "
            f"authority, then run `yoke github-actions run cancel {repo} {run} "
            f"--project {dispatch['project'] or '<project>'}`.",
        )
    return WorkflowCancellation(repo, run, outcome)


def cancel_run_workflows(conn: Any, run_id: str) -> List[Dict[str, str]]:
    """Cancel every workflow *run_id* dispatched; return one outcome each."""
    try:
        dispatches = _recorded_dispatches(conn, run_id)
    except Exception as exc:  # noqa: BLE001 - the close stands; report instead
        # Only the failed read is undone: callers run this after their commit,
        # and an aborted transaction would refuse their next statement.
        conn.rollback()
        _LOG.warning(
            "deployment run %s ended but its dispatched workflows could not be "
            "read (%s); inspect its GitHub Actions runs and cancel any still "
            "queued or running",
            run_id,
            exc,
        )
        return [asdict(WorkflowCancellation("", "", CANCEL_FAILED, str(exc)))]
    results = [_cancel_one(dispatch) for dispatch in dispatches]
    for result in results:
        if result.outcome in {CANCEL_FAILED, RUN_UNIDENTIFIED}:
            _LOG.warning(
                "deployment run %s ended but workflow %s in %s was not cancelled: %s",
                run_id,
                result.workflow_run_id or "(unidentified)",
                result.repo,
                result.detail,
            )
    return [asdict(result) for result in results]


__all__ = [
    "CANCEL_FAILED",
    "RUN_UNIDENTIFIED",
    "WorkflowCancellation",
    "cancel_run_workflows",
]
