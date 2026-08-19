"""Postgres SQL fragments shared by board render queries."""

from __future__ import annotations

DATE_FMT_SQL = "'YYYY-MM-DD'"
LOCAL_NOW_SQL = "LOCALTIMESTAMP"


def timestamp_expr(value_sql: str) -> str:
    """Return *value_sql* cast from Yoke timestamp text to Postgres timestamp."""
    return f"NULLIF({value_sql}, '')::timestamp"


def day_expr(value_sql: str) -> str:
    """Return a ``YYYY-MM-DD`` day bucket expression for timestamp text."""
    return f"to_char({timestamp_expr(value_sql)}, {DATE_FMT_SQL})"


def day_text_expr(value_sql: str) -> str:
    """Return a ``YYYY-MM-DD`` bucket from ISO timestamp text without casting."""
    return f"NULLIF(substring({value_sql} from 1 for 10), '')"


def day_from_timestamp_expr(timestamp_sql: str) -> str:
    """Return a ``YYYY-MM-DD`` day bucket expression for a timestamp expression."""
    return f"to_char({timestamp_sql}, {DATE_FMT_SQL})"


def days_ago_expr(days: int) -> str:
    """Return the local timestamp cutoff *days* before now.

    *days* is an explicit bounded window baked into SQL text. Do not pass
    wall-clock-derived counts (project age, days since first commit): those
    mint a new query key every midnight.
    """
    window = int(days)
    if window < 1:
        raise ValueError(
            "days_ago window must be a positive day count; time-derived "
            "windows such as project age are refused"
        )
    return f"{LOCAL_NOW_SQL} - make_interval(days => {window})"


def days_ago_text_expr(days: int) -> str:
    """Return a ``YYYY-MM-DD`` text cutoff *days* before now."""
    return f"to_char({days_ago_expr(days)}, {DATE_FMT_SQL})"


def age_days_expr(value_sql: str) -> str:
    """Return item age in fractional days from a timestamp-text column."""
    return (
        f"(EXTRACT(EPOCH FROM ({LOCAL_NOW_SQL} - {timestamp_expr(value_sql)})) "
        "/ 86400.0)"
    )


def elapsed_days_expr(later_sql: str, earlier_sql: str) -> str:
    """Return fractional days elapsed between two timestamp expressions."""
    return f"(EXTRACT(EPOCH FROM ({later_sql} - {earlier_sql})) / 86400.0)"
