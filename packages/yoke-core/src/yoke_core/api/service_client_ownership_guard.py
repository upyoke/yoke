"""``service-client ownership-guard`` — runtime ownership check.

Read-only CLI surface over
:func:`yoke_core.domain.sessions_offer_ownership_guard.evaluate_ownership_guard`.
Called by ``/yoke do``'s ``resume`` dispatch before re-dispatching an
item-scoped routed handler so the loop can detect mid-step claim loss
before issuing a stale dispatch.

Usage::

    python3 -m yoke_core.api.service_client ownership-guard --item YOK-N

Resolves ``--session-id`` from the standard env chain
(``YOKE_SESSION_ID`` / ``CLAUDE_SESSION_ID`` / ``CODEX_THREAD_ID``)
when the flag is omitted. Always prints one JSON object to stdout on
success; non-zero exit only on argument or DB-connection errors.

The command does NOT mutate state. It is the runtime-side companion to
the routed-ownership defense recorded in :mod:`frontier_recent_owner`
and the offer-envelope merge in :mod:`sessions_offer`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from yoke_core.domain.sessions_offer_ownership_guard import (
    evaluate_ownership_guard,
)
from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readonly,
    _resolve_session_id,
    normalize_claim_item_id,
)


OWNERSHIP_GUARD_EXIT_OK = 0
OWNERSHIP_GUARD_EXIT_USAGE = 2


def cmd_ownership_guard(args: list[str]) -> int:
    """Return runtime ownership status for the active session over ``--item``.

    Output JSON shape (always printed to stdout on success)::

        {"owned": bool,
         "holder_session_id": str | null,
         "claim_id": int | null,
         "defense_in_flight": bool}
    """
    parser = argparse.ArgumentParser(prog="ownership-guard", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--item", required=True,
        help="Item target (YOK-N or bare numeric)",
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: ownership-guard [--session-id S] --item YOK-N",
            file=sys.stderr,
        )
        return OWNERSHIP_GUARD_EXIT_USAGE

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return OWNERSHIP_GUARD_EXIT_USAGE

    try:
        item_id = int(normalize_claim_item_id(parsed.item))
    except (ValueError, TypeError) as exc:
        print(f"Error: --item not parseable: {exc}", file=sys.stderr)
        return OWNERSHIP_GUARD_EXIT_USAGE

    conn = _get_db_readonly()
    try:
        result = evaluate_ownership_guard(
            conn, session_id=parsed.session_id, item_id=item_id,
        )
    finally:
        conn.close()

    print(json.dumps(asdict(result)))
    return OWNERSHIP_GUARD_EXIT_OK


OWNERSHIP_GUARD_COMMANDS = {
    "ownership-guard": cmd_ownership_guard,
}


__all__ = [
    "OWNERSHIP_GUARD_COMMANDS",
    "cmd_ownership_guard",
]
