"""Whether a quiet claim holder is stuck or sitting inside one long call.

Idleness is measured from the last recorded tool call, which reads a worker
mid-command as silent: a session holding one foreground merge wait or CI-routed
QA gate makes no new call for fifteen to twenty-five minutes and every pass of
the report called it idle. The seat then probed, woke, or restaffed a worker
that was working.

So a holder whose newest open ``session_tool_calls`` row invokes a known
long-running shape -- the watcher wrappers and the inline merge-queue landing
wait -- is reported as in flight rather than counted toward the idle alarm.
Three facts must hold together, because each alone has been observed lying:

- **The command must be a long-running shape.** An ordinary call that left its
  row open is residue, not work.
- **The row must not be a denial.** A PreToolUse guardrail denies after the
  start row is written, and a harness with no PostToolUse never closes it, so a
  dead turn leaves one open row per refused call -- twenty of them on one
  observed session. A denied call ran for zero seconds; reading it as activity
  hides a genuinely stuck holder.
- **The open row must still be the session's newest activity.** Activity
  recorded well after the call opened proves the session kept working and the
  row was simply never closed.

And in flight is bounded. Past :data:`IN_FLIGHT_CEILING_SECONDS` the call has
outlived every wrapper's own wait budget, so the holder returns to the idle
alarm where the seat can see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS
from yoke_core.domain.session_activity_state import has_session_tool_calls_table
from yoke_core.domain.session_reclaim_progress import open_tool_call_is_live
from yoke_core.domain.steering_fleet_report_detectors import (
    age_seconds,
    marker,
    parse_stamp,
)


#: How long an open long-running call may go unexamined before it rejoins the
#: idle alarm. Set to the widest budget any of these shapes gives itself -- the
#: merge-queue landing wait's own poll deadline -- so a call that outlives it
#: has outlived the bound its own command would have enforced.
IN_FLIGHT_CEILING_SECONDS = 45 * 60

#: The event that marks a start row as a refused call rather than a running one.
DENIAL_EVENT_NAME = "HarnessToolCallDenied"

# Both spellings of every watcher wrapper: the `yoke watch <kind>` sub-command
# pair and the module fallback. The pair rather than the whole `yoke watch
# <kind>` form, because a real invocation carries flags in between
# (`yoke --env prod watch merge ...`).
_WATCHER_FORMS = tuple(
    sorted(
        {
            *(" ".join(tokens) for tokens in WATCH_CLI_TOKENS.values()),
            *WATCH_CLI_TOKENS,
        }
    )
)
_WATCHER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(form) for form in _WATCHER_FORMS) + r")\b"
)

# The inline merge-queue landing wait, in either spelling (`yoke merge item`
# or the runtime module the wrapper invokes). Only `--wait` holds the turn;
# the enqueue-and-exit default returns in seconds.
_MERGE_LANDING_WAIT_RE = re.compile(r"\bmerge[ _]item\b")
MERGE_LANDING_WAIT_LABEL = "merge item --wait"


@dataclass(frozen=True)
class InFlightCall:
    """One holder that is inside a long-running call rather than idle."""

    session_id: str
    item_id: int
    public_ref: str
    command: str
    started_at: str
    open_seconds: int


def long_running_command(command_summary: str | None) -> str | None:
    """Name the long-running shape this command invokes, or ``None``.

    The name is the matched shape rather than the whole command line, so the
    report reads ``in watch merge`` regardless of which flags and working
    directory the invocation carried.
    """
    text = str(command_summary or "")
    watcher = _WATCHER_RE.search(text)
    if watcher is not None:
        return watcher.group(0)
    if "--wait" in text and _MERGE_LANDING_WAIT_RE.search(text) is not None:
        return MERGE_LANDING_WAIT_LABEL
    return None


def _newest_open_call(conn: Any, session_id: str) -> dict[str, Any] | None:
    """The newest unfinished ``session_tool_calls`` row for one session."""
    p = marker(conn)
    row = conn.execute(
        f"""SELECT tool_use_id, tool_name, started_at, command_summary
              FROM session_tool_calls
             WHERE session_id = {p}
               AND completed_at IS NULL
             ORDER BY started_at DESC, tool_use_id DESC
             LIMIT 1""",
        (session_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def call_was_denied(conn: Any, *, session_id: str, tool_use_id: str) -> bool:
    """Whether a PreToolUse guardrail refused the call that opened this row."""
    if not tool_use_id:
        return False
    p = marker(conn)
    row = conn.execute(
        f"""SELECT 1 AS denied
              FROM events
             WHERE session_id = {p}
               AND tool_use_id = {p}
               AND event_name = {p}
             LIMIT 1""",
        (session_id, tool_use_id, DENIAL_EVENT_NAME),
    ).fetchone()
    return row is not None


def in_flight_calls(
    conn: Any,
    *,
    quiet: Sequence[Any],
    now: str,
) -> tuple[InFlightCall, ...]:
    """Which of these quiet holders are inside a long-running call."""
    if not has_session_tool_calls_table(conn):
        return ()
    calls = []
    for holder in quiet:
        open_call = _newest_open_call(conn, holder.session_id)
        if open_call is None:
            continue
        command = long_running_command(open_call.get("command_summary"))
        if command is None:
            continue
        started_at = str(open_call.get("started_at") or "")
        if not open_tool_call_is_live(started_at, holder.last_activity_at):
            continue
        if call_was_denied(
            conn,
            session_id=holder.session_id,
            tool_use_id=str(open_call.get("tool_use_id") or ""),
        ):
            continue
        open_seconds = age_seconds(started_at, now) or 0
        if open_seconds >= IN_FLIGHT_CEILING_SECONDS:
            continue
        calls.append(
            InFlightCall(
                session_id=holder.session_id,
                item_id=holder.item_id,
                public_ref=holder.public_ref,
                command=command,
                started_at=started_at,
                open_seconds=open_seconds,
            )
        )
    return tuple(calls)


@dataclass(frozen=True)
class QuietPartition:
    """Quiet holders split into the ones working and the ones to alarm on.

    ``idle`` keeps holders whose native process is gone: a dead process runs
    nothing, so an open call row of its own is residue. ``alive_idle`` drops
    them again for the detectors that reason about a live session.
    """

    in_flight: tuple[InFlightCall, ...]
    idle: tuple[Any, ...]
    alive_idle: tuple[Any, ...]


def partition_quiet(conn: Any, *, quiet: Sequence[Any], now: str) -> QuietPartition:
    """Split quiet holders into long-running calls and the idle alarm."""
    alive = tuple(holder for holder in quiet if not holder.native_process_gone)
    calls = in_flight_calls(conn, quiet=alive, now=now)
    working = {call.session_id for call in calls}
    return QuietPartition(
        in_flight=calls,
        idle=tuple(h for h in quiet if h.session_id not in working),
        alive_idle=tuple(h for h in alive if h.session_id not in working),
    )


def in_flight_section(calls: tuple[InFlightCall, ...]) -> list[str]:
    """The report's in-flight section, heading included; empty when quiet."""
    if not calls:
        return []
    ceiling = IN_FLIGHT_CEILING_SECONDS // 60
    return [
        f"in flight — holder inside a long-running call, not idle "
        f"(rejoins the idle alarm past {ceiling}m):",
        *(
            f"  {call.public_ref}  session {call.session_id}  "
            f"in {call.command} since {parse_stamp(call.started_at):%H:%M}Z"
            for call in calls
        ),
    ]


def in_flight_dicts(calls: tuple[InFlightCall, ...]) -> list[dict[str, Any]]:
    return [
        {
            "session_id": call.session_id,
            "item_id": call.item_id,
            "public_ref": call.public_ref,
            "command": call.command,
            "started_at": call.started_at,
            "open_seconds": call.open_seconds,
        }
        for call in calls
    ]


__all__ = [
    "DENIAL_EVENT_NAME",
    "IN_FLIGHT_CEILING_SECONDS",
    "MERGE_LANDING_WAIT_LABEL",
    "InFlightCall",
    "QuietPartition",
    "call_was_denied",
    "in_flight_calls",
    "in_flight_dicts",
    "in_flight_section",
    "long_running_command",
    "partition_quiet",
]
