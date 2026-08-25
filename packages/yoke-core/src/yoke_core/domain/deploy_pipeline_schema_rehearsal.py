"""Rehearse an uncovered hosted-release schema shape before dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import deploy_pipeline_environment
from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain.schema_shape_source import (
    SchemaShapeSourceError,
    digest_schema_shape_commit,
)

HOSTED_RELEASE_STAGE = "hosted-release"
HOSTED_RELEASE_WORKFLOW = "platform-release-bridge.yml"
RECEIPT_QUERY_LIMIT = 500


def ensure_before_dispatch(
    config: Mapping[str, Any],
    *,
    stage_name: str,
    project: str,
    environment: str,
    repository: str,
    release_lineage: str,
) -> tuple[int, str]:
    """Run and record fleet rehearsal when the release digest is uncovered."""
    if not _owns_schema_rehearsal(config, stage_name):
        return 0, ""
    if not environment.strip():
        return 1, "hosted release schema rehearsal requires a target environment"

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

    rows, read_error = _receipt_rows(project)
    if read_error:
        return 1, read_error
    if not receipt.uncovered_schema_shape(schema_digest, rows, environment):
        print(
            "  Fleet schema rehearsal: covered for "
            f"{receipt.target_environment_for_admin_env(environment)} "
            f"({schema_digest}); skipping"
        )
        return 0, ""

    receipt_environment = deploy_pipeline_environment.release_control_plane_env()
    if not receipt_environment or receipt_environment == "unbound":
        return 1, "hosted release schema rehearsal has no release control plane"
    admin_environment = receipt.admin_connection_for_environment(environment)
    print(
        "  Fleet schema rehearsal: uncovered for "
        f"{receipt.target_environment_for_admin_env(environment)} "
        f"({schema_digest}); running before dispatch"
    )
    rc = _run_preflight(
        [
            admin_environment,
            "--record-receipt",
            "--product-sha",
            release_sha,
            "--receipt-env",
            receipt_environment,
        ]
    )
    if rc != 0:
        return rc, (
            "hosted release fleet schema rehearsal failed before dispatch "
            f"(exit code {rc})"
        )

    rows, read_error = _receipt_rows(project)
    if read_error:
        return 1, read_error
    if receipt.uncovered_schema_shape(schema_digest, rows, environment):
        return 1, (
            "fleet rehearsal passed but its receipt does not cover release "
            f"schema shape {schema_digest}; the selected engine source may "
            "differ from the release commit"
        )
    print(
        f"  Fleet schema rehearsal: receipt covers release schema shape {schema_digest}"
    )
    return 0, ""


def _owns_schema_rehearsal(config: Mapping[str, Any], stage_name: str) -> bool:
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


def _receipt_rows(project: str) -> tuple[list[dict[str, Any]], str]:
    try:
        response = call_dispatcher(
            function_id="events.query.run",
            target=TargetRef(kind="global"),
            payload={
                "event_name": receipt.EVENT_NAME,
                "project": project,
                "limit": RECEIPT_QUERY_LIMIT,
            },
        )
    except Exception as exc:  # noqa: BLE001 - unreadable evidence fails closed
        return [], f"could not read fleet schema rehearsal receipts: {exc}"
    if not response.success:
        detail = (
            response.error.message
            if response.error is not None
            else "receipt query refused"
        )
        return [], f"could not read fleet schema rehearsal receipts: {detail}"
    result = response.result if isinstance(response.result, Mapping) else {}
    rows = result.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return [], "could not read fleet schema rehearsal receipts: malformed rows"
    return rows, ""


def _run_preflight(args: list[str]) -> int:
    """Execute through the same raw/progress watcher operators use directly."""
    from yoke_core.tools import watch_preflight

    return watch_preflight.main(["--", *args])


__all__ = [
    "HOSTED_RELEASE_STAGE",
    "HOSTED_RELEASE_WORKFLOW",
    "ensure_before_dispatch",
]
