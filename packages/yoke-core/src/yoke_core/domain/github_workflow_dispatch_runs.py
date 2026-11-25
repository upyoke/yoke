"""Find and classify the GitHub runs behind durable workflow dispatches."""

from __future__ import annotations

from typing import Any

from yoke_contracts.github_workflow_dispatch import workflow_dispatch_marker
from yoke_core.domain.github_workflow_dispatch_intents import DispatchIntent


CORRELATION_SEARCH_PAGES = 5
CORRELATION_RUNS_PER_PAGE = 100


def correlated_run(payload: Any, intent: DispatchIntent, token: str) -> Any:
    from yoke_core.domain.github_actions_rest import rest_get

    marker = workflow_dispatch_marker(intent.correlation_id)
    for page in range(1, CORRELATION_SEARCH_PAGES + 1):
        data = rest_get(
            f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/runs",
            query={
                "event": "workflow_dispatch",
                "per_page": str(CORRELATION_RUNS_PER_PAGE),
                "page": str(page),
            },
            token=token,
        )
        if not isinstance(data, dict) or not isinstance(
            data.get("workflow_runs"),
            list,
        ):
            raise ValueError("workflow correlation lookup returned malformed data")
        runs = data["workflow_runs"]
        matches = []
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError(
                    "workflow correlation lookup contained a malformed run"
                )
            if marker in str(run.get("display_title") or ""):
                matches.append(run)
        if len(matches) > 1:
            raise ValueError(
                "multiple workflow runs expose dispatch correlation "
                f"{intent.correlation_id}"
            )
        if matches:
            return matches[0]
        if len(runs) < CORRELATION_RUNS_PER_PAGE:
            break
    return None


def recorded_run(payload: Any, intent: DispatchIntent, token: str) -> dict:
    from yoke_core.domain.github_actions_rest import rest_get

    run = rest_get(
        f"/repos/{payload.repo}/actions/runs/{intent.workflow_run_id}",
        token=token,
    )
    if not isinstance(run, dict):
        raise ValueError("exact workflow run lookup returned malformed data")
    if str(run.get("id") or "") != intent.workflow_run_id:
        raise ValueError("exact workflow run lookup returned a different run id")
    return run


def run_classification(run: dict) -> str:
    """Classify a run as active, a usable verdict, or a completed run without proof."""
    from yoke_core.domain.ci_run_redispatch import VERDICT_CONCLUSIONS

    status = str(run.get("status") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip()
    if status in {"queued", "pending", "waiting", "requested", "in_progress"}:
        return "active"
    if status == "completed" and conclusion in VERDICT_CONCLUSIONS:
        return "verdict"
    if status == "completed" and conclusion:
        return "no_verdict"
    raise ValueError(
        "exact workflow run lookup returned an unknown state "
        f"(status={status!r}, conclusion={conclusion!r})"
    )
