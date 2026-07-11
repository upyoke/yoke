"""Read-only query and reporting functions for the Yoke event platform."""

from __future__ import annotations

import sys
from typing import IO, Any, List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.events_audit_presets import (
    cmd_failed_only_list,
    cmd_friction_summary,
)
from yoke_core.domain.events_select import (
    _EVT_SELECT_COLS,
    _format_rows,
    severity_num,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.events_query_usage import LIST_USAGE
from yoke_core.domain.events_relative_time import parse_since
from yoke_core.domain.yok_n_parser import parse_item_id


_COLUMN_FLAGS: dict[str, str] = {
    "--source-type": "source_type",
    "--session-id": "session_id",
    "--session": "session_id",
    "--event-kind": "event_kind",
    "--event-name": "event_name",
    "--agent": "agent",
    "--service": "service",
    "--actor-id": "actor_id",
    "--trace-id": "trace_id",
    "--project": "project_id",
    "--item-id": "item_id",
    "--item": "item_id",
    "--tool-use-id": "tool_use_id",
    "--turn-id": "turn_id",
    "--hook-event-name": "hook_event_name",
}

def _build_where(
    args: Sequence[str],
    *,
    db_path: Optional[str] = None,
) -> Tuple[str, list]:
    """Parse filter flags and return (WHERE clause, params list).

    Raises ``ValueError`` for unknown flags or missing values. ``--item``
    resolves public refs or project-local sequences to internal ids;
    ``--project`` resolves slug/id to ``events.project_id``.
    ``--current-episode`` requires ``--session-id``.
    """
    parts: list[str] = []
    params: list[Any] = []
    current_episode = False
    session_id_value: Optional[str] = None
    project_context: Optional[str] = None
    for idx, token in enumerate(args):
        if token == "--project" and idx + 1 < len(args):
            project_context = str(args[idx + 1])
            break
    i = 0
    while i < len(args):
        flag = args[i]
        if flag == "--current-episode":
            current_episode = True
            i += 1
            continue
        if flag in _COLUMN_FLAGS:
            col = _COLUMN_FLAGS[flag]
            if i + 1 >= len(args) or str(args[i + 1]).startswith("--"):
                raise ValueError(
                    f"events filter flag '{flag}' requires a value"
                )
            i += 1
            value: Any = args[i]
            if col == "item_id":
                conn = connect(db_path)
                try:
                    value = str(parse_item_id(
                        value, project=project_context, conn=conn
                    ))
                except ValueError as exc:
                    message = str(exc)
                    if "not found" in message:
                        raise ValueError(message) from exc
                    raise ValueError(
                        f"events filter flag '{flag}' requires PREFIX-N, or "
                        "bare N with project context"
                    ) from exc
                finally:
                    conn.close()
            elif col == "project_id":
                conn = connect(db_path)
                try:
                    value = resolve_project_id(conn, value)
                except LookupError as exc:
                    raise ValueError(str(exc)) from exc
                finally:
                    conn.close()
            elif col == "actor_id":
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "events filter flag '--actor-id' requires a numeric actor id"
                    ) from exc
            if col == "session_id":
                session_id_value = str(value)
            parts.append(f"{col}=%s")
            params.append(value)
        elif flag == "--min-severity":
            if i + 1 >= len(args) or str(args[i + 1]).startswith("--"):
                raise ValueError(
                    "events filter flag '--min-severity' requires a value"
                )
            i += 1
            sev_num = severity_num(args[i])
            parts.append(
                "CASE severity "
                "WHEN 'DEBUG' THEN 0 "
                "WHEN 'INFO' THEN 1 "
                "WHEN 'STATUS' THEN 2 "
                "WHEN 'WARN' THEN 3 "
                "WHEN 'ERROR' THEN 4 "
                "WHEN 'FATAL' THEN 5 "
                f"ELSE 1 END >= {sev_num}"
            )
        elif flag == "--since":
            if i + 1 >= len(args) or str(args[i + 1]).startswith("--"):
                raise ValueError(
                    "events filter flag '--since' requires a value"
                )
            i += 1
            parts.append("created_at >= %s")
            params.append(parse_since(args[i]))
        elif flag == "--until":
            if i + 1 >= len(args) or str(args[i + 1]).startswith("--"):
                raise ValueError(
                    "events filter flag '--until' requires a value"
                )
            i += 1
            parts.append("created_at <= %s")
            params.append(parse_since(args[i]))
        else:
            raise ValueError(f"events: unknown filter flag '{flag}'")
        i += 1

    if current_episode:
        if session_id_value is None:
            raise ValueError(
                "events filter flag '--current-episode' requires --session-id"
            )
        from yoke_core.domain.events_current_episode import (
            resolve_current_episode_boundary,
        )
        conn = connect(db_path)
        try:
            boundary = resolve_current_episode_boundary(conn, session_id_value)
        finally:
            conn.close()
        if boundary is None:
            parts.append("0=1")  # fail closed: empty set, never implicit-all
        else:
            parts.append("created_at >= %s")
            params.append(boundary)

    if parts:
        return "WHERE " + " AND ".join(parts), params
    return "", params


