"""Compact human output for fleet session-control commands."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, TextIO


BODY_EXCERPT_CHARACTERS = 72
EMPTY_VALUE = "—"
Column = tuple[str, Callable[[Mapping[str, Any]], Any], int]


def _plain(value: Any) -> str:
    if value is None or value == "":
        return EMPTY_VALUE
    if isinstance(value, bool):
        return "yes" if value else "no"
    return " ".join(str(value).split()) or EMPTY_VALUE


def _fit(value: Any, width: int) -> str:
    text = _plain(value)
    if len(text) <= width:
        return text
    return f"{text[: width - 1]}…"


def humanize(value: Any) -> str:
    text = _plain(value)
    if text == EMPTY_VALUE:
        return text
    return text.replace("_", " ").replace("-", " ")


def utc_time(value: Any) -> str:
    text = _plain(value)
    if text == EMPTY_VALUE:
        return text
    candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def write_table(
    title: str,
    columns: Sequence[Column],
    rows: Iterable[Mapping[str, Any]],
    stdout: TextIO,
    *,
    empty: str,
) -> None:
    materialized = list(rows)
    print(title, file=stdout)
    if not materialized:
        print(empty, file=stdout)
        return
    cells = [
        [_fit(accessor(row), width) for _heading, accessor, width in columns]
        for row in materialized
    ]
    widths = [
        max(len(column[0]), *(len(row[index]) for row in cells))
        for index, column in enumerate(columns)
    ]
    print(
        "  ".join(
            column[0].ljust(widths[index]) for index, column in enumerate(columns)
        ).rstrip(),
        file=stdout,
    )
    print("  ".join("-" * width for width in widths), file=stdout)
    for row in cells:
        print(
            "  ".join(
                cell.ljust(widths[index]) for index, cell in enumerate(row)
            ).rstrip(),
            file=stdout,
        )


def write_summary(
    title: str,
    fields: Sequence[tuple[str, Any]],
    stdout: TextIO,
) -> None:
    print(title, file=stdout)
    width = max(len(label) for label, _value in fields)
    for label, value in fields:
        print(f"{label.ljust(width)}  {_plain(value)}", file=stdout)


def _runner(row: Mapping[str, Any]) -> str:
    executor = _plain(row.get("executor"))
    surface = _plain(row.get("executor_surface"))
    if executor == EMPTY_VALUE:
        return surface
    if surface == EMPTY_VALUE:
        return executor
    return f"{executor} / {surface}"


def _roster_focus(row: Mapping[str, Any]) -> str:
    if row.get("focus"):
        return str(row["focus"])
    claims = row.get("claims") or []
    return ", ".join(str(claim.get("target") or "") for claim in claims)


def _messageable(row: Mapping[str, Any]) -> str:
    value = row.get("messageability")
    if not isinstance(value, Mapping):
        return "unknown"
    if bool(value.get("messageable")):
        return "yes"
    reason = value.get("reason") or value.get("code")
    return f"no ({humanize(reason)})" if reason else "no"


def write_roster_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Write either the rich roster or the single-session liveness view."""
    fields = set(result.get("fields") or [])
    rows = result.get("rows") or []
    if "activity_at" in fields and "project" not in fields:
        columns: tuple[Column, ...] = (
            ("SESSION", lambda row: row.get("session_id"), 30),
            ("LIVENESS", lambda row: humanize(row.get("liveness")), 12),
            ("ACTIVITY (UTC)", lambda row: utc_time(row.get("activity_at")), 22),
            ("ENDED (UTC)", lambda row: utc_time(row.get("ended_at")), 22),
        )
    else:
        columns = (
            ("SESSION", lambda row: row.get("session_id"), 28),
            ("PROJECT", lambda row: row.get("project"), 14),
            ("FOCUS", _roster_focus, 20),
            ("ROLE", lambda row: humanize(row.get("role")), 16),
            ("RUNNER", _runner, 28),
            ("MACHINE", lambda row: row.get("machine_id"), 18),
            ("LIVENESS", lambda row: humanize(row.get("liveness")), 10),
            ("RELAY", lambda row: humanize(row.get("relay")), 12),
            ("MESSAGEABLE", _messageable, 18),
        )
    write_table("SESSIONS", columns, rows, stdout, empty="No sessions found.")


