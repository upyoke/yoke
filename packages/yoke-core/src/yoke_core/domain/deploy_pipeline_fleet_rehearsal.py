"""Rehearse a hosted release the fleet receipts do not yet cover.

Coverage is decided from what the release commit carries: its ordered
migration history entries and its boot-converge schema shape. An entry that
transforms rows without touching a table, column or index moves no schema
shape, so a shape-only question answers "covered" for precisely the entries a
rehearsal exists to catch — the ones that must be idempotent against their own
output and must write through their readers' canonical serializer. Asking both
questions makes an unrehearsed entry visible the way an unrehearsed shape
already was.

A receipt is stale for an environment when that environment's coverage
document does not record something this release commit carries: any history
entry name, or the schema-shape digest. It is not stale because the shape
moved, and it does not age out — coverage is the union the store accumulates,
so entries the fleet rehearsed on an earlier release stay covered and are not
rehearsed again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deploy_pipeline_environment
from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain.migration_preflight_receipt_store import read_coverage
from yoke_core.domain.schema_shape_source import (
    SchemaShapeSourceError,
    digest_schema_shape_commit,
)

HOSTED_RELEASE_STAGE = "hosted-release"
HOSTED_RELEASE_WORKFLOW = "platform-release-bridge.yml"

#: Registered read serving a project's declared migration history location.
CAPABILITY_FUNCTION_ID = "projects.capability_settings.get"


def ensure_before_dispatch(
    config: Mapping[str, Any],
    *,
    stage_name: str,
    project: str,
    environment: str,
    repository: str,
    release_lineage: str,
) -> tuple[int, str]:
    """Run and record fleet rehearsal for whatever this release is missing."""
    if not _owns_fleet_rehearsal(config, stage_name):
        return 0, ""
    if not environment.strip():
        return 1, "hosted release fleet rehearsal requires a target environment"

    release_sha, lineage_error = _release_sha(
        release_lineage,
        repository,
    )
    if lineage_error:
        return 1, lineage_error
    try:
        schema_digest = digest_schema_shape_commit(Path(repository or "."), release_sha)
    except SchemaShapeSourceError as exc:
        return 1, f"hosted release schema digest unavailable: {exc}"

    history, history_error = _release_history(project, repository, release_sha)
    if history_error:
        return 1, history_error

    values, read_error = _coverage(project, environment, history, schema_digest)
    if read_error:
        return 1, read_error
    target = receipt.target_environment_for_admin_env(environment)
    missing = _uncovered_summary(history, schema_digest, values)
    if not missing:
        print(
            f"  Fleet rehearsal: covered for {target} "
            f"({len(history)} history entries, schema shape {schema_digest}); "
            "skipping"
        )
        return 0, ""

    receipt_environment = deploy_pipeline_environment.release_control_plane_env()
    if not receipt_environment or receipt_environment == "unbound":
        return 1, "hosted release fleet rehearsal has no release control plane"
    print(
        f"  Fleet rehearsal: uncovered for {target} ({missing}); "
        "running before dispatch"
    )
    rc = _run_preflight(
        [
            environment,
            "--record-receipt",
            "--product-sha",
            release_sha,
            "--receipt-env",
            receipt_environment,
        ]
    )
    if rc != 0:
        return rc, (
            "hosted release fleet rehearsal failed before dispatch "
            f"(exit code {rc})"
        )

    values, read_error = _coverage(project, environment, history, schema_digest)
    if read_error:
        return 1, read_error
    still_missing = _uncovered_summary(history, schema_digest, values)
    if still_missing:
        return 1, (
            "fleet rehearsal passed but its receipt does not cover "
            f"{still_missing}; the selected engine source may differ from "
            "the release commit"
        )
    print(
        f"  Fleet rehearsal: receipt covers this release for {target} "
        f"({len(history)} history entries, schema shape {schema_digest})"
    )
    return 0, ""


def _uncovered_summary(
    history: Sequence[str], schema_digest: str, values: Mapping[str, Any]
) -> str:
    """Name what this environment has never rehearsed; empty when nothing."""
    missing_entries = receipt.uncovered(history, values)
    missing_shape = receipt.uncovered_schema_shape(schema_digest, values)
    parts = []
    if missing_entries:
        parts.append(
            f"{len(missing_entries)} history "
            f"{'entry' if len(missing_entries) == 1 else 'entries'} "
            f"({', '.join(missing_entries)})"
        )
    if missing_shape:
        parts.append(f"schema shape {schema_digest}")
    return " and ".join(parts)


def _owns_fleet_rehearsal(config: Mapping[str, Any], stage_name: str) -> bool:
    """True only for the hosted bridge contract that builds Yoke releases."""
    return (
        stage_name == HOSTED_RELEASE_STAGE
        and str(config.get("workflow") or "") == HOSTED_RELEASE_WORKFLOW
    )


def _release_sha(lineage: str, repository: str) -> tuple[str, str]:
    from yoke_core.domain.deploy_pipeline_github_workflow import (
        _resolve_release_lineage_sha,
    )

    return _resolve_release_lineage_sha(lineage, repository, "")


def _coverage(
    project: str,
    environment: str,
    history: Sequence[str],
    schema_digest: str,
) -> tuple[dict[str, Any], str]:
    """The environment's coverage for this release, or why it is unknown."""
    values, unreadable = read_coverage(
        project=project,
        environment=environment,
        paths=receipt.coverage_paths(history, schema_digest),
    )
    if unreadable:
        return {}, f"could not read fleet rehearsal receipts: {unreadable}"
    return values, ""


