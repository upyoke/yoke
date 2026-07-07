"""Postgres-native SQL "now-offset" fragments.

Callers use :func:`now_sql` instead of hand-writing
``to_char(now() ... )`` literals.  The returned strings are SQL fragments for
interpolation into larger query strings; this module never executes SQL.

For callers that do not need SQL-evaluated time at all (e.g., stashing a
"run started at" timestamp in an event payload, or computing a cutoff in
Python before binding it as a parameter), prefer the app-level
:func:`yoke_core.domain.db_helpers.iso8601_now` path over a forced SQL
helper call.

Usage::

    from yoke_core.domain.time_sql import now_sql

    # Fixed-window offsets (days / hours / minutes):
    conn.execute(
        "SELECT COUNT(*) FROM item_status_transitions "
        f"WHERE (created_at)::timestamp >= ({now_sql(offset_days=-30)})::timestamp"
    )

    # Placeholder-driven modifier expression, e.g., heartbeat TTL sweeps
    # where the offset is supplied via a bound parameter:
    conn.execute(
        "SELECT ... WHERE (last_heartbeat)::timestamp < "
        f"({now_sql(offset_modifier=\"? || ' minutes'\")})::timestamp",
        (f"-{ttl_minutes}",),
    )

    # ``localtime`` variant used only by the operator-facing board buckets:
    conn.execute(
        "SELECT ... WHERE (created_at)::timestamp >= "
        f"({now_sql(offset_modifier='?', localtime=True)})::timestamp",
        (f"-{label_days} days",),
    )
"""

from __future__ import annotations

from typing import Optional


def _pg_now_sql(offset_days, offset_hours, offset_minutes, offset_modifier, localtime):
    """Return a Postgres timestamp string fragment.

    Emits ``to_char(..., 'YYYY-MM-DD HH24:MI:SS')`` so the rendered string
    matches the space-separated form used by translated timestamp comparisons.
    The ``offset_modifier`` fragment (``?`` or ``? || ' minutes'``) is reused
    verbatim and cast to ``interval``.
    """
    base = "LOCALTIMESTAMP" if localtime else "(now() AT TIME ZONE 'utc')"
    fmt = "'YYYY-MM-DD HH24:MI:SS'"
    if offset_days is not None:
        expr = f"{base} + make_interval(days => {offset_days})"
    elif offset_hours is not None:
        expr = f"{base} + make_interval(hours => {offset_hours})"
    elif offset_minutes is not None:
        expr = f"{base} + make_interval(mins => {offset_minutes})"
    elif offset_modifier is not None:
        expr = f"{base} + ({offset_modifier})::interval"
    else:
        expr = base
    return f"to_char({expr}, {fmt})"


def now_sql(
    *,
    offset_days: Optional[int] = None,
    offset_hours: Optional[int] = None,
    offset_minutes: Optional[int] = None,
    offset_modifier: Optional[str] = None,
    localtime: bool = False,
) -> str:
    """Return a Postgres SQL fragment evaluating "now" with an optional offset.

    At most one of ``offset_days`` / ``offset_hours`` / ``offset_minutes`` /
    ``offset_modifier`` may be supplied; pass none for bare "now".

    ``offset_days`` / ``offset_hours`` / ``offset_minutes`` are signed integers.
    Negative values reach into the past (the common "retention window" /
    "staleness cutoff" case); positive values reach into the future.

    ``offset_modifier`` is a raw SQL expression inlined verbatim, typically
    a placeholder-driven modifier like ``"? || ' minutes'"`` or a lone
    ``"?"`` when the full modifier string is supplied via the bound
    parameter tuple.  Parameter binding is the caller's responsibility; the
    helper never touches the bind values.

    ``localtime`` switches the base expression to ``LOCALTIMESTAMP``.  Only the
    operator-facing weekly-bucket path in the board uses this; server-side
    telemetry queries run in UTC without it.
    """
    fixed_offsets = (offset_days, offset_hours, offset_minutes)
    fixed_supplied = sum(1 for v in fixed_offsets if v is not None)
    if fixed_supplied > 1:
        raise ValueError(
            "now_sql: pass at most one of offset_days, offset_hours, offset_minutes"
        )
    if fixed_supplied and offset_modifier is not None:
        raise ValueError(
            "now_sql: offset_modifier is mutually exclusive with a fixed offset"
        )

    return _pg_now_sql(
        offset_days, offset_hours, offset_minutes, offset_modifier, localtime
    )


__all__ = ["now_sql"]
