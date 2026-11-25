"""Reconcile ambiguous sends for the read-only, exact Platform proof."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.github_workflow_dispatch import workflow_dispatch_marker
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_rest import read_lightweight_tag, rest_get
from yoke_core.domain.github_workflow_dispatch_intents import DispatchIntent, proof_attempts
from yoke_core.domain.github_workflow_dispatch_runs import (
    CORRELATION_RUNS_PER_PAGE,
    CORRELATION_SEARCH_PAGES,
    recorded_run,
    run_classification,
)
from yoke_core.domain.platform_consumer_dispatch import (
    CANDIDATE_INPUT,
    CONSUMER_CHECK_WORKFLOW,
    CONSUMER_REPO,
    PENDING_JOIN_BUDGET_SECONDS,
    consumer_dispatch_tag,
    pair_request_id,
)

_COMMIT = re.compile(r"[0-9a-f]{40}")
_REDISPATCH_SUFFIX = re.compile(r":redispatch:[0-9]+")
_WORKFLOW_PATH = f".github/workflows/{CONSUMER_CHECK_WORKFLOW}"
_JOIN_WINDOW = timedelta(seconds=PENDING_JOIN_BUDGET_SECONDS)


class ConsumerProofRecoveryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_exact_consumer_proof(payload: Any, request_id: str) -> bool:
    """Only exact-pair release requests may replace ambiguous sends."""
    if payload.repo != CONSUMER_REPO or payload.workflow != CONSUMER_CHECK_WORKFLOW:
        return False
    candidate = payload.inputs.get(CANDIDATE_INPUT, "")
    consumer = payload.inputs.get("consumer_sha", "")
    if not (_COMMIT.fullmatch(candidate) and _COMMIT.fullmatch(consumer)):
        return False
    if len(payload.inputs) != 2 or payload.ref != consumer_dispatch_tag(consumer):
        return False
    base = pair_request_id(candidate, consumer)
    return request_id == base or (
        request_id.startswith(base) and bool(_REDISPATCH_SUFFIX.fullmatch(request_id[len(base):]))
    )


def validate_consumer_run(payload: Any, intent: DispatchIntent, run: dict) -> None:
    candidate = payload.inputs[CANDIDATE_INPUT]
    consumer = payload.inputs["consumer_sha"]
    title = (
        f"platform-release-pin-check {candidate} on {consumer} "
        f"{workflow_dispatch_marker(intent.correlation_id)}"
    )
    if (
        run.get("display_title") != title
        or run.get("head_sha") != consumer
        or run.get("event") != "workflow_dispatch"
        or str(run.get("path") or "").split("@", 1)[0] != _WORKFLOW_PATH
        or (intent.workflow_run_id and str(run.get("id")) != intent.workflow_run_id)
    ):
        raise ConsumerProofRecoveryError(
            "consumer_proof_identity_mismatch",
            f"GitHub run {run.get('id')!r} does not name the recorded workflow, "
            f"dispatch marker and exact Platform/Yoke pair for attempt {intent.attempt}.",
        )


def _lookup(path: str, token: str, *, query: dict | None = None) -> Any:
    try:
        return rest_get(path, token=token, query=query)
    except RestTransportError as exc:
        raise ConsumerProofRecoveryError(
            "consumer_proof_lookup_unavailable", f"GitHub lookup failed for {path}: {exc}"
        ) from exc


def verify_consumer_tag(payload: Any, token: str) -> None:
    """A replacement may use only the existing tag on the bound commit."""
    expected_ref = f"refs/tags/{payload.ref}"
    expected_sha = payload.inputs["consumer_sha"]
    try:
        ref, sha = read_lightweight_tag(payload.repo, payload.ref, token=token)
    except RestTransportError as exc:
        raise ConsumerProofRecoveryError(
            "consumer_proof_tag_unverified", f"GitHub could not read {expected_ref}: {exc}"
        ) from exc
    if ref != expected_ref or sha != expected_sha:
        raise ConsumerProofRecoveryError(
            "consumer_proof_tag_unverified",
            f"GitHub did not resolve {expected_ref} directly to the bound Platform commit {expected_sha}.",
        )


def _visible_runs(payload: Any, token: str, earliest: datetime) -> tuple[list[dict], bool]:
    """Return seen runs and whether pagination accounted for the entire query."""
    path = f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/runs"
    # Leave room for GitHub and the control plane to disagree on the creation clock.
    created = (earliest - _JOIN_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen: dict[int, dict] = {}
    total = None
    for page in range(1, CORRELATION_SEARCH_PAGES + 1):
        data = _lookup(path, token, query={
            "event": "workflow_dispatch",
            "created": f">={created}",
            "per_page": str(CORRELATION_RUNS_PER_PAGE),
            "page": str(page),
        })
        if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            break
        count = data.get("total_count")
        if type(count) is not int or count < 0 or (total is not None and count != total):
            break
        total = count
        runs = data["workflow_runs"]
        if len(runs) != min(CORRELATION_RUNS_PER_PAGE, total - len(seen)):
            break
        for run in runs:
            if (
                not isinstance(run, dict)
                or type(run.get("id")) is not int
                or run["id"] <= 0
                or run["id"] in seen
                or not isinstance(run.get("display_title"), str)
            ):
                return list(seen.values()), False
            seen[run["id"]] = run
        if len(seen) == total:
            return list(seen.values()), True
    return list(seen.values()), False


def reconcile_consumer_runs(
    payload: Any, latest: DispatchIntent, token: str
) -> tuple[tuple[DispatchIntent, dict, str] | None, bool]:
    """Find an exact usable run, or establish when a missing send can be replaced."""
    attempts = proof_attempts(latest)
    pending = []
    for intent in attempts:
        if (
            intent.actor_id != latest.actor_id
            or intent.authorization_scope != latest.authorization_scope
            or intent.payload_checksum != latest.payload_checksum
            or intent.inputs != payload.inputs
        ):
            raise ConsumerProofRecoveryError(
                "consumer_proof_identity_mismatch",
                f"Recorded attempt {intent.attempt} does not bind the same Platform/Yoke proof.",
            )
        if intent.state == "pending":
            pending.append(intent)
        elif intent.state == "completed":
            run = recorded_run(payload, intent, token)
            validate_consumer_run(payload, intent, run)
            classification = run_classification(run)
            if classification != "no_verdict":
                return (intent, run, classification), False

    if not pending:
        return None, True

    runs, complete = _visible_runs(payload, token, min(intent.created_at for intent in pending))
    usable = None
    latest_without_verdict = None
    for intent in pending:
        marker = workflow_dispatch_marker(intent.correlation_id)
        matches = [run for run in runs if marker in run["display_title"]]
        if len(matches) > 1:
            raise ConsumerProofRecoveryError(
                "consumer_proof_identity_mismatch",
                f"Multiple GitHub runs name the dispatch marker for attempt {intent.attempt}.",
            )
        if matches:
            run = matches[0]
            validate_consumer_run(payload, intent, run)
            classification = run_classification(run)
            if classification != "no_verdict" and usable is None:
                usable = intent, run, classification
            elif classification == "no_verdict" and intent.attempt == latest.attempt:
                latest_without_verdict = intent, run, classification

    if usable is not None:
        return usable, False
    if not complete:
        raise ConsumerProofRecoveryError(
            "consumer_proof_lookup_incomplete",
            "The bounded GitHub lookup could not account for every run in the Platform proof window.",
        )
    if latest_without_verdict is not None:
        return latest_without_verdict, False
    return None, utc_now() - pending[0].created_at >= _JOIN_WINDOW