def _recipient(row: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = row.get("routing_snapshot")
    return {
        **(dict(snapshot) if isinstance(snapshot, Mapping) else {}),
        **dict(row),
    }


def _recipient_project(row: Mapping[str, Any]) -> Any:
    return row.get("project") or row.get("project_id")


def _recipient_status(row: Mapping[str, Any]) -> str:
    return humanize(row.get("state") or row.get("liveness"))


def _write_recipients(recipients: Iterable[Mapping[str, Any]], stdout: TextIO) -> None:
    rows = [_recipient(recipient) for recipient in recipients]
    columns: tuple[Column, ...] = (
        ("SESSION", lambda row: row.get("session_id"), 28),
        ("PROJECT", _recipient_project, 14),
        ("STATE", _recipient_status, 14),
        ("SURFACE", lambda row: row.get("executor_surface"), 20),
        ("MACHINE", lambda row: row.get("machine_id"), 18),
        ("MESSAGEABLE", _messageable, 18),
    )
    write_table(
        "RECIPIENTS",
        columns,
        rows,
        stdout,
        empty="No recipients found.",
    )


def _message_state(message: Mapping[str, Any]) -> str:
    if message.get("cancelled_at"):
        reason = humanize(message.get("cancellation_reason"))
        return f"cancelled ({reason})" if reason != EMPTY_VALUE else "cancelled"
    states = sorted(
        {
            humanize(recipient.get("state"))
            for recipient in message.get("recipients") or []
        }
    )
    return " / ".join(states) if states else "no recipients"


def _body_excerpt(value: Any) -> str:
    return _fit(value, BODY_EXCERPT_CHARACTERS)


def _write_message_detail(message: Mapping[str, Any], stdout: TextIO) -> None:
    recipients = message.get("recipients") or []
    sender = message.get("sender_session_id")
    if not sender and message.get("sender_actor_id") is not None:
        sender = f"actor {message['sender_actor_id']}"
    fields = [
        ("Message ID", message.get("message_id")),
        ("State", _message_state(message)),
        ("Sender", sender),
        ("Recipients", len(recipients)),
        ("Created (UTC)", utc_time(message.get("created_at"))),
        ("Expires (UTC)", utc_time(message.get("expires_at"))),
        ("Body excerpt", _body_excerpt(message.get("body"))),
    ]
    if message.get("cancellation_reason"):
        fields.insert(
            -1, ("Cancellation reason", humanize(message["cancellation_reason"]))
        )
    write_summary("MESSAGE", fields, stdout)
    _write_recipients(recipients, stdout)


def write_message_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    if "recipients" in result:
        message_id = result.get("message_id")
        fields: list[tuple[str, Any]] = [
            ("Recipients", result.get("recipient_count", 0)),
        ]
        if message_id:
            fields.insert(0, ("Message ID", message_id))
        if "deduplicated" in result:
            fields.append(("Deduplicated", bool(result.get("deduplicated"))))
        if result.get("confirmation_token"):
            fields.append(("Confirmation token", result["confirmation_token"]))
        write_summary(
            "MESSAGE SENT" if message_id else "MESSAGE PREVIEW", fields, stdout
        )
        _write_recipients(result.get("recipients") or [], stdout)
        return
    if "messages" in result:
        columns: tuple[Column, ...] = (
            ("MESSAGE", lambda row: row.get("message_id"), 28),
            ("STATE / REASON", _message_state, 28),
            ("TO", lambda row: len(row.get("recipients") or []), 4),
            ("CREATED (UTC)", lambda row: utc_time(row.get("created_at")), 22),
            ("EXPIRES (UTC)", lambda row: utc_time(row.get("expires_at")), 22),
            (
                "BODY",
                lambda row: _body_excerpt(row.get("body")),
                BODY_EXCERPT_CHARACTERS,
            ),
        )
        write_table(
            "MESSAGES",
            columns,
            result.get("messages") or [],
            stdout,
            empty="No messages found.",
        )
        return
    message = result.get("message")
    if isinstance(message, Mapping):
        _write_message_detail(message, stdout)
        return
    print("MESSAGE\nNo message details returned.", file=stdout)


__all__ = [
    "BODY_EXCERPT_CHARACTERS",
    "Column",
    "EMPTY_VALUE",
    "humanize",
    "utc_time",
    "write_message_result",
    "write_roster_result",
    "write_summary",
    "write_table",
]
