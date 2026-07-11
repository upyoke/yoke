"""CLI surface for emitting structured events into the Yoke event log.

Handles CLI argument parsing, session/project fallback resolution,
envelope construction, registry validation, and write-side severity
filtering. Delegates persistence to :mod:`yoke_core.domain.events_crud`.

Context-payload helpers (truncation, integer normalisation, error-context
validation, JSON parsing) live in :mod:`emit_event_context`. Argument
parser construction and :class:`UsageError` live in
:mod:`emit_event_parser` and are re-exported below for callers that
import them from this module.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend, events_crud
from yoke_core.domain.emit_event_context import (
    MAX_ENVELOPE_BYTES,
    _normalize_int,
    _parse_context_payload,
    _validate_error_context,
)
from yoke_core.domain.emit_event_parser import (
    EmitEventArgumentParser,
    UsageError,
    build_parser,
)
from yoke_core.domain.events import isolation_gate_blocks
from yoke_core.domain.yok_n_parser import parse_item_id


__all__ = [
    "EmitEventArgumentParser",
    "UsageError",
    "build_parser",
    "emit",
    "main",
]


def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> Optional[str]:
    """Resolve DB path via :func:`db_helpers.resolve_db_path`, or ``None``."""
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        return resolve_db_path()
    except (FileNotFoundError, ImportError, RuntimeError):
        return None


def _item_lookup_id(
    value: Optional[str],
    *,
    project: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[str]:
    """Resolve an event item reference to the numeric ``items.id`` form."""
    if value is None:
        return None
    try:
        return str(parse_item_id(value, project=project, conn=conn))
    except Exception:
        return events_crud.normalize_event_item_id(value)


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for env_name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        value = os.environ.get(env_name)
        if value:
            return value
    return f"{int(time.time())}-{os.getpid()}"


def _resolve_item_project(item_id: Optional[str]) -> Optional[str]:
    if not item_id:
        return None
    conn = None
    try:
        conn = db_backend.connect()
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        lookup_id = _item_lookup_id(item_id, conn=conn)
        if lookup_id is None:
            return None
        row = conn.execute(
            f"""
            SELECT p.slug
            FROM items i
            JOIN projects p ON p.id = i.project_id
            WHERE i.id = {p}
            LIMIT 1
            """,
            (int(lookup_id),),
        ).fetchone()
    except db_backend.operational_error_types():
        return None
    finally:
        if conn is not None:
            conn.close()
    if row and row[0]:
        return str(row[0])
    return None


def _registry_warning(event_name: str) -> tuple[Optional[str], bool]:
    if os.environ.get("YOKE_EVENTS_REGISTRY_VALIDATE", "1") == "0":
        return None, False
    conn = None
    try:
        conn = db_backend.connect()
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM event_registry WHERE event_name = {p}",
            (event_name,),
        ).fetchone()
    except db_backend.operational_error_types():
        # event_registry table absent (minimal/fixture schema) → no warning.
        return None, False
    finally:
        if conn is not None:
            conn.close()
    if not row:
        return (
            f"WARN: event emitter: event '{event_name}' is not registered in event_registry. "
            "Run python3 -m yoke_core.domain.populate_registry or add manually.",
            True,
        )
    status = row[0]
    if status == "deprecated":
        return f"WARN: event emitter: event '{event_name}' is deprecated in the registry", False
    return None, False


def _current_trace_context() -> dict[str, str]:
    try:
        from yoke_core.api.observability import trace_context
    except Exception:
        return {}
    try:
        return trace_context()
    except Exception:
        return {}


def _build_envelope(args: argparse.Namespace, *, event_id: str, session_id: str, project: str, anomaly_flags: Optional[str]) -> dict[str, Any]:
    detail = _parse_context_payload(args.context, label="context")
    error = _parse_context_payload(args.error_context, label="error-context")
    context = None
    if detail is not None or error is not None:
        context = {}
        if detail is not None:
            context["detail"] = detail
        if error is not None:
            context["error"] = error

    decomposed_item, decomposed_task, work_unit_sentinel = events_crud.decompose_work_unit(args.item_id)
    task_num_value = _normalize_int(args.task_num)
    if decomposed_task is not None and task_num_value is None:
        task_num_value = decomposed_task
    if work_unit_sentinel is not None:
        if context is None:
            context = {}
        context.setdefault("work_unit", work_unit_sentinel)

    active_trace = _current_trace_context()
    trace_id = args.trace_id or active_trace.get("trace_id")

    envelope: dict[str, Any] = {
        "event_id": event_id,
        "event_name": args.name,
        "event_kind": args.kind,
        "event_type": args.type,
        "event_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_outcome": args.outcome or None,
        "source_type": args.source_type,
        "severity": args.severity,
        "session_id": session_id,
        "service": args.service,
        "project": project,
        "environment": args.environment or None,
        "org_id": args.org_id or None,
        "request_id": args.request_id or None,
        "actor_id": args.actor_id,
        "agent": args.agent or None,
        "item_id": decomposed_item,
        "task_num": task_num_value,
        "tool_name": args.tool_name or None,
        "duration_ms": _normalize_int(args.duration_ms),
        "exit_code": _normalize_int(args.exit_code),
        "trace_id": trace_id or None,
        "span_id": active_trace.get("span_id"),
        "parent_id": args.parent_id or None,
        "anomaly_flags": anomaly_flags or None,
        "tool_use_id": args.tool_use_id or None,
        "turn_id": args.turn_id or None,
        "hook_event_name": args.hook_event_name or None,
        "context": context,
    }
    encoded = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_ENVELOPE_BYTES:
        envelope["context"] = None
        envelope["_truncated"] = True
    return envelope


def emit(args: argparse.Namespace) -> int:
    _validate_error_context(args.error_context)

    skip_severity = os.environ.get("YOKE_EVENTS_CAPTURE") == "1"
    if not skip_severity:
        db_path = _db_path()
        if not events_crud.check_severity(db_path, args.name, args.source_type, args.severity):
            return 0

    warning, add_unregistered_flag = _registry_warning(args.name)
    anomaly_flags = args.anomaly_flags or ""
    if add_unregistered_flag:
        anomaly_flags = f"{anomaly_flags},unregistered_event".strip(",")

    event_id = args.event_id or str(uuid.uuid4())
    session_id = _resolve_session_id(args.session_id)
    project = args.project or _resolve_item_project(args.item_id or None) or "yoke"
    args.item_id = _item_lookup_id(args.item_id or None, project=project) or args.item_id
    envelope = _build_envelope(
        args,
        event_id=event_id,
        session_id=session_id,
        project=project,
        anomaly_flags=anomaly_flags or None,
    )
    envelope_json = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)

    if warning:
        print(warning, file=sys.stderr)

    capture_file = os.environ.get("YOKE_EVENTS_FILE")
    if os.environ.get("YOKE_EVENTS_CAPTURE") == "1" and capture_file:
        with open(capture_file, "a", encoding="utf-8") as handle:
            handle.write(envelope_json + "\n")
        return 0

    # Isolation gate: share the native emitter's contract so the
    # CLI and the Python emitter refuse canonical writes under the same
    # rules.  Capture-without-sink and YOKE_EVENTS_ISOLATION both route
    # through ``events.isolation_gate_blocks``.
    if isolation_gate_blocks(
        db_path=_db_path(),
        anomaly_flags=anomaly_flags or None,
        has_explicit_conn=False,
    ):
        print(
            f"refused: event '{args.name}' would write to canonical ledger "
            "under isolation/capture mode with no escape hatch configured",
            file=sys.stderr,
        )
        return 0

    try:
        events_crud.cmd_insert(
            _db_path(),
            event_id=event_id,
            source_type=args.source_type,
            session_id=session_id,
            event_kind=args.kind,
            event_type=args.type,
            event_name=args.name,
            severity=args.severity,
            event_outcome=args.outcome or None,
            org_id=args.org_id or None,
            actor_id=args.actor_id,
            environment=args.environment or None,
            service=args.service,
            project=project,
            item_id=envelope["item_id"],
            task_num=envelope["task_num"],
            agent=args.agent or None,
            tool_name=args.tool_name or None,
            duration_ms=_normalize_int(args.duration_ms),
            exit_code=_normalize_int(args.exit_code),
            trace_id=args.trace_id or None,
            parent_id=args.parent_id or None,
            anomaly_flags=anomaly_flags or None,
            tool_use_id=args.tool_use_id or None,
            turn_id=args.turn_id or None,
            hook_event_name=args.hook_event_name or None,
            envelope=envelope_json,
            skip_severity=True,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    for required, label in (
        (args.name, "--name"),
        (args.kind, "--kind"),
        (args.type, "--type"),
        (args.source_type, "--source-type"),
    ):
        if not required:
            print(f"Error: {label} is required", file=sys.stderr)
            return 2

    try:
        return emit(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
