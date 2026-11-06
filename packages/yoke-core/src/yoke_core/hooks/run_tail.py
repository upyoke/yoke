"""Post-chain tail for ``run_event``: batched telemetry flush + lifecycle.

Remote runs register inline for launch attestation, then persist observations,
turn posture, lifecycle and telemetry after the response. Local runs persist
inline. The relay client subset skips this tail; the server owns remote writes.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.hook_driver_process import (
    DRIVER_PAYLOAD_KEY,
    resolve_driver_process,
)
from yoke_contracts.hook_evaluator_protocol import (
    evaluator_telemetry_fields,
    hook_call_identity_fields,
)
from yoke_contracts.hook_runner.chain_registry import TERMINAL_HOOK_EVENTS


def _str_or(value: Any, default: Optional[str] = None) -> Optional[str]:
    return value if isinstance(value, str) else default


def _ensure_session_request(
    *,
    event_name: str,
    context: Any,
    payload: Any,
    stdin_data: str,
    controls: Any,
    preflight_complete: bool,
    driver: dict[str, Any] | None = None,
) -> tuple[Any, ...] | None:
    """Build registration proof only for hooks that demonstrate live work."""
    from yoke_core.hooks.cursor_payload import is_folded_cursor_session

    if event_name in TERMINAL_HOOK_EVENTS:
        return None
    if not context.session_id:
        return None
    if isinstance(payload, dict) and is_folded_cursor_session(payload):
        return None
    remote = controls is not None and controls.remote
    force = remote and event_name in ("SessionStart", "UserPromptSubmit")
    ensure_payload = (
        {**payload, DRIVER_PAYLOAD_KEY: driver}
        if isinstance(payload, dict) and driver is not None
        else payload
    )
    return (
        context.session_id,
        json.dumps(ensure_payload)
        if isinstance(ensure_payload, dict)
        else (stdin_data or ""),
        _str_or(payload.get("transcript_path"), "") or "",
        not remote,
        (context.executor_family or "") if remote else "",
        True,
        force and not preflight_complete,
        controls.actor_id if remote else None,
        payload.get("project_id") if isinstance(payload, dict) else None,
    )


def _observed_session_request(
    *,
    context: Any,
    payload: Any,
    stdin_data: str,
    controls: Any = None,
) -> tuple[Any, ...] | None:
    """Build an observation of a row that exists, with no registration authority.

    The executor is the family this dispatch actually ran through, so the
    reading is taken against the harness that is really serving this
    session rather than against whatever the ambient environment looks
    like. Unlike registration this is built for terminal hooks too: a
    turn's served model and consumption are first provable once the turn
    has ended, and a single-turn answer that calls no tool has no other
    hook left to prove them on.

    Whether this process is the one running the session travels with the
    request, read from the dispatch controls rather than from the payload,
    because a relayed evaluation reading its own machine's artifacts would
    answer for the wrong session entirely.
    """
    if not context.session_id:
        return None
    payload_json = (
        json.dumps(payload) if isinstance(payload, dict) else (stdin_data or "")
    )
    return (
        context.session_id,
        payload_json,
        context.executor_family or "",
        not (controls is not None and controls.remote),
    )


def preflight_remote_registration(
    *,
    event_name: str,
    context: Any,
    payload: Any,
    stdin_data: str,
    controls: Any,
    deadline: Any,
) -> bool:
    """Register remote opening events before launch attestation reads the row."""
    if (
        controls is None
        or not controls.remote
        or event_name not in ("SessionStart", "UserPromptSubmit")
    ):
        return False
    ensure_session = _ensure_session_request(
        event_name=event_name,
        context=context,
        payload=payload,
        stdin_data=stdin_data,
        controls=controls,
        preflight_complete=False,
        driver=resolve_driver_process(
            payload if isinstance(payload, dict) else None,
            hook_event=event_name,
        ),
    )
    if ensure_session is None:
        return False
    from yoke_core.hooks import telemetry as _telemetry

    _telemetry.flush_hook_telemetry(
        [],
        deadline=deadline,
        ensure_session=ensure_session,
    )
    return True


def flush_run_tail(
    *,
    event_name: str,
    context,
    chain_length: int,
    final_outcome: str,
    hook_wait_ms: int,
    timed_out: bool,
    deadline,
    payload,
    stdin_data: str,
    controls,
    telem_records: list,
    registration_preflight: bool = False,
) -> None:
    """Register inline; defer remote bookkeeping without changing guard results."""
    from yoke_core.hooks import telemetry as _telemetry
    from yoke_core.hooks.session_turn_posture_tail import (
        persist_accepted_hook_turn_posture,
    )

    failed = any(kind == "failed" for kind, _record in telem_records)
    observed_session = _observed_session_request(
        context=context,
        payload=payload,
        stdin_data=stdin_data,
        controls=controls,
    )
    defer = controls is not None and controls.remote
    if not deadline.telemetry_allowed() and not defer:
        _telemetry.flush_hook_telemetry([], observed_session=observed_session)
        persist_accepted_hook_turn_posture(
            event_name=event_name,
            session_id=context.session_id or "",
            observed_at=getattr(context, "now", None),
            final_outcome=final_outcome,
            timed_out=timed_out,
            failed=failed,
        )
        return
    # One resolved answer to "which process drove this hook event", read by
    # both consumers below: the telemetry row, and — when this dispatch
    # revives an ended session — the reactivation's own driver stamp.
    driver = resolve_driver_process(
        payload if isinstance(payload, dict) else None, hook_event=event_name
    )
    dispatch_extra: dict[str, Any] = {
        "hook_wait_ms": hook_wait_ms,
        "timed_out": timed_out,
        "total_timeout_ms": deadline.budget_ms,
        "driver_pid": driver.get("pid"),
        "driver_ppid": driver.get("ppid"),
        "driver_origin": driver.get("origin"),
        **evaluator_telemetry_fields(payload),
        **hook_call_identity_fields(payload),
    }
    telem_records.append(
        (
            "dispatch",
            {
                "hook_event": event_name,
                "executor": context.executor_family,
                "chain_length": chain_length,
                "decision_outcome": final_outcome,
                "session_id": context.session_id or "",
                "item_id": context.item_id,
                "tool_name": context.tool_name or "",
                "duration_ms": hook_wait_ms,
                "extra": dispatch_extra,
            },
        )
    )
    ensure_session = _ensure_session_request(
        event_name=event_name,
        context=context,
        payload=payload,
        stdin_data=stdin_data,
        controls=controls,
        preflight_complete=registration_preflight,
        driver=driver,
    )
    _telemetry.flush_hook_telemetry(
        [] if defer else telem_records,
        deadline=deadline,
        ensure_session=ensure_session,
        observed_session=None if defer else observed_session,
    )
    if defer:
        from yoke_core.hooks.deferred_tail import deferred_flush

        controls.deferred_telemetry = deferred_flush(
            telem_records,
            dispatch_extra,
            observed_session=observed_session,
            event_name=event_name,
            context=context,
            final_outcome=final_outcome,
            timed_out=timed_out,
            failed=failed,
        )
        return
    persist_accepted_hook_turn_posture(
        event_name=event_name,
        session_id=context.session_id or "",
        observed_at=getattr(context, "now", None),
        final_outcome=final_outcome,
        timed_out=timed_out,
        failed=failed,
    )


__all__ = ["flush_run_tail", "preflight_remote_registration"]
