"""Exact main-push factory verdicts and one cancelled-attempt recovery."""

from __future__ import annotations

import re
import hashlib

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_rest import newest_run, rest_get, rest_post
from yoke_core.domain.github_workflow_dispatch_intents import (
    DispatchIntentStoreError, claim_attempt, complete_intent, latest_intent,
)


def _runs(repo, workflow, token, **selectors):
    data = rest_get(
        f"/repos/{repo}/actions/workflows/{workflow}/runs",
        query={"per_page": "100", "branch": "main", "event": "push", **selectors},
        token=token,
    )
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ValueError("factory workflow-runs response omitted workflow_runs")
    runs = data["workflow_runs"]
    if not all(isinstance(run, dict) for run in runs):
        raise ValueError("factory workflow-runs response contains a malformed run")
    return [
        run for run in runs
        if run.get("head_branch") == "main" and run.get("event") == "push"
        and (run.get("head_repository") or {}).get("full_name", "").casefold()
        == repo.casefold()
        and all(str(run.get(key) or "") == value for key, value in selectors.items()
                if key == "head_sha")
    ]


def _failure(code, detail):
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=code,
            message=f"{detail}; inspect the exact main factory run and restore GitHub Actions access before retrying the gate",
        ),
    )


def check_main_factory(payload, *, token, request):
    """One relay call, no server wait and no automatic POST replay."""
    if payload.branch != "main" or not re.fullmatch(r"[0-9a-f]{40}", payload.head_sha):
        return _failure(
            "main_factory_target_invalid",
            "main factory gating requires branch main and a full lowercase head_sha",
        )
    try:
        run = newest_run(_runs(
            payload.repo, payload.workflow, token, head_sha=payload.head_sha
        ))
        # A successful matching push is the only acceptable factory evidence.
        if run and run.get("status") == "completed" and run.get("conclusion") == "success":
            return _outcome(run, "passed")
        if run and run.get("status") != "completed":
            return _outcome(run, "running")
        if run and run.get("conclusion") == "cancelled":
            run_id = run.get("id")
            if not isinstance(run_id, int) or run_id <= 0:
                raise ValueError("cancelled factory response omitted a valid run id")
            attempt = run.get("run_attempt")
            if not isinstance(attempt, int) or attempt < 1:
                raise ValueError("cancelled factory response omitted run_attempt")
            if attempt == 1:
                # Re-read before mutation: paired release drivers may share this run.
                refreshed = rest_get(
                    f"/repos/{payload.repo}/actions/runs/{run_id}", token=token
                )
                if not isinstance(refreshed, dict):
                    raise ValueError("factory rerun safety read omitted its run")
                if (
                    refreshed.get("id") != run_id
                    or refreshed.get("head_sha") != payload.head_sha
                    or refreshed.get("head_branch") != "main"
                    or refreshed.get("event") != "push"
                    or refreshed.get("path") != f".github/workflows/{payload.workflow}"
                ):
                    raise ValueError("factory identity changed before rerun")
                if refreshed.get("run_attempt") != 1 or refreshed.get("status") != "completed":
                    return _outcome(refreshed, "running")
                if refreshed.get("conclusion") == "cancelled":
                    _rerun_once(payload, run_id, token, request)
                    return _outcome(run, "running", message="Cancelled factory first attempt rerun requested; waiting for attempt 2.")
        passed = newest_run([
            candidate for candidate in _runs(
                payload.repo, payload.workflow, token, status="success"
            )
            if candidate.get("status") == "completed"
            and candidate.get("conclusion") == "success"
        ])
        return _outcome(
            run, "failed" if run else "no_runs",
            newest_successful_main_sha=passed.get("head_sha") if passed else None,
            message="main_factory_not_successful: obtain a successful main-push factory before releasing; a cancelled run is rerun only from attempt 1.",
        )
    except (RestTransportError, ValueError, DispatchIntentStoreError) as exc:
        return _failure(
            "main_factory_unavailable",
            f"{exc}; a rerun POST is never retried automatically; inspect its attempt before any recovery",
        )


def _outcome(run, state, **extra):
    run = run or {}
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "main_factory_checked": True,
            "state": state,
            "run_id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "html_url": run.get("html_url"),
            **extra,
        },
    )


def _rerun_once(payload, run_id, token, request):
    """Persist the single POST owner using the existing Actions intent store.

    Stage/prod drivers and lost-response retries share this key. A pending intent
    never replays the POST, including when the owner crashed before sending it.
    GitHub's attempt then supplies the outcome; an ambiguous attempt stays blocked.
    """
    actor_id = str(request.actor.actor_id or "")
    project_id = request.options.get("authorized_project_id")
    if not actor_id or project_id is None:
        raise ValueError("factory rerun requires actor and authorized project identity")
    identity = f"main-factory-rerun:{project_id}:{payload.repo.casefold()}:{run_id}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    claimed = claim_attempt(
        request_id=identity, attempt=1, actor_id=actor_id,
        authorization_scope=f"project:{project_id}", payload_checksum=digest,
        repo=payload.repo, workflow=payload.workflow, workflow_ref=payload.head_sha,
        inputs={}, correlation_id=f"factory-rerun-{digest}",
    )
    if not claimed:
        return
    rest_post(
        f"/repos/{payload.repo}/actions/runs/{run_id}/rerun",
        body={}, token=token, max_attempts=1,
    )
    intent = latest_intent(identity)
    if intent is None:
        raise DispatchIntentStoreError("factory rerun intent disappeared")
    complete_intent(
        intent, workflow_run_id=str(run_id), run_url=None,
        html_url=f"https://github.com/{payload.repo}/actions/runs/{run_id}",
    )
