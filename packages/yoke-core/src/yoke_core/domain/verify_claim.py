"""Claim verification guard for sanctioned status writers.

Verifies that the acting session holds an active item or exact task claim
before allowing a status mutation.

CLI contract::

    python3 -m yoke_core.domain.verify_claim --item-id <YOK-N|N>

Environment:

* Session identity resolves through the canonical ambient chain
  (env vars, then the process-anchor registry —
  ``yoke_core.domain.session_ambient_identity``).
* ``YOKE_CLAIM_BYPASS`` — if set, bypass verification with audit trail.
  Value is the bypass source (e.g., ``cascade:YOK-N``,
  ``repair-status:reason``, ``auto-unblock``, ``done-cascade``). An empty
  value is *not* a valid bypass.
* ``YOKE_STATUS_SOURCE`` — if it starts with ``repair-status:``, also
  treated as bypass.

Exit codes:
    0 — claim verified (or bypassed with audit)
    1 — claim denied (no claim or wrong session)
    2 — usage error

Stdout:
    JSON ``{"verified": true/false, "session_id": "...", "claimant": "...",
    "reason": "...", "bypassed": true/false}``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from yoke_contracts.public_ref import unresolved_item_ref
from yoke_core.domain.claim_recovery import canonical_item_ref
from yoke_core.domain.status_claim_bypass_context import resolve_claim_bypass
from yoke_core.domain.work_claim_targets import (
    exact_match_clause,
    make_epic_task_target,
    scope_int_sql,
)


def _resolve_session_id() -> str:
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or ""


def _ambient_resolution_failed() -> str:
    from yoke_core.domain.session_ambient_identity import (
        AMBIENT_RESOLUTION_FAILED,
    )

    return AMBIENT_RESOLUTION_FAILED


def _resolve_bypass() -> str:
    # Request-scoped override first (done-transition status relays post it on a
    # ContextVar), then the process-global env vars so env-driven callers are
    # unchanged.
    ctx_bypass, ctx_source = resolve_claim_bypass()
    direct = ctx_bypass or os.environ.get("YOKE_CLAIM_BYPASS", "")
    if direct:
        return direct
    status_source = ctx_source or os.environ.get("YOKE_STATUS_SOURCE", "")
    if status_source.startswith("repair-status:"):
        return status_source
    return ""


def _db_available() -> bool:
    """Return True when Postgres authority is configured for a claim check.

    A resolvable DSN means the gate runs against the authority; an
    unresolvable one preserves the historical fail-open path.
    """
    try:
        from yoke_core.domain import db_backend
    except Exception:
        return False
    try:
        db_backend.resolve_pg_dsn()
    except Exception:
        return False
    return True


def _fetch_claim(
    item_id: int, *, task_num: int | None = None, session_id: str = ""
) -> Optional[dict]:
    """Find parent authority or an exact task claim, preferring the actor.

    A task claim never authorizes another task or a parent item write.
    """
    try:
        from yoke_core.domain import db_helpers
    except Exception:
        return None
    try:
        with db_helpers.connect() as conn:
            item_scope = scope_int_sql(conn, "scope", "item_id")
            match = f"(target_kind='item' AND {item_scope} = %s)"
            params = [int(item_id)]
            ordering = "claimed_at DESC"
            if task_num is not None:
                task_match, task_params = exact_match_clause(
                    conn, make_epic_task_target(item_id, task_num)
                )
                match = f"({match} OR ({task_match}))"
                params.extend(task_params)
                ordering = "(session_id = %s) DESC, claimed_at DESC"
                params.append(session_id)
            row = db_helpers.query_one(
                conn,
                f"SELECT id, session_id, {item_scope} AS item_id, "
                "claim_type, claimed_at "
                "FROM work_claims "
                f"WHERE {match} AND released_at IS NULL "
                f"ORDER BY {ordering} LIMIT 1",
                tuple(params),
            )
    except Exception:
        return None
    if row is None:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "item_id": row["item_id"],
        "claim_type": row["claim_type"],
        "claimed_at": row["claimed_at"],
    }


def _emit_lifecycle_event(
    name: str,
    severity: str,
    outcome: str,
    public_ref: str,
    context: dict,
) -> None:
    """Fire a lifecycle event via the Python emit_event owner."""
    try:
        from yoke_core.domain import emit_event as emit_event_cli
    except Exception:
        return
    try:
        parser = emit_event_cli.build_parser()
        args = parser.parse_args(
            [
                "--name",
                name,
                "--kind",
                "lifecycle",
                "--type",
                "claim_verification",
                "--source-type",
                "system",
                "--severity",
                severity,
                "--outcome",
                outcome,
                "--item-id",
                public_ref,
                "--context",
                json.dumps(context, separators=(",", ":")),
            ]
        )
        emit_event_cli.emit(args)
    except Exception:
        pass


def verify(
    item_id: int, *, task_num: int | None = None, session_id: str | None = None
) -> tuple[int, dict]:
    """Evaluate the verification.

    Returns ``(exit_code, result_dict)`` where the dict is the JSON
    payload written to stdout by ``main``.
    """
    public_ref = canonical_item_ref(item_id) or unresolved_item_ref()
    session_id = _resolve_session_id() if session_id is None else session_id
    bypass_source = _resolve_bypass()

    if bypass_source:
        context = {
            "bypass_source": bypass_source,
            "session_id": session_id or "unknown",
            "work_unit": public_ref,
        }
        _emit_lifecycle_event(
            "ClaimVerificationBypassed",
            "INFO",
            "completed",
            public_ref,
            context,
        )
        return 0, {
            "verified": True,
            "session_id": session_id or "unknown",
            "claimant": "bypass",
            "reason": "audited bypass: %s" % bypass_source,
            "bypassed": True,
        }

    if not session_id:
        _emit_lifecycle_event(
            "ClaimVerificationDenied",
            "WARN",
            "failed",
            public_ref,
            {"failure_type": "no_session_id", "work_unit": public_ref},
        )
        return 1, {
            "verified": False,
            "session_id": "",
            "claimant": "",
            "reason": _ambient_resolution_failed(),
            "bypassed": False,
        }

    if not _db_available():
        return 0, {
            "verified": True,
            "session_id": session_id,
            "claimant": "degraded",
            "reason": "no DB available for claim check — allowing",
            "bypassed": True,
        }

    claim = (
        _fetch_claim(item_id, task_num=task_num, session_id=session_id)
        if task_num is not None
        else _fetch_claim(item_id)
    )
    if claim is None:
        _emit_lifecycle_event(
            "ClaimVerificationDenied",
            "WARN",
            "failed",
            public_ref,
            {
                "failure_type": "no_active_claim",
                "session_id": session_id,
                "work_unit": public_ref,
            },
        )
        return 1, {
            "verified": False,
            "session_id": session_id,
            "claimant": "",
            "reason": "no active claim on %s" % public_ref,
            "bypassed": False,
        }

    claimant = claim.get("session_id") or ""
    if claimant == session_id:
        return 0, {
            "verified": True,
            "session_id": session_id,
            "claimant": claimant,
            "reason": "matching claim verified",
            "bypassed": False,
        }

    _emit_lifecycle_event(
        "ClaimVerificationDenied",
        "WARN",
        "failed",
        public_ref,
        {
            "failure_type": "wrong_session",
            "session_id": session_id,
            "claimant_session": claimant,
            "work_unit": public_ref,
        },
    )
    return 1, {
        "verified": False,
        "session_id": session_id,
        "claimant": claimant,
        "reason": "claim held by different session %s" % claimant,
        "bypassed": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-claim")
    parser.add_argument("--item-id", dest="item_id", required=True)
    args = parser.parse_args(argv)

    from yoke_core.domain.yok_n_parser import parse_item_argument

    try:
        item_num = parse_item_argument(args.item_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    exit_code, payload = verify(item_num)
    print(json.dumps(payload, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
