"""Registered Pack catalog, rendered-bundle, and project-report handlers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.pack_catalog import PackError, build_pack_bundle
from yoke_core.domain.pack_projection import (
    PackProjectionError,
    list_project_pack_status,
    report_project_packs,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class PacksCatalogListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str


class PacksCatalogListResponse(BaseModel):
    project_id: int
    project_slug: str
    repository_report: dict[str, Any] | None
    packs: list[dict[str, Any]]


class PacksBundleGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    pack: str
    version: str | None = None
    render_values: dict[str, str] | None = None


class PacksBundleGetResponse(BaseModel):
    bundle_schema: int
    project_id: int
    project_slug: str
    pack: str
    name: str
    description: str
    version: str
    latest_version: str
    dependencies: list[str]
    documentation: str
    settings_schema: dict[str, Any]
    verification: list[dict[str, str]]
    render_values: dict[str, str]
    files: list[dict[str, Any]]
    content_digest: str


class ProjectPackReportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    version: str
    file_count: int


class PacksProjectReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    receipt_digest: str
    packs: list[ProjectPackReportRow]


class PacksProjectReportResponse(BaseModel):
    project_id: int
    project_slug: str
    reported: int
    reported_at: str
    receipt_digest: str


class PacksOperationRequest(BaseModel):
    """Inputs for one machine-local Pack preview or apply."""

    model_config = ConfigDict(extra="forbid")

    project: str
    pack: str
    repo_root: str | None = None
    apply: bool = False
    version: str | None = None
    accepted_current_paths: list[str] = Field(default_factory=list)


class PacksOperationResponse(BaseModel):
    """Reviewable result from a machine-local Pack operation."""

    operation: str
    project_id: int
    project_slug: str
    repo_root: str
    requested_pack: str
    plans: list[dict[str, Any]]
    conflict_count: int
    applied: bool
    receipt: str
    refused: bool = False
    projection: dict[str, Any] | None = None
    projection_warning: str | None = None


def handle_packs_catalog_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = PacksCatalogListRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = list_project_pack_status(conn, project=parsed.project)
    except PackProjectionError as exc:
        return _failure("packs_catalog_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_packs_bundle_get(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = PacksBundleGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = build_pack_bundle(
            conn,
            project=parsed.project,
            pack=parsed.pack,
            version=parsed.version,
            render_values=parsed.render_values,
        )
    except (LookupError, PackError) as exc:
        return _failure("pack_bundle_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_packs_project_report(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = PacksProjectReportRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = report_project_packs(
            conn,
            project=parsed.project,
            packs=[row.model_dump() for row in parsed.packs],
            receipt_digest=parsed.receipt_digest,
        )
        conn.commit()
    except PackProjectionError as exc:
        conn.rollback()
        return _failure("pack_report_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_packs_get(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_pack_operation(request, operation="get")


def handle_packs_update(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_pack_operation(request, operation="update")


def _handle_pack_operation(
    request: FunctionCallRequest,
    *,
    operation: str,
) -> HandlerOutcome:
    try:
        parsed = PacksOperationRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_cli.packs import PackClientError, run_pack_operation

    try:
        result = run_pack_operation(
            parsed.repo_root,
            project=parsed.project,
            pack=parsed.pack,
            operation=operation,
            apply=parsed.apply,
            version=parsed.version,
            session_id=request.actor.session_id or None,
            accepted_current_paths=parsed.accepted_current_paths,
        )
    except PackClientError as exc:
        return _failure("pack_operation_failed", str(exc))
    return HandlerOutcome(primary_success=True, result_payload=result)


def _invalid(exc: ValidationError) -> HandlerOutcome:
    return _failure("payload_invalid", safe_validation_message(exc))


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


__all__ = [
    "PacksBundleGetRequest",
    "PacksBundleGetResponse",
    "PacksCatalogListRequest",
    "PacksCatalogListResponse",
    "PacksOperationRequest",
    "PacksOperationResponse",
    "PacksProjectReportRequest",
    "PacksProjectReportResponse",
    "handle_packs_bundle_get",
    "handle_packs_catalog_list",
    "handle_packs_get",
    "handle_packs_project_report",
    "handle_packs_update",
]
