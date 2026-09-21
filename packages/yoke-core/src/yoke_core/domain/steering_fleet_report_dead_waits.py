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
unanswered message is working, not waiting. And scoped to messages that
actually ask -- an interrogative sentence or an explicit reply request. A
holder's last peer message is frequently a confirmation, which asks for
nothing and waits on nothing; counting it produced exactly the false positive
this module exists to avoid.

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

#: Phrasings that request a reply without asking a question. A peer message
#: is otherwise only a wait when it contains an interrogative sentence.
REPLY_REQUEST_PHRASES: tuple[str, ...] = (
    "please reply",
    "please send",
    "confirm whether",
    "let me know",
)

#: How far back a holder's own outbound messages are read for its open
#: question. A question older than its recent conversation has been overtaken
#: by whatever the holder said since, and resurrecting it invents a wait.
ASK_SCAN_LIMIT = 20


def message_asks(body: str | None) -> bool:
    """Whether this message actually asks the recipient for something.

    A confirmation is not a wait. One worker told a peer "Confirmed: none of
    these files is in the diff" and the report read that as an open question,
    sending the seat to answer a question nobody had asked.
    """
    text = str(body or "")
    if "?" in text:
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in REPLY_REQUEST_PHRASES)


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


def _unique_session_ids(holders: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(holder.session_id) for holder in holders))


def _last_questions(
    conn: Any, session_ids: Sequence[str]
) -> dict[str, dict[str, Any] | None]:
    """The most recent asking message each session sent, if one is in view.

    Scans back over each holder's recent conversation rather than reading
    only its latest message, so a confirmation sent after a real question
    neither counts as a wait itself nor hides the question still underneath
    it. The per-session window is the same ``ASK_SCAN_LIMIT`` joined rows
    the single-session scan used.
    """
    found: dict[str, dict[str, Any] | None] = {
        session_id: None for session_id in session_ids
    }
    if not session_ids:
        return found
    p = marker(conn)
    slots = ",".join(p for _ in session_ids)
    rows = conn.execute(
        f"""SELECT sender_session_id, message_id, created_at, body,
                   answerer_session_id
              FROM (
                    SELECT m.sender_session_id AS sender_session_id,
                           m.message_id AS message_id,
                           m.created_at AS created_at,
                           m.body AS body,
                           r.session_id AS answerer_session_id,
                           ROW_NUMBER() OVER (
                             PARTITION BY m.sender_session_id
                             ORDER BY m.created_at DESC, m.message_id DESC
                           ) AS rn
                      FROM session_messages m
                      JOIN session_message_recipients r
                        ON r.message_id = m.message_id
                     WHERE m.sender_session_id IN ({slots})
                   ) recent
             WHERE rn <= {ASK_SCAN_LIMIT}
             ORDER BY sender_session_id, created_at DESC, message_id DESC""",
        tuple(session_ids),
    ).fetchall()
    for row in rows:
        record = dict(row)
        sender = str(record.get("sender_session_id") or "")
        if sender not in found or found[sender] is not None:
            continue
        if message_asks(record.get("body")):
            found[sender] = record
    return found


def answered_after(conn: Any, *, answerer: str, asker: str, asked_at: str) -> bool:
    """Did the intended answerer send this asker anything after the question?

    Checked before anything else. An answerer that replied and then ended
    answered the question, and calling that a dead wait would send the
    steering seat to repeat an answer the asker already has. The steering
    drain asks the same question of a seat that ended holding a
    role-addressed message.
    """
    return (answerer, asker) in _replied_pairs(conn, ((answerer, asker, asked_at),))


def _replied_pairs(
    conn: Any, triples: Sequence[tuple[str, str, str]]
) -> set[tuple[str, str]]:
    """Which (answerer, asker) pairs already have a reply at or after the ask."""
    if not triples:
        return set()
    p = marker(conn)
    clauses = " OR ".join(
        f"(m.sender_session_id = {p} AND r.session_id = {p} AND m.created_at >= {p})"
        for _ in triples
    )
    params: list[str] = []
    for answerer, asker, asked_at in triples:
        params.extend((answerer, asker, asked_at))
    rows = conn.execute(
        f"""SELECT DISTINCT m.sender_session_id AS answerer,
                   r.session_id AS asker
              FROM session_messages m
              JOIN session_message_recipients r ON r.message_id = m.message_id
             WHERE {clauses}""",
        tuple(params),
    ).fetchall()
    return {(str(dict(row)["answerer"]), str(dict(row)["asker"])) for row in rows}


