"""CLI front door for operator-asserted advance skip hops.

This module intentionally keeps the public import and CLI path stable:

    python3 -m yoke_core.domain.advance_skip polish <item-id>
    python3 -m yoke_core.domain.advance_skip refine <item-id>

Flow logic lives in responsibility-named sibling modules. The direct imports
below preserve compatibility for callers that import the public API from this
front door.
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import Optional

from yoke_core.domain.advance_skip_core import (
    BYPASS_SKIP_POLISH,
    BYPASS_SKIP_REFINE,
    _POLISH_END,
    _POLISH_START,
    _POLISH_TRANSIT,
    _POLISH_TRANSIT_ALLOWED,
    _REFINE_ROUTING,
    _REFINE_TARGETS_ALLOWED,
    _do_execute_update,
    _lookup_item,
    _walk_hops,
)
from yoke_core.domain.advance_skip_finalize import (
    _emit_skip_event,
    _release_claim,
)
from yoke_core.domain.advance_skip_polish import skip_polish
from yoke_core.domain.advance_skip_refine import skip_refine

__all__ = [
    "BYPASS_SKIP_POLISH",
    "BYPASS_SKIP_REFINE",
    "main",
    "skip_polish",
    "skip_refine",
]


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


def _run_cli_skip(
    mode: str,
    item_id: int,
    session_id: Optional[str],
) -> int:
    """Dispatch a CLI subcommand to the matching skip function."""
    captured = io.StringIO()
    try:
        if mode == "polish":
            result = skip_polish(item_id, session_id=session_id, out=captured)
        else:
            result = skip_refine(item_id, session_id=session_id, out=captured)
    except (ValueError, RuntimeError) as exc:
        body = captured.getvalue()
        if body:
            sys.stdout.write(body)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    body = captured.getvalue()
    if body:
        sys.stdout.write(body)

    print(
        "Skip {via}: YOK-{item_id} {frm} -> {to} (skipped {phase})".format(
            via=result["via"],
            item_id=item_id,
            frm=result["from_status"],
            to=result["to_status"],
            phase=result["skipped_phase"],
        )
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.advance_skip",
        description=(
            "Operator-asserted skip-phase hops for /yoke advance. "
            "Distinct bypass reasons preserve the pre-implementation "
            "safety invariant (claim-bypass only for gate-free bookkeeping rungs)."
        ),
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_polish = sub.add_parser(
        "polish",
        help=(
            "Skip polish: advance reviewed-implementation -> implemented "
            "in one sanctioned call."
        ),
    )
    p_polish.add_argument("item_id", help="Backlog item id (YOK-N or N)")
    p_polish.add_argument(
        "--session-id",
        default=None,
        help="Explicit session id for claim release (default: env).",
    )

    p_refine = sub.add_parser(
        "refine",
        help=(
            "Skip refine: advance refining-idea -> refined-idea, or "
            "refining-plan -> planned, in one sanctioned call."
        ),
    )
    p_refine.add_argument("item_id", help="Backlog item id (YOK-N or N)")
    p_refine.add_argument(
        "--session-id",
        default=None,
        help="Explicit session id for claim release (default: env).",
    )

    args = parser.parse_args(argv)

    item_id = _normalize_item_id(args.item_id)
    if item_id is None:
        print(f"Error: invalid item id: {args.item_id}", file=sys.stderr)
        return 2

    return _run_cli_skip(args.mode, item_id, args.session_id)


if __name__ == "__main__":
    sys.exit(main())
