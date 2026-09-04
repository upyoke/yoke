"""What a session owed a CI verdict is told, and how it reaches them.

The recipient is not resolved from a lane the way a landing notice is: the
wait already names the session that dispatched the run, and nobody else is
owed that verdict. What this adds is the body — which has to carry the
verdict itself, because a worker woken with only "your run finished" pays
another round trip to learn the one fact it stopped for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_ci_wait_schema import CI_WAIT_QA_CASE, run_url


def notice_idempotency_key(session_id: str, run_id: str) -> str:
    """One notice per session per run, however many sweeps observe it."""
    return f"ci-run-concluded:{session_id}:{run_id}"


def ci_run_message(
    *,
    conclusion: str,
    repo: str,
    run_id: str,
    head_sha: str,
    kind: str,
    continue_command: str,
) -> str:
    """Name the verdict, the run, the commit, and how to continue."""
    what = "QA case CI run" if kind == CI_WAIT_QA_CASE else "pytest selection run"
    commit = head_sha[:12] or "an unrecorded commit"
    lines = [
        f"CI verdict: {conclusion} — the {what} you dispatched for {commit} "
        f"has concluded.",
        run_url(repo, run_id),
    ]
    if continue_command:
        lines.append(
            f"Continue with: {continue_command} — the gate adopts a concluded "
            "run by exact sha, so this costs a lookup rather than another suite."
        )
    return "\n".join(lines)


def _receipt_delivered(conn: Any, message_id: str, session_id: str) -> bool:
    """True when the recipient actually received the envelope, not merely queued."""
    details = message_details(conn, message_id)
    for recipient in details.get("recipients") or ():
        if str(recipient.get("session_id") or "") != session_id:
            continue
        if recipient.get("last_injected_at") or recipient.get("acknowledged_at"):
            return True
        if int(recipient.get("injection_count") or 0) > 0:
            return True
        return str(recipient.get("state") or "") in {"injected", "acknowledged"}
    return False


def push_ci_run_notice(
    conn: Any,
    *,
    session_id: str,
    actor_id: int,
    body: str,
    idempotency_key: str,
    now: datetime,
) -> str:
    """Send one verdict notice; report what delivery did.

    ``"undelivered"`` is the ordinary answer for the session this exists to
    reach: it has ended its turn, so the envelope waits for the stopped-wake
    route rather than a hook that is not going to fire.
    """
    created = send_message(
        conn,
        actor_id=actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[session_id]),
        body=body,
        idempotency_key=idempotency_key,
        idempotency_intent_only=True,
        now=now,
        commit=False,
    )
    message_id = str(created["message_id"])
    mark_explicit_stopped_wake(conn, message_id=message_id, session_id=session_id)
    if not _receipt_delivered(conn, message_id, session_id):
        return "undelivered"
    return "delivered"


__all__ = [
    "ci_run_message",
    "notice_idempotency_key",
    "push_ci_run_notice",
]
