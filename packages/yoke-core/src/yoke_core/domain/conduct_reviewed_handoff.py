"""Post-simulation reviewed-implementation handoff.

Encapsulates the three-step sequence that must run after a clean integration
simulation before an epic can advance to ``reviewed-implementation``:

1. Pre-advance parent-status check — parent must be
   ``reviewing-implementation``.
2. Authoritative epic simulation gate — runs the Python
   ``qa_gates.check_epic_simulation_gate`` directly.
3. In-process status write to ``reviewed-implementation`` via the backlog
   domain (sanctioned mutation surface, respects the pre-check when called
   with ``YOKE_STATUS_SOURCE=conduct-reviewed-handoff``).
4. Post-write verification.

CLI contract::

    python3 -m yoke_core.domain.conduct_reviewed_handoff [--session-id SESSION_ID] <epic_item_id>

Exit codes:
    0 — success (parent is now ``reviewed-implementation``)
    1 — pre-condition failure / usage error
    2 — simulation gate failure
    3 — status write failed or post-write verification failed
    4 — status handoff succeeded but claim release failed
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Optional

from yoke_core.domain.sessions_lifecycle_release_failure import (
    RELEASE_FAILURE_ALREADY_TERMINAL,
    RELEASE_FAILURE_ITEM_NOT_FOUND,
)

_IDEMPOTENT_RELEASE_MISSES = frozenset({
    RELEASE_FAILURE_ALREADY_TERMINAL,
    RELEASE_FAILURE_ITEM_NOT_FOUND,
})


def _resolve_session_id(session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return session_id
    return (
        os.environ.get("YOKE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
    )


def _release_conduct_claim(
    epic_id: int,
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Release the Conduct-owned item claim after successful handoff."""
    effective_session_id = _resolve_session_id(session_id)
    if not effective_session_id:
        return {"released": False, "reason": "missing_session_id"}

    try:
        from yoke_core.domain.sessions import release_item_claim_for_execution
        from yoke_core.domain.db_helpers import connect

        with connect() as conn:
            result = release_item_claim_for_execution(
                conn, effective_session_id, str(epic_id), "handoff-to-polish"
            )
        if result.get("released"):
            print(
                "Claim released: YOK-%d (reason=handoff-to-polish)" % epic_id
            )
        return result
    except Exception as exc:
        return {"released": False, "reason": "exception", "error": str(exc)}


def _normalize_item_id(raw: str) -> Optional[int]:
    stripped = raw.strip()
    if stripped.upper().startswith("YOK-"):
        stripped = stripped[4:]
    stripped = stripped.lstrip("0")
    if stripped == "":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _fetch_status(epic_id: int) -> Optional[str]:
    from yoke_core.domain import db_backend, db_helpers

    try:
        with db_helpers.connect() as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = db_helpers.query_one(
                conn,
                f"SELECT status FROM items WHERE id = {p}",
                (epic_id,),
            )
    except Exception as exc:  # pragma: no cover - surface DB errors to caller
        print("Error: DB read failed for YOK-%d: %s" % (epic_id, exc), file=sys.stderr)
        return None
    if row is None:
        return None
    return row["status"]


def _run_simulation_gate(epic_id: int) -> int:
    """Invoke the authoritative epic simulation gate directly in-process."""
    if os.environ.get("YOKE_SKIP_SIMULATION", "0") == "1":
        print(
            "WARNING: Integration simulation gate bypassed via YOKE_SKIP_SIMULATION "
            "for YOK-%d" % epic_id,
            file=sys.stderr,
        )
        return 0

    from yoke_core.domain.qa_gates import check_epic_simulation_gate

    try:
        result = check_epic_simulation_gate(epic_id, "")
    except Exception as exc:
        print(
            "Error: simulation gate raised: %s" % exc,
            file=sys.stderr,
        )
        return 1
    result.emit_errors()
    return 0 if result.passed else 1


