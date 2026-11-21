"""Read recent multi-OS suite outcomes from one workflow listing per project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.github_app_installation_permissions import GITHUB_ACTIONS_READ_PERMISSION_LEVELS
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.steering_report_handler_timing import time_dependency
from yoke_core.domain import gh_rest_transport, json_helper
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.project_github_sync_receipt import suppress_installation_token_receipts
from yoke_core.domain.schema_connection import instant_parameter
from yoke_core.domain.schema_github_workflow_dispatch_intents import INTENT_TABLE

_WORKFLOW = "yoke-suite.yml"
_LOOKBACK = timedelta(days=1)
_RUN_LIMIT = 10


@dataclass(frozen=True)
class SuiteRunFinding:
    repo: str
    run_id: str
    commit: str
    conclusion: str
    recovery: str


@suppress_installation_token_receipts()
@time_dependency("suite_run_reads")
def suite_run_findings(
    conn: Any, *, project_id: int, now: datetime
) -> tuple[SuiteRunFinding, ...]:
    """Join dispatch identities and inputs to the current listing by run ID."""
    rows = conn.execute(
        f"SELECT repo, workflow_run_id, inputs, created_at FROM {INTENT_TABLE} "
        "WHERE authorization_scope = %s AND workflow = %s "
        "AND state = 'completed' AND updated_at >= %s "
        "ORDER BY updated_at DESC, request_id, attempt DESC LIMIT %s",
        (
            f"project:{project_id}",
            _WORKFLOW,
            instant_parameter(conn, now - _LOOKBACK),
            _RUN_LIMIT,
        ),
    ).fetchall()
    if not rows:
        return ()

    project = str(project_id)
    try:
        auth = resolve_project_github_auth(
            project,
            conn=conn,
            required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        return tuple(
            _finding(row, "unreadable", repair_command_hint(exc, project))
            for row in rows
        )

    bound_rows = [row for row in rows if row[0].casefold() == auth.repo.casefold()]
    listed_runs = {}
    listing_error = ""
    if bound_rows:
        oldest = min(parse_instant(row[3]) for row in bound_rows)
        try:
            listed_runs = _list_runs(auth.repo, auth.token, oldest)
        except (gh_rest_transport.RestTransportError, ValueError) as exc:
            listing_error = str(exc)

    findings = []
    for row in rows:
        repo, run_id, _, _ = row
        recovery = f"yoke github-actions wait-run {repo} {run_id} --project {project}"
        if repo.casefold() != auth.repo.casefold():
            findings.append(
                _finding(row, "unreadable", "Restore the dispatch repository binding.")
            )
            continue
        body = listed_runs.get(run_id)
        if body is None:
            reason = listing_error or f"GitHub's workflow listing omitted run {run_id}"
            findings.append(_finding(row, "unreadable", f"{reason}. Retry with {recovery}"))
            continue

        if body.get("status") == "completed" and body.get("conclusion") != "success":
            findings.append(
                _finding(row, body.get("conclusion") or "unknown", recovery, body)
            )
    return tuple(findings)


def _list_runs(repo: str, token: str, oldest: datetime) -> dict[str, dict[str, Any]]:
    body = gh_rest_transport.request_with_retry(
        gh_rest_transport.RestRequest(
            method="GET",
            path=f"/repos/{repo}/actions/workflows/{_WORKFLOW}/runs",
            query={
                "event": "workflow_dispatch",
                "per_page": "100",
                "created": f">={format_instant(oldest)}",
            },
        ),
        token=token,
        max_attempts=1,
        timeout_seconds=3,
    ).body
    runs = body.get("workflow_runs") if isinstance(body, dict) else None
    if not isinstance(runs, list):
        raise ValueError("GitHub returned an invalid workflow run listing")
    by_id = {}
    for run in runs:
        if not isinstance(run, dict) or not str(run.get("id", "")).isdecimal():
            raise ValueError("GitHub returned an invalid workflow run in the listing")
        by_id[str(run["id"])] = run
    return by_id


def _finding(
    row: Any, conclusion: str, recovery: str, run: dict[str, Any] | None = None
) -> SuiteRunFinding:
    repo, run_id, raw_inputs, _ = row
    # The workflow definition's head_sha can differ from the commit under test.
    inputs = (
        raw_inputs
        if isinstance(raw_inputs, dict)
        else json_helper.loads_text(str(raw_inputs or "{}"))
    )
    commit = (inputs.get("sha") if isinstance(inputs, dict) else None) or (
        (run or {}).get("head_sha") or "dispatched ref"
    )
    return SuiteRunFinding(repo, run_id, commit, conclusion, recovery)


def suite_run_lines(findings: tuple[SuiteRunFinding, ...]) -> list[str]:
    return [
        f"  {row.repo} run {row.run_id}, commit {row.commit}: "
        f"{row.conclusion}. {row.recovery}"
        for row in findings
    ]
