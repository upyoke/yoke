"""DB query failure detection from Bash output.

Sibling of ``db_error_hook``. Owns the neutral ``detect_db_query_failure``
analyzer that scans command + output strings for raw ``sqlite3`` CLI exit
codes, Python ``sqlite3`` tracebacks, and schema-name hints from ``db_router
query`` and friends.

The current pattern set is still SQLite-dialect-shaped, so the historical
``detect_sqlite_failure`` name remains as a compatibility alias for callers
and telemetry that still refer to the old detector name.
"""

from __future__ import annotations

import re
from typing import Optional


# Schema-hint matches must originate at line-start (column 0) -- the
# stderr-shape position real sqlite3 / db_router failures use. Stored
# envelope text from prior failed sessions (legitimately recorded in
# columns like ``events.envelope``, ``tool_calls.payload``, or
# ``qa_runs.raw_result``) appears embedded inside row content -- after
# ``1|`` separators or inside JSON-quoted strings -- and never at
# column 0. Without the anchor, a successful raw-SQL query whose
# output rows contain historical ``Error: no such column: ...`` text
# would fire the hard-stop and mislead the agent into "fixing" a
# query that already succeeded.
_SCHEMA_HINT_RE = re.compile(
    r"^(?:Error|sqlite3\.OperationalError):\s*no such (column|table)(?::\s*([\w.]+))?",
    re.IGNORECASE | re.MULTILINE,
)


# Substrings that mark a command as raw-SQL / direct-sqlite shape. A
# schema-name miss inside these failed commands is a stale-schema bug and
# the hard-stop hint applies. A schema-name miss inside structured
# commands (``items get ... body``, ``items update ...``, ``projects get
# ...``) is content data, not failure output, and must not fire the hint
# -- that scenario is the false-positive class where reading a
# ticket body containing historical ``Error: no such column`` examples
# was emitting the hard-stop unnecessarily.
_DB_QUERY_SHAPE_SUBSTRINGS: tuple[str, ...] = (
    "sqlite3",
    "db_router query",
    "cli.db_router query",
)


def _looks_like_db_query_command(command: str) -> bool:
    """Return True when *command* is a raw-SQL / direct-sqlite shape."""
    if not command:
        return False
    if any(token in command for token in _DB_QUERY_SHAPE_SUBSTRINGS):
        return True
    # Python invocations that import sqlite3 (or call a Python helper
    # that wraps sqlite3) qualify when the output already shows a
    # sqlite3 traceback shape; the caller handles that pairing inline.
    if "python" in command and "sqlite" in command:
        return True
    return False


def _schema_hint_message(kind: str, name: str) -> str:
    return (
        f"HARD STOP: query references unknown {kind} `{name}`. "
        "The query shape is stale -- most likely a column was renamed, "
        "a table was retired, or the agent guessed a wrong name from "
        "training data. Do NOT keep guessing.\n"
        "- Read the layer-explicit schema/API packet for the current "
        "actor: `python3 -m yoke_core.domain.schema_api_context render "
        "--role <role>` where <role> is one of `main_agent` "
        "(top-level Yoke session), `architect_agent`, `engineer_agent`, "
        "`tester_agent`, `simulator_agent`, or `boss_agent`.\n"
        "- For live claim-holder lookups use "
        "`python3 -m runtime.harness.harness_sessions who-claims <item-id>` "
        "(also `python3 -m yoke_core.cli.db_router harness-sessions "
        "who-claims <item-id>`), not raw SQL on guessed session/claim "
        "columns.\n"
        "- The generated packet and its drift tests reject the known stale "
        "session-owner, claim-session, item-claim, and generic target-column "
        "guesses that do not exist in Yoke's schema.\n"
        "- Full reference: docs/db-reference/ (start at "
        "docs/db-reference.md)."
    )


def detect_db_query_failure(command: str, output: str) -> Optional[str]:
    """Detect DB query failures in command output.

    Returns an error message to inject, or None if no failure detected.

    Schema-name hints (``no such column`` / ``no such table``) only fire
    when *command* itself is a raw-SQL / direct-sqlite shape -- structured
    reads like ``db_router items get ... body`` legitimately surface
    historical error text inside the rendered content and must not be
    mistaken for a failed query.
    """
    import sqlite3 as _sqlite3_mod  # noqa: F401 -- stdlib import for error name matching

    messages = []
    _sqlite_cmd = "sqlite3"

    if _sqlite_cmd in command:
        exit_match = re.search(r"Exit code ([1-9]\d*)", output)
        if exit_match:
            exit_code = exit_match.group(1)
            messages.append(
                f"HARD STOP: {_sqlite_cmd} query FAILED (exit code {exit_code}). "
                "Do NOT draw conclusions from a failed query. "
                "A failed query means the SQL was wrong or the DB state is unexpected -- "
                'it does NOT mean "no results" or "empty table". '
                "Fix the query and re-run before proceeding."
            )

    schema_hint = _SCHEMA_HINT_RE.search(output)
    is_query_shape = _looks_like_db_query_command(command)
    if schema_hint and is_query_shape:
        kind = schema_hint.group(1).lower()
        name = schema_hint.group(2) or "(unnamed)"
        messages.append(_schema_hint_message(kind, name))
    elif (
        not schema_hint
        # Same position-aware rationale as ``_SCHEMA_HINT_RE`` above:
        # only real Python sqlite3 tracebacks emit ``sqlite3.<Type>Error:``
        # at line-start. Stored envelope text from prior failed sessions
        # carries the same prefix mid-line and must not fire.
        and re.search(r"^sqlite3\.[A-Za-z]+Error:", output, re.MULTILINE)
        and ("python" in command or _sqlite_cmd in command)
    ):
        messages.append(
            "HARD STOP: DB query FAILED in a Python traceback. "
            "Do NOT draw conclusions from that traceback. "
            "Use Postgres authority through `YOKE_PG_DSN` or the "
            "Python-owned `python3 -m yoke_core.cli.db_router`, then re-run."
        )

    return "\n".join(messages) if messages else None


def detect_sqlite_failure(command: str, output: str) -> Optional[str]:
    """Compatibility alias for the current SQLite-dialect detector."""
    return detect_db_query_failure(command, output)


__all__ = ("detect_db_query_failure", "detect_sqlite_failure")