def _parse_item_id(raw_item_id: Any) -> int | None:
    """``current_item_id`` is text; ``items.id`` is an integer."""
    try:
        return int(str(raw_item_id))
    except (TypeError, ValueError):
        return None


def _item_statuses(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    if not item_ids:
        return {}
    p = marker(conn)
    unique = list(dict.fromkeys(item_ids))
    slots = ",".join(p for _ in unique)
    rows = conn.execute(
        f"SELECT id, status FROM items WHERE id IN ({slots})",
        tuple(unique),
    ).fetchall()
    statuses: dict[int, str] = {}
    for row in rows:
        record = dict(row)
        statuses[int(record["id"])] = str(record.get("status") or "")
    return statuses


def _answerability_for(conn: Any, answerers: Sequence[str]) -> dict[str, str]:
    """Why no answer can arrive from each session, or ``UNRESOLVED``."""
    unique = list(dict.fromkeys(str(answerer) for answerer in answerers if answerer))
    reasons = {
        answerer: "answerer session is unknown to the control plane"
        for answerer in unique
    }
    if not unique:
        return reasons
    p = marker(conn)
    slots = ",".join(p for _ in unique)
    rows = conn.execute(
        f"""SELECT session_id, ended_at, terminated_at, current_item_id
              FROM harness_sessions
             WHERE session_id IN ({slots})""",
        tuple(unique),
    ).fetchall()
    live_pairs: list[tuple[str, int]] = []
    for row in rows:
        record = dict(row)
        answerer = str(record.get("session_id") or "")
        if record.get("ended_at") or record.get("terminated_at"):
            reasons[answerer] = "answerer session has ended"
            continue
        item_id = _parse_item_id(record.get("current_item_id"))
        if item_id is None:
            reasons[answerer] = UNRESOLVED
            continue
        reasons[answerer] = UNRESOLVED
        live_pairs.append((answerer, item_id))
    statuses = _item_statuses(conn, [item_id for _answerer, item_id in live_pairs])
    for answerer, item_id in live_pairs:
        if statuses.get(item_id, "") in TERMINAL_STATUSES:
            reasons[answerer] = "answerer's own item is already terminal"
    return reasons


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

    if not idle:
        return ()
    questions = _last_questions(conn, _unique_session_ids(idle))
    role_addressed = role_addressed_message_ids(
        conn,
        [
            str(question["message_id"])
            for question in questions.values()
            if question is not None
        ],
    )
    pending: list[tuple[Any, str, str, str]] = []
    for holder in idle:
        question = questions.get(holder.session_id)
        if question is None:
            continue
        answerer = str(question.get("answerer_session_id") or "")
        asked_at = str(question.get("created_at") or "")
        if not answerer or answerer == holder.session_id:
            continue
        pending.append(
            (holder, answerer, asked_at, str(question.get("message_id") or ""))
        )
    replied = _replied_pairs(
        conn,
        tuple(
            (answerer, holder.session_id, asked_at)
            for holder, answerer, asked_at, _message_id in pending
        ),
    )
    remaining = [
        (holder, answerer, asked_at)
        for holder, answerer, asked_at, message_id in pending
        if (answerer, holder.session_id) not in replied
        and message_id not in role_addressed
    ]
    reasons = _answerability_for(conn, [answerer for _h, answerer, _asked in remaining])
    return tuple(
        DeadWait(
            session_id=holder.session_id,
            item_id=holder.item_id,
            public_ref=holder.public_ref,
            asked_seconds=age_seconds(asked_at, now) or 0,
            answerer_session_id=answerer,
            reason=reasons.get(
                answerer, "answerer session is unknown to the control plane"
            ),
        )
        for holder, answerer, asked_at in remaining
    )


__all__ = [
    "ASK_SCAN_LIMIT",
    "REPLY_REQUEST_PHRASES",
    "UNRESOLVED",
    "DeadWait",
    "answered_after",
    "dead_waits",
    "message_asks",
]
