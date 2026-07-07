"""Post-success finalize recovery for ``execute-update --force``."""

from __future__ import annotations

import io

from yoke_core.api.service_client_shared import (
    _get_db_readwrite,
    _resolve_session_id,
    release_item_claim_for_execution,
)

_FORCE_FINALIZE_REASONS = {
    "reviewed-implementation": "handoff-to-polish",
    "implemented": "handoff-to-usher",
    "release": "finalize-exit",
    "done": "finalize-exit",
    "cancelled": "finalize-exit",
    "stopped": "finalize-exit",
}


def _next_step(item_id: int, status: str) -> str:
    if status == "reviewed-implementation":
        return f"Next: /yoke polish YOK-{item_id}"
    if status == "implemented":
        return f"Next: /yoke usher YOK-{item_id}"
    return f"Force finalize complete for YOK-{item_id} at {status}."


def run_force_finalize_handoff(
    *,
    item_id: int,
    field: str,
    value: str,
    force: bool,
    dry_run: bool,
    result: dict,
    out: io.StringIO,
) -> None:
    """Recover the advance-finalize claim handoff after a forced status write."""
    if dry_run or not force or field != "status" or not result.get("success"):
        return
    release_reason = _FORCE_FINALIZE_REASONS.get(value)
    if release_reason is None:
        return

    session_id = _resolve_session_id(None)
    if not session_id:
        print(
            f"Warning: execute-update --force reached {value} for YOK-{item_id} "
            "but no session id was available for claim handoff.",
            file=out,
        )
        result["force_finalize"] = {"released": False, "failure_reason": "missing_session_id"}
        return

    conn = _get_db_readwrite()
    try:
        try:
            release_result = release_item_claim_for_execution(
                conn, session_id, str(item_id), release_reason,
            )
        except ValueError as exc:
            print(
                f"Warning: claim release failed for YOK-{item_id} "
                f"(reason=domain_error): {exc}",
                file=out,
            )
            result["force_finalize"] = {
                "released": False,
                "failure_reason": "domain_error",
                "error": str(exc),
            }
            return
    finally:
        conn.close()

    result["force_finalize"] = release_result
    if release_result.get("released"):
        print(
            f"Force finalize: released claim for YOK-{item_id} "
            f"with reason {release_reason}.",
            file=out,
        )
    else:
        failure = release_result.get("failure_reason", "unknown")
        holder = release_result.get("holder_session_id")
        holder_clause = f" held by session '{holder}'" if holder else ""
        print(
            f"Warning: claim release failed for YOK-{item_id} "
            f"(reason={failure}){holder_clause}: see events for ItemClaimReleaseFailed.",
            file=out,
        )
    print(_next_step(item_id, value), file=out)


__all__ = ["run_force_finalize_handoff"]