def _query_events(
    db_path: Optional[str],
    where: str,
    params: Sequence[Any],
    *,
    order: str = "ASC",
) -> str:
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            f"SELECT {_EVT_SELECT_COLS} FROM events {where} "
            f"ORDER BY created_at {order}, id {order}",
            tuple(params),
        )
        return _format_rows(rows)
    finally:
        conn.close()


def cmd_list(db_path: Optional[str] = None, args: Sequence[str] = ()) -> str:
    where, params = _build_where(args, db_path=db_path)
    return _query_events(db_path, where, params)


def cmd_count(db_path: Optional[str] = None, args: Sequence[str] = ()) -> int:
    where, params = _build_where(args, db_path=db_path)
    conn = connect(db_path)
    try:
        return query_scalar(conn, f"SELECT COUNT(*) FROM events {where}", tuple(params))
    finally:
        conn.close()


def cmd_anomalies(db_path: Optional[str] = None, args: Sequence[str] = ()) -> str:
    where, params = _build_where(args, db_path=db_path)
    extra = "anomaly_flags IS NOT NULL AND anomaly_flags <> ''"
    where = f"{where} AND {extra}" if where else f"WHERE {extra}"
    return _query_events(db_path, where, params, order="DESC")


def cmd_tail(db_path: Optional[str] = None, limit: int = 20) -> str:
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            f"SELECT {_EVT_SELECT_COLS} FROM events "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        )
        return _format_rows(rows)
    finally:
        conn.close()


def cmd_query(db_path: Optional[str] = None, sql: str = "") -> str:
    if not sql:
        raise ValueError("SQL query is required")
    conn = connect(db_path)
    try:
        rows = query_rows(conn, sql)
        return _format_rows(rows)
    finally:
        conn.close()


def cli_list(
    db_path: Optional[str],
    rest: Sequence[str],
    *,
    stdout: Optional[IO[str]] = None,
    stderr: Optional[IO[str]] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    if "--help" in rest or "-h" in rest:
        print(LIST_USAGE, file=out)
        return 0
    limit_val: Optional[int] = None
    failed_only = False
    friction_summary = False
    filter_args: List[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == "--limit":
            i += 1
            try:
                limit_val = int(rest[i])
                if limit_val < 0:
                    raise ValueError
            except (IndexError, ValueError):
                print(
                    "Error: list --limit must be a non-negative integer",
                    file=err,
                )
                return 2
        elif rest[i] == "--failed-only":
            failed_only = True
        elif rest[i] == "--friction-summary":
            friction_summary = True
        else:
            filter_args.append(rest[i])
        i += 1
    try:
        if friction_summary:
            where, params = _build_where(filter_args, db_path=db_path)
            result = cmd_friction_summary(db_path, where, params)
        elif failed_only:
            where, params = _build_where(filter_args, db_path=db_path)
            result = cmd_failed_only_list(db_path, where, params)
        else:
            result = cmd_list(db_path, filter_args)
    except ValueError as exc:
        print(f"Error: {exc}", file=err)
        return 2
    if limit_val is not None and result:
        result = "\n".join(result.split("\n")[:limit_val])
    if result:
        print(result, file=out)
    return 0


def cli_count(
    db_path: Optional[str],
    rest: Sequence[str],
    *,
    stdout: Optional[IO[str]] = None,
    stderr: Optional[IO[str]] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        result = cmd_count(db_path, rest)
    except ValueError as exc:
        print(f"Error: {exc}", file=err)
        return 2
    print(result, file=out)
    return 0


def cli_anomalies(
    db_path: Optional[str],
    rest: Sequence[str],
    *,
    stdout: Optional[IO[str]] = None,
    stderr: Optional[IO[str]] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        result = cmd_anomalies(db_path, rest)
    except ValueError as exc:
        print(f"Error: {exc}", file=err)
        return 2
    if result:
        print(result, file=out)
    return 0
