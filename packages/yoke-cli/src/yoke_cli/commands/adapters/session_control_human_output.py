"""Compact human output for fleet session-control commands."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, TextIO

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.liveness import ENDED_CAUSE_KILLED
from yoke_cli.commands.adapters.session_control_native_diagnostic_output import (
    native_diagnostic_fields,
)
from yoke_cli.commands.adapters.session_control_roster_diagnostics_output import (
    roster_diagnostics,
)
from yoke_cli.commands.adapters.session_control_recipient_output import (
    display_recipients,
    recipient_count,
    recipient_party,
    recipient_project,
    recipient_states,
    recipient_surface,
)


BODY_EXCERPT_CHARACTERS = 72
EMPTY_VALUE = "—"
#: ``(heading, accessor, width)``. Identifier columns pass ``None``: a
#: width elides the cell, and part of an id is not the id.
Column = tuple[str, Callable[[Mapping[str, Any]], Any], int | None]


def _plain(value: Any) -> str:
    if value is None or value == "":
        return EMPTY_VALUE
    if isinstance(value, bool):
        return "yes" if value else "no"
    return " ".join(str(value).split()) or EMPTY_VALUE


def _fit(value: Any, width: int | None) -> str:
    text = _plain(value)
    if width is None:
        return text
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


def _liveness(row: Mapping[str, Any]) -> str:
    """Liveness, with a kill named as the cause it is rather than a state."""
    state = humanize(row.get("liveness"))
    if row.get("ended_cause") == ENDED_CAUSE_KILLED:
        return f"{state} (killed)"
    return state


def write_roster_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Write either the rich roster or the single-session liveness view."""
    fields = set(result.get("fields") or [])
    rows = result.get("rows") or []
    if "activity_at" in fields and "project" not in fields:
        columns: tuple[Column, ...] = (
            ("SESSION", lambda row: row.get("session_id"), None),
            ("LIVENESS", _liveness, 16),
            ("ACTIVITY (UTC)", lambda row: utc_time(row.get("activity_at")), 22),
            ("ENDED (UTC)", lambda row: utc_time(row.get("ended_at")), 22),
        )
    else:
        columns = (
            ("SESSION", lambda row: row.get("session_id"), None),
            ("PROJECT", lambda row: row.get("project"), 14),
            ("FOCUS", _roster_focus, 20),
            ("ROLE", lambda row: humanize(row.get("role")), 16),
            ("RUNNER", _runner, 28),
            (
                "MACHINE",
                lambda row: row.get("machine_name") or row.get("machine_id"),
                None,
            ),
            ("LIVENESS", _liveness, 16),
            ("RESUME", lambda row: humanize(row.get("resume_state")), 18),
            ("RELAY", lambda row: humanize(row.get("relay")), 12),
            ("MESSAGEABLE", _messageable, 18),
            ("DIAGNOSTICS", roster_diagnostics, None),
        )
    write_table("SESSIONS", columns, rows, stdout, empty="No sessions found.")


def _write_recipients(
    recipients: Iterable[Mapping[str, Any]],
    stdout: TextIO,
    *,
    actor_recipients: Iterable[Mapping[str, Any]] = (),
) -> None:
    rows = display_recipients(recipients, actor_recipients)
    columns: tuple[Column, ...] = (
        ("SESSION / ACTOR", recipient_party, None),
        ("PROJECT", recipient_project, 14),
        ("STATE", lambda row: humanize(row.get("state") or row.get("liveness")), 14),
        ("SURFACE", recipient_surface, 20),
        ("MACHINE", lambda row: row.get("machine_id"), None),
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
    states = sorted(humanize(state) for state in recipient_states(message))
    return " / ".join(states) if states else "no recipients"


def _body_excerpt(value: Any) -> str:
    return _fit(value, BODY_EXCERPT_CHARACTERS)


def _attempt_evidence(attempt: Mapping[str, Any]) -> dict[str, str | int]:
    evidence = attempt.get("evidence")
    return redacted_evidence_document(
        evidence if isinstance(evidence, Mapping) else None
    )


def _write_attempts(attempts: Iterable[Mapping[str, Any]], stdout: TextIO) -> None:
    rows = list(attempts)
    if not rows:
        return
    columns: tuple[Column, ...] = (
        ("ATTEMPT", lambda row: row.get("attempt_id"), None),
        ("TARGET", lambda row: row.get("target_session_id"), None),
        ("TYPE", lambda row: humanize(row.get("attempt_kind")), 16),
        ("RESULT", lambda row: humanize(row.get("result_code")), 18),
        # Why a wake fired against a live-looking session. Without it an
        # escalated resume reads here as an ordinary one.
        ("ESCALATION", lambda row: _attempt_evidence(row).get("wake_escalation"), 24),
        (
            "DIAGNOSTIC",
            lambda row: _attempt_evidence(row).get("native_diagnostic_ref"),
            None,
        ),
    )
    write_table("DELIVERY ATTEMPTS", columns, rows, stdout, empty="")
    for row in rows:
        evidence = _attempt_evidence(row)
        fields = native_diagnostic_fields(evidence)
        if not fields:
            continue
        write_summary("NATIVE DIAGNOSTIC", fields, stdout)


def _write_message_detail(message: Mapping[str, Any], stdout: TextIO) -> None:
    recipients = message.get("recipients") or []
    actor_recipients = message.get("actor_recipients") or []
    sender = message.get("sender_session_id")
    if not sender and message.get("sender_actor_id") is not None:
        sender = f"actor {message['sender_actor_id']}"
    fields = [
        ("Message ID", message.get("message_id")),
        ("State", _message_state(message)),
        ("Sender", sender),
        ("Recipients", recipient_count(message)),
        ("Created (UTC)", utc_time(message.get("created_at"))),
        ("Expires (UTC)", utc_time(message.get("expires_at"))),
        ("Body excerpt", _body_excerpt(message.get("body"))),
    ]
    if message.get("cancellation_reason"):
        fields.insert(
            -1, ("Cancellation reason", humanize(message["cancellation_reason"]))
        )
    write_summary("MESSAGE", fields, stdout)
    _write_recipients(recipients, stdout, actor_recipients=actor_recipients)
    _write_attempts(message.get("attempts") or [], stdout)
    if any(recipient.get("state") == "injected" for recipient in recipients):
        print(
            f"Recipient next step: yoke messages acknowledge {message.get('message_id')}",
            file=stdout,
        )


def write_message_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    if "recipients" in result:
        message_id = result.get("message_id")
        fields: list[tuple[str, Any]] = [
            ("Recipients", result.get("recipient_count", 0)),
        ]
        if message_id:
            fields.insert(0, ("Message ID", message_id))
        if result.get("applied_liveness"):
            fields.append(("Liveness", ", ".join(result["applied_liveness"])))
        if "deduplicated" in result:
            fields.append(("Deduplicated", bool(result.get("deduplicated"))))
        if result.get("confirmation_token"):
            fields.append(("Confirmation token", result["confirmation_token"]))
        write_summary(
            "MESSAGE SENT" if message_id else "MESSAGE PREVIEW", fields, stdout
        )
        _write_recipients(
            result.get("recipients") or [],
            stdout,
            actor_recipients=result.get("actor_recipients") or [],
        )
        if message_id:
            print(f"Track delivery: yoke messages get {message_id}", file=stdout)
        return
    if "messages" in result:
        columns: tuple[Column, ...] = (
            ("MESSAGE", lambda row: row.get("message_id"), None),
            ("STATE / REASON", _message_state, 28),
            ("TO", recipient_count, 4),
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
