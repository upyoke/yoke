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
    client_project_context,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.project_snapshot import (
    ProjectSnapshotScanError,
    identity_sync_payload,
    plan_sync,
)
from yoke_cli.commands.adapters.project_snapshot_incremental import sync_snapshots
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.git_hook_markers import HEAD_RECORDING_GIT_HOOKS
from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.path_snapshot import (
    PathSnapshotSyncPayload,
)

HOOK_WRITE_TIMEOUT_S = 8.0
_RESPONSE_TIMEOUT_MARKER = "exceeded the time limit"

PROJECT_SNAPSHOT_SYNC_USAGE = (
    "yoke project snapshot sync [REPO_ROOT] [--project P] "
    "[--integration-target BRANCH] [--head-only] [--hook GIT_HOOK] "
    "[--session-id S] [--json]"
)


def project_snapshot_sync(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke project snapshot sync",
        description=(
            "Sync server-side path snapshots of this checkout's committed HEAD "
            "plus the integration target. Only files whose blob differs from "
            "a snapshot the server already holds are read and uploaded."
        ),
    )
    parser.add_argument("repo_root", nargs="?", default=None)
    add_project_arg(parser)
    parser.add_argument("--integration-target", default=None)
    parser.add_argument(
        "--head-only",
        action="store_true",
        help=(
            "Record this checkout's HEAD as its lane head only: no "
            "integration target, no file-content scan, no stored snapshot. "
            "The fast re-stamp for a lane whose recorded head went stale."
        ),
    )
    parser.add_argument(
        "--hook",
        dest="hook_name",
        choices=HEAD_RECORDING_GIT_HOOKS,
        help="Hook-safe mode for GIT_HOOK: label failures with it, exit 0.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_SNAPSHOT_SYNC_USAGE)
    if parsed is None:
        return 2

    project = _project_context(parsed.project)
    hook_mode = parsed.hook_name is not None
    # --head-only and the git hook ask for commit identity only: the server
    # records the lane head and stores no snapshot. A full sync stores the
    # inventory, uploading only files the server's base snapshot lacks.
    try:
        plan = plan_sync(
            parsed.repo_root,
            integration_target=parsed.integration_target,
            head_only=parsed.head_only,
        )
        if parsed.head_only and not hook_mode:
            response = _dispatch_sync_payload(
                project=project,
                payload=identity_sync_payload(
                    plan, project_id=project, hook_mode=False
                ),
                session_id=parsed.session_id,
                timeout_s=None,
            )
        else:
            response = sync_snapshots(
                project=project,
                plan=plan,
                contents=not hook_mode,
                hook_mode=hook_mode,
                session_id=parsed.session_id,
                timeout_s=HOOK_WRITE_TIMEOUT_S if hook_mode else None,
            )
    except ProjectSnapshotScanError as exc:
        label = "warning" if hook_mode else "error"
        message = f"{label}: {exc}"
        if hook_mode:
            message = format_hook_diagnostic(parsed.hook_name, message)
        print(message, file=sys.stderr)
        return 0 if hook_mode else 1
    except Exception as exc:
        if hook_mode:
            message = str(exc) or type(exc).__name__
            print(
                format_hook_diagnostic(
                    parsed.hook_name,
                    _failure_warning(
                        message,
                        _write_repair(
                            message,
                            code="",
                            retry_command="",
                            snapshot_repair="yoke project snapshot sync",
                        ),
                    ),
                ),
                file=sys.stderr,
            )
            return 0
        raise
    if hook_mode:
        if not response.success:
            print(
                format_hook_diagnostic(parsed.hook_name, _sync_outcome_line(response)),
                file=sys.stderr,
            )
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
    head_only: bool = False,
    timeout_s: Optional[float] = HOOK_WRITE_TIMEOUT_S,
    retry_command: str = "",
    stderr: TextIO = sys.stderr,
) -> dict[str, Any]:
    project_id = _project_context(project)
    snapshot_repair = _repair_command(project_id, repo_root)
    if project_id is None:
        return _sync_status(
            False,
            "skipped",
            "project context unavailable",
            snapshot_repair,
        )
    try:
        plan = plan_sync(
            repo_root,
            integration_target=integration_target,
            head_only=head_only,
        )
        if head_only:
            # Identity-only callers match the git hook shims: no blob scan,
            # and the server stores no snapshot for them.
            response = _dispatch_sync_payload(
                project=project_id,
                payload=identity_sync_payload(
                    plan, project_id=project_id, hook_mode=True
                ),
                session_id=session_id,
                timeout_s=timeout_s,
            )
        else:
            response = sync_snapshots(
                project=project_id,
                plan=plan,
                contents=True,
                hook_mode=True,
                session_id=session_id,
                timeout_s=timeout_s,
            )
    except ProjectSnapshotScanError as exc:
        return _sync_status(False, "skipped", str(exc), snapshot_repair)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        repair = _write_repair(
            message,
            code="",
            retry_command=retry_command,
            snapshot_repair=snapshot_repair,
        )
        print(_failure_warning(message, repair), file=stderr)
        return _sync_status(True, "failed", message, repair)
    if not response.success:
        deferred = _is_snapshot_deferral(response)
        error = response.error
        message = error.message if error is not None else "snapshot sync failed"
        repair = (
            ""
            if deferred
            else _write_repair(
                message,
                code=getattr(error, "code", "") or "",
                retry_command=retry_command,
                snapshot_repair=snapshot_repair,
            )
        )
        print(_sync_outcome_line(response, repair=repair), file=stderr)
        return _sync_status(
            True,
            "deferred" if deferred else "failed",
            message,
            repair,
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


def _write_repair(
    message: str,
    *,
    code: str,
    retry_command: str,
    snapshot_repair: str,
) -> str:
    # Only a response-deadline timeout recommends retry. Auth/validation
    # refusals keep an empty repair so the named original error stands.
    if _RESPONSE_TIMEOUT_MARKER in message:
        return retry_command
    if str(code).startswith("snapshot_") or not code:
        return snapshot_repair
    return ""


def _failure_warning(message: str, repair: str) -> str:
    if repair:
        return f"warning: snapshot sync failed; repair with `{repair}`: {message}"
    return f"warning: snapshot sync failed: {message}"


def _sync_outcome_line(response: Any, *, repair: Optional[str] = None) -> str:
    """Stderr line for an unsuccessful sync response.

    A by-design deferral (a large snapshot kept off the commit / path-claim
    hot path) reads as a calm note — not a scary "FAILED ... repair" warning
    that throws operators off track. Genuine failures keep the warning.
    """
    error = getattr(response, "error", None)
    message = (getattr(error, "message", "") or "") or "snapshot sync failed"
    if _is_snapshot_deferral(response):
        return f"note: {message}"
    if repair is None:
        repair = _write_repair(
            message,
            code=getattr(error, "code", "") or "",
            retry_command="",
            snapshot_repair="yoke project snapshot sync",
        )
    return _failure_warning(message, repair)


def _write_human(response: Any, stdout, stderr) -> None:
    result = response.result or {}
    snapshots = result.get("snapshots") or []
    for row in snapshots:
        status = row.get("status") or "unknown"
        ref = row.get("ref") or "?"
        commit = row.get("commit_sha") or ""
        snapshot_id = row.get("snapshot_id")
        suffix = f" snapshot={snapshot_id}" if snapshot_id is not None else ""
        if base := row.get("base_commit_sha"):
            suffix += f" ({row.get('uploaded_file_count')} files over base {base})"
        print(f"{status}: {ref} {commit}{suffix}", file=stdout)
    for warning in result.get("warnings") or []:
        print(f"warning: {warning}", file=stderr)


__all__ = [
    "HOOK_WRITE_TIMEOUT_S",
    "PROJECT_SNAPSHOT_SYNC_USAGE",
    "project_snapshot_sync",
    "sync_local_snapshot_for_write",
]
