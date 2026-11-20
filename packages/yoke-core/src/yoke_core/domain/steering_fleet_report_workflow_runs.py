"""Read outcomes for recent multi-OS suite dispatches from their exact GitHub runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.github_app_installation_permissions import GITHUB_ACTIONS_READ_PERMISSION_LEVELS
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
def suite_run_findings(
    conn: Any, *, project_id: int, now: datetime
) -> tuple[SuiteRunFinding, ...]:
    """Join durable dispatch identity and inputs to GitHub's current verdict."""
    rows = conn.execute(
        f"SELECT repo, workflow_run_id, inputs FROM {INTENT_TABLE} "
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

    findings = []
    for row in rows:
        repo, run_id, _ = row
        recovery = f"yoke github-actions wait-run {repo} {run_id} --project {project}"
        if repo.casefold() != auth.repo.casefold():
            findings.append(
                _finding(row, "unreadable", "Restore the dispatch repository binding.")
            )
            continue
        try:
            body = gh_rest_transport.request_with_retry(
                gh_rest_transport.RestRequest(
                    method="GET", path=f"/repos/{auth.repo}/actions/runs/{run_id}"
                ),
                token=auth.token,
                max_attempts=1,
                timeout_seconds=3,
            ).body
            if not isinstance(body, dict) or str(body.get("id") or "") != run_id:
                raise ValueError("GitHub returned no matching run")
        except (gh_rest_transport.RestTransportError, ValueError) as exc:
            findings.append(_finding(row, "unreadable", f"{exc}. Retry with {recovery}"))
            continue

        if body.get("status") == "completed" and body.get("conclusion") != "success":
            findings.append(
                _finding(row, body.get("conclusion") or "unknown", recovery, body)
            )
    return tuple(findings)


def _finding(
    row: Any, conclusion: str, recovery: str, run: dict[str, Any] | None = None
) -> SuiteRunFinding:
    repo, run_id, raw_inputs = row
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
