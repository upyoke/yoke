"""CLI entrypoint for observe telemetry processing."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Optional

from yoke_core.domain.observe_anomaly import detect_anomalies
from yoke_core.domain.observe_db import (
    connect_observe_db,
    normalize_observe_db_path,
)
from yoke_core.domain.observe_event_emission import build_envelope, insert_event
from yoke_core.domain.observe_parsing import parse_hook_event


def _resolve_db_fallback() -> Optional[str]:
    """Resolve the events DB path when ``--db`` is not supplied.

    Hook launchers now pass only ``--project-dir`` / ``--hook-event``; the
    backend factory resolves the connected Postgres authority. Explicit
    ``--db`` remains a legacy connection-token override for test callers.

    All failures degrade to ``None``; hook observers must never block tool
    execution.
    """
    return None


def record_hook_event(
    data: dict[str, Any],
    *,
    session_id: str = "",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    agent_type: Optional[str] = None,
    attribution_source: Optional[str] = None,
    hook_event: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    db_path: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> None:
    """Parse, detect, and insert one hook payload. Failures are swallowed."""
    rec = parse_hook_event(
        data,
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        agent_type=agent_type,
        attribution_source=attribution_source,
        hook_event=hook_event,
        tool_use_id=tool_use_id,
        db_path=normalize_observe_db_path(db_path),
        project_dir=project_dir,
    )
    if rec is None:
        return
    detect_anomalies(rec)
    envelope = build_envelope(rec)
    try:
        conn = connect_observe_db()
        try:
            insert_event(conn, envelope)
        finally:
            conn.close()
    except Exception:
        pass


def main(db_fallback_resolver: Optional[Callable[[], Optional[str]]] = None) -> None:
    """CLI entry point: read JSON from stdin, process, insert to DB."""
    parser = argparse.ArgumentParser(
        description="Process PostToolUse/PostToolUseFailure hook events"
    )
    parser.add_argument("--db", default=None, help="Legacy connection token")
    parser.add_argument("--session-id", default="", help="Session ID")
    parser.add_argument("--item-id", default="", help="Item ID (e.g. 42)")
    parser.add_argument("--task-num", default="", help="Task number")
    parser.add_argument("--agent-type", default="", help="Agent type")
    parser.add_argument("--attribution-source", default="", help="Attribution source")
    parser.add_argument(
        "--start-ms", default="", help="Start timestamp (unused, for compat)"
    )
    parser.add_argument("--hook-event", default="", help="Hook event name")
    parser.add_argument("--tool-use-id", default="", help="Tool use ID for dedup")
    parser.add_argument(
        "--project-dir",
        default="",
        help="Hook working directory for dispatch/main-session attribution",
    )
    args = parser.parse_args()

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except Exception:
        return
    if not isinstance(data, dict):
        return

    resolver = db_fallback_resolver or _resolve_db_fallback
    db_path = args.db or resolver()
    task_num_val: Optional[int] = None
    if args.task_num:
        try:
            task_num_val = int(args.task_num)
        except ValueError:
            pass

    record_hook_event(
        data,
        session_id=args.session_id,
        item_id=args.item_id or None,
        task_num=task_num_val,
        agent_type=args.agent_type or None,
        attribution_source=args.attribution_source or None,
        hook_event=args.hook_event or None,
        tool_use_id=args.tool_use_id or None,
        db_path=db_path,
        project_dir=args.project_dir or None,
    )


if __name__ == "__main__":
    main()