def _release_history(
    project: str, repository: str, release_sha: str
) -> tuple[tuple[str, ...], str]:
    """Ordered history entry names the release commit carries, or why not.

    Read from the commit rather than from this process's installed history,
    for the same reason the schema-shape digest is: the control plane
    dispatching a release is not necessarily running the build it dispatches.
    """
    from yoke_core.domain.migration_history import HistoryError
    from yoke_core.domain.migration_history_integration import history_names_at_ref

    modules_dir, capability_error = _modules_dir(project)
    if capability_error:
        return (), capability_error
    try:
        return (
            history_names_at_ref(Path(repository or "."), release_sha, modules_dir),
            "",
        )
    except HistoryError as exc:
        return (), (
            "hosted release migration history unavailable for commit "
            f"{release_sha}: {exc}"
        )


def _modules_dir(project: str) -> tuple[str, str]:
    """The project's declared history directory, or why it is unknown.

    Declared, never assumed: the directory is where this project keeps its
    ordered history, and a guess that missed it would report a release as
    carrying no entries — the same silent pass this gate exists to remove.
    """
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.migration_model_capability import (
        MigrationModelCapabilityError,
        resolve_model,
        validate,
    )

    unknown = (
        f"could not resolve the migration_model history directory for "
        f"project {project!r}"
    )
    try:
        response = call_dispatcher(
            function_id=CAPABILITY_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": project, "cap_type": "migration_model"},
        )
    except Exception as exc:  # noqa: BLE001 - unreadable declaration fails closed
        return "", f"{unknown}: {exc}"
    if not response.success:
        detail = (
            response.error.message
            if response.error is not None
            else "capability read refused"
        )
        return "", f"{unknown}: {detail}"
    result = response.result if isinstance(response.result, Mapping) else {}
    try:
        capability = validate(json.loads(str(result.get("settings_json") or "")))
        model_name = str(capability.get("default_model") or "")
        if not model_name:
            return "", (
                f"{unknown}: the capability declares no default_model, so the "
                "release cannot say which history it carries"
            )
        config = (resolve_model(capability, model_name).get("runner") or {}).get(
            "config"
        ) or {}
        modules_dir = str(config.get("modules_dir") or "")
    except (
        KeyError,
        MigrationModelCapabilityError,
        TypeError,
        ValueError,
    ) as exc:
        return "", f"{unknown}: {exc}"
    if not modules_dir:
        return "", f"{unknown}: the declared model has no modules_dir"
    return modules_dir, ""


def _run_preflight(args: list[str]) -> int:
    """Execute through the same raw/progress watcher operators use directly."""
    from yoke_core.tools import watch_preflight

    return watch_preflight.main(["--", *args])


__all__ = [
    "CAPABILITY_FUNCTION_ID",
    "HOSTED_RELEASE_STAGE",
    "HOSTED_RELEASE_WORKFLOW",
    "ensure_before_dispatch",
]
