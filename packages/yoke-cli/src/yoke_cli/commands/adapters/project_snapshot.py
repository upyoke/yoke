"""Adapter for ``yoke project snapshot sync``."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import Any, List, Optional, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    attach_field_note_footer,
    client_project_context,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.project_snapshot import (
    ProjectSnapshotScanError,
    build_sync_payload,
)
from yoke_cli.commands.adapters.project_snapshot_chunked import (
    dispatch_chunked_sync_payload,
    needs_https_chunking,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.path_snapshot import (
    PathSnapshotSyncPayload,
)

PROJECT_SNAPSHOT_SYNC_USAGE = (
    "yoke project snapshot sync [REPO_ROOT] [--project P] "
    "[--integration-target BRANCH] [--head-only] [--hook] "
    "[--session-id S] [--json]"
)


def project_snapshot_sync(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project snapshot sync",
        description=(
            "Scan committed git tree state in this checkout and sync "
            "server-side path snapshots for HEAD plus the integration target."
        ),
    )
    parser.add_argument("repo_root", nargs="?", default=None)
    add_project_arg(parser)
    parser.add_argument("--integration-target", default=None)
    parser.add_argument("--head-only", action="store_true")
    parser.add_argument(
        "--hook", dest="hook_mode", action="store_true",
        help="Hook-safe mode: report failures but exit zero.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_SNAPSHOT_SYNC_USAGE)
    if parsed is None:
        return 2

    project = _project_context(parsed.project)
    try:
        payload = build_sync_payload(
            parsed.repo_root,
            project_id=project,
            integration_target=parsed.integration_target,
            head_only=parsed.head_only,
            hook_mode=parsed.hook_mode,
        )
    except ProjectSnapshotScanError as exc:
        label = "warning" if parsed.hook_mode else "error"
        print(f"{label}: {exc}", file=sys.stderr)
        return 0 if parsed.hook_mode else 1
    try:
        if needs_https_chunking(payload):
            response = dispatch_chunked_sync_payload(
                project=project,
                payload=payload,
                session_id=parsed.session_id,
                timeout_s=8.0 if parsed.hook_mode else None,
            )
        else:
            response = _dispatch_sync_payload(
                project=project,
                payload=payload,
                session_id=parsed.session_id,
                timeout_s=8.0 if parsed.hook_mode else None,
            )
    except Exception as exc:
        if parsed.hook_mode:
            print(
                "warning: snapshot sync failed; repair with "
                "`yoke project snapshot sync`: "
                f"{exc}",
                file=sys.stderr,
            )
            return 0
        raise
    if parsed.hook_mode:
        if not response.success:
            print(_sync_outcome_line(response), file=sys.stderr)
        return 0
    return emit_response(
        response,
        json_mode=parsed.json_mode,
        human_writer=_write_human,
    )


def sync_local_snapshot_for_write(
    *,
    project: Optional[str],
    repo_root: Optional[str] = None,
    integration_target: Optional[str],
    session_id: Optional[str],
    stderr: TextIO = sys.stderr,
) -> dict[str, Any]:
    project_id = _project_context(project)
    repair_command = _repair_command(project_id, repo_root)
    if project_id is None:
        return _sync_status(
            False, "skipped", "project context unavailable", repair_command,
        )
    try:
        payload = build_sync_payload(
            repo_root,
            project_id=project_id,
            integration_target=integration_target,
            hook_mode=True,
        )
    except ProjectSnapshotScanError as exc:
        return _sync_status(False, "skipped", str(exc), repair_command)
    try:
        if needs_https_chunking(payload):
            response = dispatch_chunked_sync_payload(
                project=project_id, payload=payload,
                session_id=session_id, timeout_s=8.0,
            )
        else:
            response = _dispatch_sync_payload(
                project=project_id, payload=payload,
                session_id=session_id, timeout_s=8.0,
            )
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        _write_claim_sync_warning(message, stderr)
        return _sync_status(True, "failed", message, repair_command)
    if not response.success:
        deferred = _is_snapshot_deferral(response)
        print(_sync_outcome_line(response), file=stderr)
        message = (
            response.error.message
            if response.error is not None
            else "snapshot sync failed"
        )
        return _sync_status(
            True,
            "deferred" if deferred else "failed",
            message,
            "" if deferred else repair_command,
        )
    return _sync_status(True, "ok", "", "")


def _sync_status(
    attempted: bool,
    status: str,
    message: str,
    repair_command: str,
) -> dict[str, Any]:
    return {
        "attempted": attempted,
        "status": status,
        "message": message,
        "repair_command": repair_command,
    }


def _repair_command(project: Optional[str], repo_root: Optional[str]) -> str:
    command = ["yoke", "project", "snapshot", "sync"]
    if repo_root:
        command.append(repo_root)
    if project:
        command.extend(["--project", str(project)])
    return shlex.join(command)


def _project_context(explicit: Optional[str]) -> Optional[str]:
    resolved = client_project_context(explicit)
    return str(resolved) if resolved is not None else None


def _dispatch_sync_payload(
    *,
    project: Optional[str],
    payload: PathSnapshotSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
):
    ensure_handlers_loaded()
    return call_dispatcher(
        function_id="project.snapshot.sync",
        target=TargetRef(kind="global", project_id=project),
        payload=payload.model_dump(mode="json"),
        actor=build_actor(session_id=session_id),
        timeout_s=timeout_s,
    )


SNAPSHOT_DEFERRED_CODE = "snapshot_sync_deferred"


def _is_snapshot_deferral(response: Any) -> bool:
    error = getattr(response, "error", None)
    return getattr(error, "code", "") == SNAPSHOT_DEFERRED_CODE


def _sync_outcome_line(response: Any) -> str:
    """Stderr line for an unsuccessful sync response.

    A by-design deferral (a large snapshot kept off the commit / path-claim
    hot path) reads as a calm note — not a scary "FAILED ... repair" warning
    that throws operators off track. Genuine failures keep the warning.
    """
    error = getattr(response, "error", None)
    message = (getattr(error, "message", "") or "") or "snapshot sync failed"
    if _is_snapshot_deferral(response):
        return f"note: {message}"
    return (
        "warning: snapshot sync failed; repair with "
        f"`yoke project snapshot sync`: {message}"
    )


def _write_claim_sync_warning(message: str, stderr: TextIO) -> None:
    print(
        "warning: snapshot sync before path-claim write failed; repair with "
        "`yoke project snapshot sync`: "
        f"{message}",
        file=stderr,
    )


def _write_human(response: Any, stdout, stderr) -> None:
    result = response.result or {}
    snapshots = result.get("snapshots") or []
    for row in snapshots:
        status = row.get("status") or "unknown"
        ref = row.get("ref") or "?"
        commit = row.get("commit_sha") or ""
        snapshot_id = row.get("snapshot_id")
        suffix = f" snapshot={snapshot_id}" if snapshot_id is not None else ""
        print(f"{status}: {ref} {commit}{suffix}", file=stdout)
    for warning in result.get("warnings") or []:
        print(f"warning: {warning}", file=stderr)


__all__ = [
    "PROJECT_SNAPSHOT_SYNC_USAGE",
    "project_snapshot_sync",
    "sync_local_snapshot_for_write",
]
