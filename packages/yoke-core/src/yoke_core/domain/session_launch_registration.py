"""Single-use launch attestation and first-instruction binding."""

from __future__ import annotations

import hmac
from typing import Any

from yoke_core.domain.session_launch_binding_evidence import late_registration_evidence
from yoke_core.domain.session_launch_store import (
    attestation_digest,
    begin_mutation,
    get_launch,
    instruction_message,
    marker,
    parse_time,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_types import (
    LaunchRecord,
    LaunchRegistrationInjection,
    SessionLaunchError,
)
from .session_launch_registered_session_binding import (
    bind_launch_to_session,
    require_registered_session_facts,
)


def prepare_launch_registration(
    conn: Any,
    *,
    launch_id: str,
    attestation: str,
    session_id: str,
    now: str | None = None,
) -> LaunchRegistrationInjection:
    """Bind an attested hook session and return its pending instruction body.

    The attestation is consumed before the body leaves the transaction. If the
    hook response is lost, the ordinary pending-message path owns redelivery;
    the attestation itself can never be replayed.
    """
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.state != "awaiting_registration":
            raise SessionLaunchError(
                "invalid_state",
                f"launch is {launch.state!r}, not awaiting registration",
            )
        if launch.attestation_consumed_at:
            raise SessionLaunchError(
                "attestation_consumed", "attestation is single-use"
            )
        if parse_time(current) >= parse_time(launch.deadline_at):
            update_launch(
                conn,
                launch_id,
                state="failed",
                attestation_consumed_at=current,
                completed_at=current,
                result_code="late_registration",
                result_evidence=late_registration_evidence(
                    conn, launch=launch, session_id=session_id, now=current
                ),
            )
            conn.commit()
            raise SessionLaunchError(
                "late_registration", "registration deadline passed"
            )
        expected = str(launch.attestation_hash or "")
        if not expected or not hmac.compare_digest(
            expected, attestation_digest(attestation)
        ):
            raise SessionLaunchError(
                "attestation_invalid", "launch attestation is invalid"
            )
        facts = require_registered_session_facts(conn, session_id)
        bind_launch_to_session(
            conn,
            launch=launch,
            session_id=session_id,
            facts=facts,
            now=current,
            wake_after=launch.deadline_at,
        )
        body, body_hash, sender_actor_id = instruction_message(conn, launch.message_id)
        conn.commit()
        return LaunchRegistrationInjection(
            launch_id=launch_id,
            message_id=launch.message_id,
            session_id=session_id,
            sender_actor_id=sender_actor_id,
            body=body,
            body_sha256=body_hash,
        )
    except Exception:
        conn.rollback()
        raise


def complete_launch_injection(
    conn: Any,
    *,
    launch_id: str,
    session_id: str,
    injected: bool,
    now: str | None = None,
) -> LaunchRecord:
    """Record actual model-visible injection; never infer it from registration."""
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.registered_session_id != session_id:
            raise SessionLaunchError("session_mismatch", "launch is bound elsewhere")
        if launch.state == "succeeded":
            conn.commit()
            return launch
        if launch.state != "awaiting_registration":
            raise SessionLaunchError(
                "invalid_state", "launch cannot complete injection"
            )
        p = marker(conn)
        from yoke_core.domain.session_launch_message_attempt import (
            record_launch_instruction_attempt,
        )

        record_launch_instruction_attempt(
            conn,
            message_id=launch.message_id,
            session_id=session_id,
            injected=injected,
            occurred_at=current,
        )
        if injected:
            cursor = conn.execute(
                "UPDATE session_message_recipients SET state = 'injected', "
                f"injection_count = injection_count + 1, last_injected_at = {p} "
                f"WHERE message_id = {p} AND session_id = {p} "
                "AND state IN ('pending','injected')",
                (current, launch.message_id, session_id),
            )
            if not cursor.rowcount:
                raise SessionLaunchError(
                    "receipt_missing", "instruction receipt is missing"
                )
            result = update_launch(
                conn,
                launch_id,
                state="succeeded",
                completed_at=current,
                result_code="registered_and_injected",
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                result_code="instruction_delivery_deferred",
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def complete_launch_for_message(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: str | None = None,
    commit: bool = True,
) -> LaunchRecord | None:
    """Let the ordinary message-delivery completion close a bound launch."""
    current = now or utc_now()
    begin_mutation(conn)
    p = marker(conn)
    try:
        row = conn.execute(
            f"SELECT launch_id FROM session_launches WHERE message_id = {p}",
            (message_id,),
        ).fetchone()
        if row is None:
            if commit:
                conn.commit()
            return None
        launch_id = str(value(row, "launch_id", 0))
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.registered_session_id != session_id:
            raise SessionLaunchError("session_mismatch", "launch is bound elsewhere")
        if launch.state == "succeeded":
            if commit:
                conn.commit()
            return launch
        from yoke_core.domain.session_launch_delivery_state import (
            TERMINAL_DELIVERY_STATES,
            close_launch_delivery,
        )

        if launch.state in TERMINAL_DELIVERY_STATES:
            close_launch_delivery(
                conn,
                launch_id=launch_id,
                state=launch.state,
                changed_at=str(launch.completed_at or current),
            )
            if commit:
                conn.commit()
            return launch
        if launch.state != "awaiting_registration":
            raise SessionLaunchError(
                "invalid_state", "launch cannot complete from message delivery"
            )
        receipt = conn.execute(
            "SELECT state FROM session_message_recipients "
            f"WHERE message_id = {p} AND session_id = {p}",
            (message_id, session_id),
        ).fetchone()
        if receipt is None or value(receipt, "state", 0) != "injected":
            raise SessionLaunchError(
                "receipt_not_injected",
                "message delivery has not proven injection",
            )
        completed = update_launch(
            conn,
            launch_id,
            state="succeeded",
            completed_at=current,
            result_code="registered_and_injected",
        )
        if commit:
            conn.commit()
        return completed
    except Exception:
        if commit:
            conn.rollback()
        raise


__all__ = [
    "complete_launch_for_message",
    "complete_launch_injection",
    "prepare_launch_registration",
]