def _run_status_write(epic_id: int) -> tuple[int, str]:
    """Route the status write through the sanctioned mutation surface.

    Calls the owned backlog domain in-process. Side-effects stay identical —
    ``ItemStatusChanged`` emission, backlog view regeneration, GitHub sync
    hooks. Conduct owns the board rebuild separately, so ``rebuild_board``
    stays ``False``.
    """
    from yoke_core.domain import backlog

    previous_bypass = os.environ.get("YOKE_CLAIM_BYPASS")
    previous_source = os.environ.get("YOKE_STATUS_SOURCE")
    os.environ["YOKE_STATUS_SOURCE"] = "conduct-reviewed-handoff"
    os.environ["YOKE_CLAIM_BYPASS"] = "conduct-reviewed-handoff"

    import io as _io

    captured = _io.StringIO()
    qa_bypass = os.environ.get("YOKE_QA_GATE_BYPASS", "0") == "1"
    try:
        result = backlog.execute_update(
            item_id=epic_id,
            field="status",
            value="reviewed-implementation",
            qa_bypass=qa_bypass,
            rebuild_board=False,
            out=captured,
        )
    except Exception as exc:
        return 1, "execute_update raised: %s" % exc
    finally:
        if previous_bypass is None:
            os.environ.pop("YOKE_CLAIM_BYPASS", None)
        else:
            os.environ["YOKE_CLAIM_BYPASS"] = previous_bypass
        if previous_source is None:
            os.environ.pop("YOKE_STATUS_SOURCE", None)
        else:
            os.environ["YOKE_STATUS_SOURCE"] = previous_source

    combined = captured.getvalue()
    if not result.get("success"):
        err = result.get("error") or "update failed"
        return 1, (combined + ("\n" if combined and not combined.endswith("\n") else "") + err)
    return 0, combined


def run(epic_id: int, *, session_id: Optional[str] = None) -> int:
    # Step 1: Pre-advance parent-status check
    pre_status = _fetch_status(epic_id)
    if pre_status != "reviewing-implementation":
        print(
            "Error: Cannot advance epic YOK-%d to reviewed-implementation — "
            "parent status is '%s', expected 'reviewing-implementation'."
            % (epic_id, pre_status or "<not found>"),
            file=sys.stderr,
        )
        print(
            "The review gate was not reached. Investigate auto_derive_epic_status.",
            file=sys.stderr,
        )
        return 1

    # Step 2: Authoritative epic simulation gate
    gate_rc = _run_simulation_gate(epic_id)
    if gate_rc != 0:
        print(
            "Error: Simulation gate failed for epic YOK-%d. Cannot advance to reviewed-implementation."
            % epic_id,
            file=sys.stderr,
        )
        return 2

    # Step 3: Canonical status write
    write_rc, write_output = _run_status_write(epic_id)
    if write_rc != 0:
        if write_output:
            print(write_output.rstrip(), file=sys.stderr)
        print(
            "Error: Status write failed for epic YOK-%d. "
            "Cannot advance to reviewed-implementation." % epic_id,
            file=sys.stderr,
        )
        return 3

    # Step 4: Post-write verification
    post_status = _fetch_status(epic_id)
    if post_status != "reviewed-implementation":
        print(
            "Error: Post-write verification failed for epic YOK-%d." % epic_id,
            file=sys.stderr,
        )
        print(
            "Status write to reviewed-implementation did not take effect — "
            "current status is '%s'." % (post_status or "<missing>"),
            file=sys.stderr,
        )
        print(
            "This is the exact failure mode from the April 6 2026 claim-attribution incident.",
            file=sys.stderr,
        )
        return 3

    print(
        "Epic YOK-%d: reviewing-implementation → reviewed-implementation (verified)"
        % epic_id
    )

    # Auto-release the Conduct item claim
    release_result = _release_conduct_claim(epic_id, session_id=session_id)
    release_reason = str(
        release_result.get("failure_reason")
        or release_result.get("reason", "")
    )
    if (
        not release_result.get("released")
        and release_reason not in _IDEMPOTENT_RELEASE_MISSES
    ):
        detail = str(release_result.get("error") or release_reason or "unknown")
        print(
            "Error: claim release failed for YOK-%d after verified handoff: %s"
            % (epic_id, detail),
            file=sys.stderr,
        )
        return 4

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="conduct-reviewed-handoff")
    parser.add_argument(
        "--session-id",
        help="Explicit session ID for claim release (falls back to env vars)",
    )
    parser.add_argument(
        "epic_id",
        help="Epic item ID (YOK-N or N)",
    )
    args = parser.parse_args(argv)

    epic_id = _normalize_item_id(args.epic_id)
    if epic_id is None:
        print(
            "Error: invalid epic ID: %s" % args.epic_id,
            file=sys.stderr,
        )
        return 1
    return run(epic_id, session_id=args.session_id)


if __name__ == "__main__":
    sys.exit(main())
