"""One observation of fleet state, read through registered functions.

A steering session needs to notice change: an item moved status, a
session appeared or ended, an envelope is sitting unread. None of that
has a streaming surface, so the probe polls and compares. This module
owns the *observation* — the three registered reads and the normalized
rows they produce. Comparison lives in
:mod:`yoke_core.domain.fleet_delta_lines`.

Every read is a registered function id dispatched through the client
transport, so a local-Postgres universe and an HTTPS control plane both
answer, and no raw SQL is embedded in a polling loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_core.domain.session_mode import session_is_parked

#: Registered function ids this observation is composed from.
SESSIONS_FUNCTION = "sessions.list"
FRONTIER_FUNCTION = "charge.schedule"
ENVELOPES_FUNCTION = "session_control.message.list"

#: Envelope rows fetched per pass. Starvation lives at the recent end of
#: the list, so a bounded page is the whole working set.
ENVELOPE_PAGE = 200


class FleetReadError(RuntimeError):
    """A registered read failed, naming the function and the reason."""

    def __init__(self, function_id: str, detail: str) -> None:
        super().__init__(f"{function_id}: {detail}")
        self.function_id = function_id
        self.detail = detail


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a control-plane timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SessionRow:
    """A roster row reduced to the fields change detection reads."""

    session_id: str
    executor_surface: str
    mode: str
    parked: bool
    ended: bool
    terminated: bool
    activity_at: datetime | None
    claimed_items: tuple[str, ...] = ()

    @property
    def lifecycle(self) -> str:
        """``live`` / ``ended`` / ``terminated`` for one roster row."""
        if self.terminated:
            return "terminated"
        if self.ended:
            return "ended"
        return "live"


@dataclass(frozen=True)
class ItemRow:
    """A non-terminal frontier item reduced to change-detection fields."""

    ref: str
    status: str
    title: str
    claim_state: str
    project: str

    @property
    def unclaimed(self) -> bool:
        return self.claim_state == "unclaimed"


@dataclass(frozen=True)
class EnvelopeRow:
    """One durable message receipt: a message plus one recipient."""

    message_id: str
    recipient_session_id: str
    sender_session_id: str
    state: str
    injection_count: int
    created_at: datetime | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.message_id, self.recipient_session_id)


@dataclass(frozen=True)
class FleetSnapshot:
    """Everything one probe pass observed, keyed for comparison."""

    taken_at: datetime
    self_session_id: str
    sessions: Mapping[str, SessionRow] = field(default_factory=dict)
    items: Mapping[str, ItemRow] = field(default_factory=dict)
    envelopes: Mapping[tuple[str, str], EnvelopeRow] = field(default_factory=dict)


def _result(response: Any, function_id: str) -> dict[str, Any]:
    """Unwrap a dispatcher response, raising a named read failure."""
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = (
            f"{error.code}: {error.message}" if error is not None else "unknown error"
        )
        raise FleetReadError(function_id, detail)
    return dict(getattr(response, "result", None) or {})


def session_rows(result: Mapping[str, Any]) -> dict[str, SessionRow]:
    """Normalize a ``sessions.list`` result into roster rows.

    The roster ships ``fields`` (a display column order) alongside
    ``rows``; only the rows carry state, and each is already a mapping.
    """
    rows: dict[str, SessionRow] = {}
    for raw in result.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        session_id = str(raw.get("session_id") or "")
        if not session_id:
            continue
        claims = tuple(
            str(claim.get("target") or claim.get("item_ref") or "")
            for claim in raw.get("claims") or []
            if isinstance(claim, Mapping) and claim.get("target_kind") == "item"
        )
        rows[session_id] = SessionRow(
            session_id=session_id,
            executor_surface=str(raw.get("executor_surface") or "unknown"),
            mode=str(raw.get("mode") or ""),
            parked=session_is_parked(raw.get("mode")),
            ended=bool(raw.get("ended_at")),
            terminated=bool(raw.get("terminated_at")),
            activity_at=parse_timestamp(raw.get("activity_at")),
            claimed_items=tuple(ref for ref in claims if ref),
        )
    return rows


def item_rows(result: Mapping[str, Any]) -> dict[str, ItemRow]:
    """Normalize a ``charge.schedule`` result into frontier item rows.

    The scheduler already excludes terminal items, so the union of its
    ranked, blocked, and frozen lists is the project's in-flight set.
    """
    rows: dict[str, ItemRow] = {}
    for bucket in ("ranked_steps", "blocked_steps", "frozen_steps"):
        for raw in result.get(bucket) or []:
            if not isinstance(raw, Mapping):
                continue
            ref = str(raw.get("item_id") or "")
            if not ref:
                continue
            rows[ref] = ItemRow(
                ref=ref,
                status=str(raw.get("status") or "unknown"),
                title=str(raw.get("title") or ""),
                claim_state=str(raw.get("claim_state") or "unknown"),
                project=str(raw.get("project") or ""),
            )
    return rows


def envelope_rows(
    result: Mapping[str, Any],
) -> dict[tuple[str, str], EnvelopeRow]:
    """Normalize a message listing into per-recipient receipt rows."""
    rows: dict[tuple[str, str], EnvelopeRow] = {}
    for message in result.get("messages") or []:
        if not isinstance(message, Mapping):
            continue
        message_id = str(message.get("message_id") or "")
        sender = str(message.get("sender_session_id") or "")
        created = parse_timestamp(message.get("created_at"))
        for recipient in message.get("recipients") or []:
            if not isinstance(recipient, Mapping):
                continue
            session_id = str(recipient.get("session_id") or "")
            if not message_id or not session_id:
                continue
            row = EnvelopeRow(
                message_id=message_id,
                recipient_session_id=session_id,
                sender_session_id=sender,
                state=str(recipient.get("state") or "unknown"),
                injection_count=int(recipient.get("injection_count") or 0),
                created_at=(parse_timestamp(recipient.get("created_at")) or created),
            )
            rows[row.key] = row
    return rows


def read_snapshot(
    projects: Sequence[str],
    *,
    call: Any,
    now: datetime,
    self_session_id: str,
    workspace: str | None = None,
) -> FleetSnapshot:
    """Compose one observation from the three registered reads.

    ``call`` is a ``(function_id, payload) -> response`` callable so the
    transport stays injectable for tests and the loop stays free of
    dispatcher construction detail.
    """
    sessions: dict[str, SessionRow] = {}
    items: dict[str, ItemRow] = {}
    resolved_workspace = workspace or str(Path.cwd())
    for project in projects:
        sessions.update(
            session_rows(
                _result(
                    call(SESSIONS_FUNCTION, {"project": project}),
                    SESSIONS_FUNCTION,
                )
            )
        )
        items.update(
            item_rows(
                _result(
                    call(
                        FRONTIER_FUNCTION,
                        {"project": project, "workspace": resolved_workspace},
                    ),
                    FRONTIER_FUNCTION,
                )
            )
        )
    envelopes = envelope_rows(
        _result(
            call(ENVELOPES_FUNCTION, {"limit": ENVELOPE_PAGE}),
            ENVELOPES_FUNCTION,
        )
    )
    return FleetSnapshot(
        taken_at=now,
        self_session_id=self_session_id,
        sessions=sessions,
        items=items,
        envelopes=envelopes,
    )


__all__ = [
    "ENVELOPES_FUNCTION",
    "ENVELOPE_PAGE",
    "EnvelopeRow",
    "FRONTIER_FUNCTION",
    "FleetReadError",
    "FleetSnapshot",
    "ItemRow",
    "SESSIONS_FUNCTION",
    "SessionRow",
    "envelope_rows",
    "item_rows",
    "parse_timestamp",
    "read_snapshot",
    "session_rows",
]
