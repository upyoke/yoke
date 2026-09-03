"""Whether the answer an idle worker is waiting on can still arrive.

This is the one negative-space check that is not a threshold. The others ask
how long something has been true; this one asks a question about the future,
and both wrong answers cost real work. A false positive sends the steering
seat to answer a question nobody asked. A false negative leaves a worker
parked on a reply that is never coming. Both were observed in one session.

So the shape here reports what it can establish and says so when it cannot.
``answerer session has ended`` and ``answerer's own item is already
terminal`` are positive evidence that no reply can arrive. ``unresolved``
means the question is genuinely open: the answerer is still live and working,
and the right read is that an answer may yet come. Nothing is inferred from
absence -- a holder that asked nobody produces no row at all, because its
silence has some other cause.

Scoped to holders the idle detector already named: a busy session with an
unanswered message is working, not waiting.

A question addressed to the steering ROLE never appears here. Its answer
does not depend on the session that happened to hold the seat: the message
is a durable row that the next seat drains on acquire unless its holder
acknowledged it. The fleet report counts only unacknowledged rows in its
awaiting-a-seat line instead of reporting them as waits nobody can answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker


#: An answerer that is live and working. Rendered as a real row so the seat
#: sees the open question, but never as evidence that the wait is dead.
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DeadWait:
    """One idle holder and what is known about the answer it waits on."""

    session_id: str
    item_id: int
    public_ref: str
    asked_seconds: int
    answerer_session_id: str
    reason: str

    @property
    def answer_impossible(self) -> bool:
        """True only with positive evidence that no reply can arrive."""
        return self.reason != UNRESOLVED


def _last_question(conn: Any, session_id: str) -> dict[str, Any] | None:
    """The most recent message this session sent, and who was meant to answer."""
    p = marker(conn)
    row = conn.execute(
        f"""SELECT m.message_id AS message_id,
                   m.created_at AS created_at,
                   r.session_id AS answerer_session_id
              FROM session_messages m
              JOIN session_message_recipients r ON r.message_id = m.message_id
             WHERE m.sender_session_id = {p}
             ORDER BY m.created_at DESC, m.message_id DESC
             LIMIT 1""",
        (session_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def answered_after(conn: Any, *, answerer: str, asker: str, asked_at: str) -> bool:
    """Did the intended answerer send this asker anything after the question?

    Checked before anything else. An answerer that replied and then ended
    answered the question, and calling that a dead wait would send the
    steering seat to repeat an answer the asker already has. The steering
    drain asks the same question of a seat that ended holding a
    role-addressed message.
    """
    p = marker(conn)
    row = conn.execute(
        f"""SELECT 1 AS replied
              FROM session_messages m
              JOIN session_message_recipients r ON r.message_id = m.message_id
             WHERE m.sender_session_id = {p}
               AND r.session_id = {p}
               AND m.created_at >= {p}
             LIMIT 1""",
        (answerer, asker, asked_at),
    ).fetchone()
    return row is not None


def _item_status(conn: Any, raw_item_id: Any) -> str:
    """The status of the item a session declared as its current one.

    ``harness_sessions.current_item_id`` is a text column while ``items.id``
    is an integer, so this resolves in two steps rather than joining across
    the mismatch. A value that is not an item id at all resolves to no
    status, which reads as "nothing known" rather than as evidence.
    """
    try:
        item_id = int(str(raw_item_id))
    except (TypeError, ValueError):
        return ""
    row = conn.execute(
        f"SELECT status FROM items WHERE id = {marker(conn)}",
        (item_id,),
    ).fetchone()
    return str(dict(row).get("status") or "") if row is not None else ""


def _answerability(conn: Any, answerer: str) -> str:
    """Why no answer can arrive from this session, or ``UNRESOLVED``."""
    row = conn.execute(
        f"""SELECT ended_at, terminated_at, current_item_id
              FROM harness_sessions
             WHERE session_id = {marker(conn)}""",
        (answerer,),
    ).fetchone()
    if row is None:
        return "answerer session is unknown to the control plane"
    record = dict(row)
    if record.get("ended_at") or record.get("terminated_at"):
        return "answerer session has ended"
    if _item_status(conn, record.get("current_item_id")) in TERMINAL_STATUSES:
        return "answerer's own item is already terminal"
    return UNRESOLVED


def dead_waits(
    conn: Any,
    *,
    idle: Sequence[Any],
    now: str,
) -> tuple[DeadWait, ...]:
    """For each idle holder, what is known about the answer it waits on."""
    from yoke_core.domain.steering_message_recipients import (
        role_addressed_message_ids,
    )

    questions = {
        holder.session_id: _last_question(conn, holder.session_id) for holder in idle
    }
    role_addressed = role_addressed_message_ids(
        conn,
        [
            str(question["message_id"])
            for question in questions.values()
            if question is not None
        ],
    )
    waits = []
    for holder in idle:
        question = questions.get(holder.session_id)
        if question is None:
            continue
        answerer = str(question.get("answerer_session_id") or "")
        asked_at = str(question.get("created_at") or "")
        if not answerer or answerer == holder.session_id:
            continue
        if answered_after(
            conn,
            answerer=answerer,
            asker=holder.session_id,
            asked_at=asked_at,
        ):
            continue
        if str(question.get("message_id") or "") in role_addressed:
            continue
        waits.append(
            DeadWait(
                session_id=holder.session_id,
                item_id=holder.item_id,
                public_ref=holder.public_ref,
                asked_seconds=age_seconds(asked_at, now) or 0,
                answerer_session_id=answerer,
                reason=_answerability(conn, answerer),
            )
        )
    return tuple(waits)


__all__ = ["UNRESOLVED", "DeadWait", "answered_after", "dead_waits"]
