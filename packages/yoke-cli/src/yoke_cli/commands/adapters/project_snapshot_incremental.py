"""Sync a checkout's snapshots, uploading only what the server lacks.

Per commit: offer the server a list of ancestor commits before scanning
anything. A commit the server already holds settles there. Otherwise the
server names a base it holds and only files whose blob differs from that
base are read and uploaded; without a base the full inventory is. The
integration target goes first when commits differ so HEAD can build on it.
Identical commits send HEAD first to record the lane before reusing content.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from yoke_cli.commands.adapters.project_snapshot_chunk_results import (
    alias_snapshot_row,
    begin_settled_row,
    upload_result,
)
from yoke_cli.commands.adapters.project_snapshot_chunk_sizing import (
    active_transport_is_https,
    delta_fits_one_request,
)
from yoke_cli.commands.adapters.project_snapshot_chunked import (
    offer_begin,
    upload_snapshot,
)
from yoke_cli.project_snapshot.sync_refs import SyncPlan, SyncRef
from yoke_cli.project_snapshot.tree_delta import (
    SnapshotUpload,
    base_candidates,
    scan_delta,
    scan_full,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.path_snapshot_chunks import SNAPSHOT_BASE_MISMATCH_CODE


def sync_snapshots(
    *,
    project: Optional[str],
    plan: SyncPlan,
    contents: bool,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    """Record every commit in ``plan``; ``contents`` stores its inventory.

    In hook mode a full inventory too large for one request over HTTPS is
    deferred to the next ``yoke project snapshot sync``; a delta always
    uploads, since it is what keeps the hot path short.
    """
    defer = hook_mode and active_transport_is_https()
    rows: Dict[str, Dict[str, Any]] = {}
    by_commit: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    project_id: Any = None
    upload_order = [ref for ref in (plan.integration, plan.head) if ref]
    if plan.integration and plan.integration.commit_sha == plan.head.commit_sha:
        # HEAD carries lane identity even when its content matches the base.
        upload_order.reverse()
    for ref in upload_order:
        if ref.commit_sha in by_commit:
            rows[ref.label] = alias_snapshot_row(
                ref.label, ref.commit_sha, by_commit[ref.commit_sha]
            )
            warnings.extend(ref.warnings)
            continue
        response = _sync_ref(
            project=project,
            plan=plan,
            ref=ref,
            contents=contents,
            defer=defer,
            hook_mode=hook_mode,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        if not response.success:
            return response
        result = response.result or {}
        project_id = result.get("project_id", project_id)
        warnings.extend(result.get("warnings") or [])
        for row in result.get("snapshots") or []:
            rows.setdefault(ref.label, row)
            by_commit.setdefault(ref.commit_sha, row)
    return FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": project_id,
            "snapshots": [rows[ref.label] for ref in plan.refs if ref.label in rows],
            "warnings": warnings,
        },
    )


def _sync_ref(
    *,
    project: Optional[str],
    plan: SyncPlan,
    ref: SyncRef,
    contents: bool,
    defer: bool,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    repo_root = str(plan.repo_root)
    upload_id = uuid4().hex
    integration_sha = (
        plan.integration.commit_sha if plan.integration and ref is plan.head else None
    )
    offer = offer_begin(
        project=project,
        repo_root=repo_root,
        upload_id=upload_id,
        ref=ref,
        base_candidates=(
            base_candidates(plan.repo_root, ref.commit_sha, integration_sha)
            if contents
            else []
        ),
        contents_included=contents,
        hook_mode=hook_mode,
        session_id=session_id,
        timeout_s=timeout_s,
    )
    if not offer.success:
        return offer
    result = offer.result or {}
    settled = begin_settled_row(ref.label, ref.commit_sha, result)
    if settled is not None:
        return upload_result(result, [settled], result.get("warnings") or [])
    if not contents:
        return _unexpected_begin(ref, result)
    # A server that predates base offers omits ``base_commit_sha`` and staged
    # an empty upload under this id; the full upload below restages it.
    base = result.get("base_commit_sha")
    upload: Optional[SnapshotUpload] = None
    if base:
        upload = scan_delta(plan.repo_root, ref, str(base))
        assert upload.delta is not None
        if not delta_fits_one_request(
            upload.delta, project=project, repo_root=repo_root, upload_id=upload_id
        ):
            upload = None
    upload = upload or scan_full(plan.repo_root, ref)
    send = dict(
        project=project,
        repo_root=repo_root,
        hook_mode=hook_mode,
        session_id=session_id,
        timeout_s=timeout_s,
    )
    response = upload_snapshot(
        upload_id=upload_id,
        upload=upload,
        defer_multi_chunk=defer and upload.delta is None,
        **send,
    )
    if upload.delta is None or not _base_mismatch(response):
        return _annotated(response, upload)
    mismatch = response.error.message if response.error else ""
    full = scan_full(plan.repo_root, ref)
    response = upload_snapshot(
        upload_id=uuid4().hex, upload=full, defer_multi_chunk=defer, **send
    )
    if response.success:
        (response.result or {}).setdefault("warnings", []).append(
            f"incremental snapshot sync of {ref.label} was refused ({mismatch}); "
            "uploaded the full inventory instead"
        )
    return _annotated(response, full)


def _base_mismatch(response: FunctionCallResponse) -> bool:
    if response.success or response.error is None:
        return False
    return response.error.code == SNAPSHOT_BASE_MISMATCH_CODE


def _annotated(
    response: FunctionCallResponse, upload: SnapshotUpload
) -> FunctionCallResponse:
    """Name, on each row, how many files went up and over which base."""
    if not response.success:
        return response
    result = dict(response.result or {})
    base = upload.delta.base_commit_sha if upload.delta else None
    result["snapshots"] = [
        {**row, "base_commit_sha": base, "uploaded_file_count": len(upload.files)}
        for row in result.get("snapshots") or []
    ]
    return response.model_copy(update={"result": result})


def _unexpected_begin(ref: SyncRef, result: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="snapshot_sync_failed",
            message=(
                f"identity-only sync of {ref.label} was not settled at begin "
                f"(status {result.get('status')!r})"
            ),
            recovery_hint="Repair with `yoke project snapshot sync`.",
        ),
    )


__all__ = ["sync_snapshots"]
