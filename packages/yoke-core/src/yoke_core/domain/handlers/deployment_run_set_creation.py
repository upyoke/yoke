"""Create a release set: one run per flow on one commit, all or nothing."""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error
from yoke_core.domain import deployment_run_create_idempotency as idempotency
from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.deployment_run_target_takeover import TakeoverRefused
from yoke_core.domain.deployment_flow_state import MergeOnlyRunRefused
from yoke_core.domain.deployment_run_target_resolution import (
    EnvironmentRegistryMigrationRequired,
)


def create_refusal(exc: Exception) -> Optional[HandlerOutcome]:
    """The named refusal for a create that raised *exc*, or ``None`` to re-raise."""
    if isinstance(exc, idempotency.IdempotencyKeyConflict):
        return error(exc.code, str(exc), jsonpath="$.payload.idempotency_key")
    if isinstance(exc, EnvironmentRegistryMigrationRequired):
        return error(exc.code, str(exc))
    if isinstance(exc, LookupError):
        return error("not_found", str(exc), jsonpath="$.payload")
    if isinstance(exc, TakeoverRefused):
        return error(exc.code, str(exc), jsonpath="$.payload")
    if isinstance(exc, CarriedWorkSourceUnavailable):
        return error(exc.reason, f"{exc.reason}: {exc.recovery}", jsonpath="$.payload")
    if isinstance(exc, MergeOnlyRunRefused):
        return error(exc.code, str(exc), jsonpath="$.payload.flow")
    if isinstance(exc, ValueError):
        return error("run_create_rejected", str(exc), jsonpath="$.payload")
    return None


def _flows(payload: dict) -> list[str] | HandlerOutcome:
    flows = payload.get("flows")
    if (
        not isinstance(flows, list)
        or not flows
        or not all(isinstance(flow, str) and flow.strip() for flow in flows)
    ):
        return error("payload_invalid", "flows must be a non-empty list of flow names",
                     jsonpath="$.payload.flows")
    clean = [flow.strip() for flow in flows]
    if len(set(clean)) != len(clean):
        return error("payload_invalid", "name each flow once in a release set",
                     jsonpath="$.payload.flows")
    for key, why in (
        ("flow", "send either flow or flows"),
        ("environment", "each flow in a release set owns its target"),
        ("retry_of", "a retry repeats one run; retry each flow's run on its own"),
    ):
        if payload.get(key) is not None:
            return error("payload_invalid", f"{key} is refused with flows: {why}",
                         jsonpath=f"$.payload.{key}")
    if not payload.get("idempotency_key"):
        return error("payload_invalid", "a release set needs an idempotency_key",
                     jsonpath="$.payload.idempotency_key")
    return clean


def handle_release_set_create(
    request: FunctionCallRequest,
    *,
    project: str,
    release_lineage: Optional[str],
    artifact_identity: Optional[str],
    created_by: str,
    created_outcome: Callable[..., HandlerOutcome],
) -> HandlerOutcome:
    """Bind the set's source once, then create every flow's run in one commit.

    Each flow's run is keyed ``KEY:FLOW``. When every key already names its
    run, those runs are returned; otherwise the create replays or creates
    each flow under one transaction, and any refusal leaves nothing behind.
    """
    payload = request.payload or {}
    flows = _flows(payload)
    if isinstance(flows, HandlerOutcome):
        return flows
    if (key_error := idempotency.validate_key(payload["idempotency_key"])) is not None:
        return error("payload_invalid", key_error, jsonpath="$.payload.idempotency_key")
    base_key = payload["idempotency_key"].strip()
    keys = {flow: f"{base_key}:{flow}" for flow in flows}
    requests = {
        flow: idempotency.canonical_request({
            "project": project, "flow": flow, "release_lineage": release_lineage,
            "artifact_identity": artifact_identity, "created_by": created_by,
        })
        for flow in flows
    }
    try:
        replayed = [idempotency.replay_run(project, keys[f], requests[f]) for f in flows]
    except idempotency.IdempotencyKeyConflict as exc:
        return error(exc.code, str(exc), jsonpath="$.payload.idempotency_key")
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.payload")
    if all(replayed):
        created = [(run_id, True, idempotency.BASIS_RECORDED_KEY) for run_id in replayed]
    else:
        created = _create(request, project, flows, keys, requests,
                          release_lineage=release_lineage,
                          artifact_identity=artifact_identity, created_by=created_by)
        if isinstance(created, HandlerOutcome):
            return created
    runs = []
    for flow, (run_id, was_replayed, basis) in zip(flows, created):
        outcome = created_outcome(run_id, retry_source="", project=project, flow=flow,
                                  key=keys[flow], replayed=was_replayed, basis=basis)
        if not outcome.primary_success:
            return outcome
        runs.append(outcome.result_payload)
    return HandlerOutcome(result_payload={"runs": runs}, primary_success=True)


def _create(request, project, flows, keys, requests, **fields) -> Any:
    from yoke_core.domain.deployment_run_ci_tested_source import ReleaseSourceRefused
    from yoke_core.domain.deployment_run_create_set_source import bind_set_source
    from yoke_core.domain.deployment_run_create_write import create_run_set
    from yoke_core.domain.deployment_start_timing import timed_preparation

    try:
        lineage = timed_preparation("create_source", bind_set_source, project, flows,
                                    fields["release_lineage"])
    except ReleaseSourceRefused as exc:
        return error(exc.code, str(exc), jsonpath="$.payload.release_lineage")
    actor_id = request.actor.actor_id
    specs = [
        {
            "flow": flow,
            "release_lineage": (lineage or "").strip() or None,
            "created_by": fields["created_by"].strip(),
            "artifact_identity": fields["artifact_identity"],
            "idempotency_key": keys[flow],
            "create_request": requests[flow],
            "session_id": request.actor.session_id,
            "actor_id": int(actor_id) if str(actor_id or "").isdigit() else None,
        }
        for flow in flows
    ]
    try:
        made = create_run_set(project, specs)
    except Exception as exc:  # noqa: BLE001 - mapped to named refusals below
        if (outcome := create_refusal(exc)) is None:
            raise
        return outcome
    return [(run.run_id, run.replayed, run.idempotency_basis) for run in made]


__all__ = ["create_refusal", "handle_release_set_create"]
