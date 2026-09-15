"""Registered creation of itemless deployment runs and pinned retries."""

from __future__ import annotations

import json
from collections.abc import Mapping

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import (
    error,
    pipe_to_dict,
    require_global,
)
from yoke_core.domain.deploy_lock import deploy_lock_refusal
from yoke_core.domain.deployment_run_retry_membership import (
    candidate_mismatch_refusal,
    inherit_retry_membership,
)
from yoke_core.domain.deployment_run_target_resolution import (
    EnvironmentRegistryMigrationRequired,
)


def _retry_candidate(run_id: str, *, project: str, flow: str) -> tuple[str, str | None]:
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    raw = cmd_get(run_id)
    if raw is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    source = pipe_to_dict(raw, RUN_FIELDS)
    if source["project"] != project or source["flow"] != flow:
        raise ValueError(
            f"retry source {run_id!r} belongs to project "
            f"{source['project']!r}, flow {source['flow']!r}"
        )
    if source["status"] not in {"failed", "cancelled"}:
        raise ValueError(
            f"retry source {run_id!r} has non-terminal status {source['status']!r}"
        )
    lineage = (source["release_lineage"] or "").strip()
    if not lineage:
        raise ValueError(f"retry source {run_id!r} has no pinned release lineage")
    artifact = str(source.get("artifact_identity") or "").strip() or None
    return lineage, artifact


def handle_deployment_run_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Create a zero-member run, optionally reusing a terminal run's lineage."""
    invalid = require_global(request, "deployment_runs.create")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    flow = payload.get("flow")
    environment = payload.get("environment")
    release_lineage = payload.get("release_lineage")
    retry_of = payload.get("retry_of")
    artifact_identity = payload.get("artifact_identity")
    created_by = payload.get("created_by") or "operator"
    for key, value, required in (
        ("project", project, True),
        ("flow", flow, True),
        ("environment", environment, False),
        ("release_lineage", release_lineage, False),
        ("retry_of", retry_of, False),
        ("artifact_identity", artifact_identity, False),
        ("created_by", created_by, True),
    ):
        if required and (not isinstance(value, str) or not value.strip()):
            return error(
                "payload_invalid",
                f"{key} must be a non-empty string",
                jsonpath=f"$.payload.{key}",
            )
        if not required and value is not None and not isinstance(value, str):
            return error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )
    if artifact_identity:
        try:
            artifact = json.loads(artifact_identity)
        except (TypeError, ValueError) as exc:
            return error(
                "payload_invalid",
                f"artifact_identity must be valid JSON: {exc}",
                jsonpath="$.payload.artifact_identity",
            )
        if not isinstance(artifact, Mapping):
            return error(
                "payload_invalid",
                "artifact_identity must be a JSON object",
                jsonpath="$.payload.artifact_identity",
            )
        artifact_identity = json.dumps(artifact, sort_keys=True, separators=(",", ":"))

    clean_project = project.strip()
    clean_flow = flow.strip()
    retry_source = retry_of.strip() if retry_of else ""

    lock_error = deploy_lock_refusal(
        clean_project,
        operation="deployment_runs.create",
        session_id=request.actor.session_id,
    )
    if lock_error is not None:
        return error("deploy_lock_required", lock_error)

    try:
        if retry_source:
            source_lineage, source_artifact = _retry_candidate(
                retry_source,
                project=clean_project,
                flow=clean_flow,
            )
            # A retry inherits the failed run's membership, which is only
            # sound while it is the same candidate. An explicitly named
            # revision or artifact is therefore an assertion about which
            # candidate is being retried, and a wrong one is a replacement
            # release rather than a retry.
            if mismatch := candidate_mismatch_refusal(
                source_lineage,
                source_artifact,
                release_lineage=(release_lineage or source_lineage),
                artifact_identity=(artifact_identity or source_artifact),
            ):
                return error("retry_candidate_mismatch", mismatch, jsonpath="$.payload")
            release_lineage, artifact_identity = source_lineage, source_artifact
        from yoke_core.domain.deployment_runs_crud_mutate import cmd_create_run

        create_kwargs = {
            "environment": (environment or "").strip() or None,
            "release_lineage": (release_lineage or "").strip() or None,
            "created_by": created_by.strip(),
        }
        if artifact_identity is not None:
            create_kwargs["artifact_identity"] = artifact_identity
        created_run_id = cmd_create_run(clean_project, clean_flow, **create_kwargs)
    except EnvironmentRegistryMigrationRequired as exc:
        return error(exc.code, str(exc))
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.payload")
    except ValueError as exc:
        return error("run_create_rejected", str(exc), jsonpath="$.payload")

    inherited_items: tuple[int, ...] = ()
    if retry_source:
        inherited_items = inherit_retry_membership(retry_source, created_run_id)

    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    created = pipe_to_dict(cmd_get(created_run_id), RUN_FIELDS)
    return HandlerOutcome(
        result_payload={
            "run_id": created_run_id,
            "retry_of": retry_source or None,
            "inherited_item_ids": list(inherited_items),
            "project": created.get("project") or clean_project,
            "flow": created.get("flow") or clean_flow,
            "target_tier": created.get("target_tier") or None,
            "target_environment": created.get("target_environment") or None,
            "release_lineage": created.get("release_lineage") or None,
            "artifact_identity": created.get("artifact_identity") or None,
            "status": created.get("status") or "created",
        },
        primary_success=True,
    )


__all__ = ["handle_deployment_run_create"]
