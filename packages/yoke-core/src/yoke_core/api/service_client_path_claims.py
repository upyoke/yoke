"""Service-client surface for path-claim register / read / state-change.

Wires :mod:`yoke_core.domain.path_claims_dispatch` into the Yoke
service-client COMMANDS table so callers that already speak the
service-client protocol (frontier/scheduler/usher dispatchers, future
Python in-process consumers, ad hoc shell wrappers) can request claim
registration, reads, releases, and cancellations through one entry
point::

    python3 -m yoke_core.api.service_client path-claim-register \\
        --item YOK-N --integration-target main --paths a.py,b.py
    python3 -m yoke_core.api.service_client path-claim-get <claim-id>
    python3 -m yoke_core.api.service_client path-claim-list --item YOK-N
    python3 -m yoke_core.api.service_client path-claim-activate <id> \\
        --base-snapshot-id <snapshot-id>
    python3 -m yoke_core.api.service_client path-claim-release <id> --reason R
    python3 -m yoke_core.api.service_client path-claim-unblock-stranded
    python3 -m yoke_core.api.service_client path-claim-cancel <id> --reason R

These commands forward to the dispatcher's named handlers verbatim.
The mirroring exists because the service-client surface is sanctioned
for cross-process consumers that already import it; rather than have
them re-author argparse parsing, the wrapper either hands the raw argv
off to the dispatch module or owns the small recovery command locally.
"""

from __future__ import annotations

import argparse
import json
import sys

from yoke_core.domain.path_claims_dependency_propagation import (
    unblock_stranded_for_released,
)
from yoke_core.domain.path_claims_dispatch import (
    cmd_activate,
    cmd_boundary,
    cmd_cancel,
    cmd_cancel_amendment,
    cmd_conflicts,
    cmd_get,
    cmd_list,
    cmd_narrow,
    cmd_register,
    cmd_release,
    cmd_widen,
)
from yoke_core.domain.path_claims_dispatch_io import open_conn
from yoke_core.domain.path_claims_dispatch_override import cmd_override


def cmd_path_claim_register(args: list[str]) -> int:
    return cmd_register(args)


def cmd_path_claim_get(args: list[str]) -> int:
    """Print the JSON projection for a single path claim.

    Usage: path-claim-get <claim-id>

    Positional claim_id (integer). Same shape as
    ``db_router path-claims get <claim-id>``.
    """
    return cmd_get(args)


def cmd_path_claim_list(args: list[str]) -> int:
    return cmd_list(args)


def cmd_path_claim_conflicts(args: list[str]) -> int:
    return cmd_conflicts(args)


def cmd_path_claim_boundary(args: list[str]) -> int:
    return cmd_boundary(args)


def cmd_path_claim_activate(args: list[str]) -> int:
    return cmd_activate(args)


def cmd_path_claim_widen(args: list[str]) -> int:
    """Widen a path claim with additional paths.

    Usage: path-claim-widen (<claim-id> | --item YOK-N) --paths a.py,b.py

    Identify the claim either by positional claim_id or ``--item YOK-N``
    (resolves to the one non-terminal exclusive claim for that item).
    """
    return cmd_widen(args)


def cmd_path_claim_narrow(args: list[str]) -> int:
    return cmd_narrow(args)


def cmd_path_claim_cancel_amendment(args: list[str]) -> int:
    return cmd_cancel_amendment(args)


def cmd_path_claim_release(args: list[str]) -> int:
    return cmd_release(args)


def cmd_path_claim_cancel(args: list[str]) -> int:
    return cmd_cancel(args)


def cmd_path_claim_override(args: list[str]) -> int:
    return cmd_override(args)


def cmd_path_claim_unblock_stranded(args: list[str]) -> int:
    """Sweep released upstream claims and unblock stranded downstreams.

    Wraps :func:`unblock_stranded_for_released`. With no flag the helper
    iterates every ``state='released'`` row; with ``--claim-id`` it
    targets a single claim. Output is a JSON object naming the flipped
    claim ids and their count so callers can branch on outcome.
    """
    parser = argparse.ArgumentParser(
        prog="path-claim-unblock-stranded", add_help=True,
    )
    parser.add_argument(
        "--claim-id", type=int, default=None,
        help="Optional single released-claim id to propagate; "
             "omit to sweep every released claim.",
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    conn = open_conn()
    try:
        flipped = unblock_stranded_for_released(
            conn, claim_id=ns.claim_id,
        )
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "success": True,
                "flipped_claim_ids": list(flipped),
                "flipped_count": len(flipped),
            }
        )
    )
    return 0


PATH_CLAIMS_COMMANDS = {
    "path-claim-register": cmd_path_claim_register,
    "path-claim-get": cmd_path_claim_get,
    "path-claim-list": cmd_path_claim_list,
    "path-claim-conflicts": cmd_path_claim_conflicts,
    "path-claim-boundary": cmd_path_claim_boundary,
    "path-claim-activate": cmd_path_claim_activate,
    "path-claim-widen": cmd_path_claim_widen,
    "path-claim-narrow": cmd_path_claim_narrow,
    "path-claim-cancel-amendment": cmd_path_claim_cancel_amendment,
    "path-claim-release": cmd_path_claim_release,
    "path-claim-cancel": cmd_path_claim_cancel,
    "path-claim-override": cmd_path_claim_override,
    "path-claim-unblock-stranded": cmd_path_claim_unblock_stranded,
}


__all__ = [
    "PATH_CLAIMS_COMMANDS",
    "cmd_path_claim_boundary",
    "cmd_path_claim_activate",
    "cmd_path_claim_cancel",
    "cmd_path_claim_cancel_amendment",
    "cmd_path_claim_conflicts",
    "cmd_path_claim_get",
    "cmd_path_claim_list",
    "cmd_path_claim_narrow",
    "cmd_path_claim_override",
    "cmd_path_claim_register",
    "cmd_path_claim_release",
    "cmd_path_claim_unblock_stranded",
    "cmd_path_claim_widen",
]


if __name__ == "__main__":  # pragma: no cover - manual module entry
    if len(sys.argv) < 2:
        sys.exit(2)
    handler = PATH_CLAIMS_COMMANDS.get(sys.argv[1])
    if handler is None:
        sys.exit(2)
    sys.exit(handler(sys.argv[2:]))
