"""``yoke items freeze|thaw|block|unblock`` flag adapters.

Covers the four item coordination-flag function ids —
``items.freeze.run``, ``items.thaw.run``, ``items.block.run``, and
``items.unblock.run``. Each command applies its flag write and its
preconditions server-side in one call; the caller supplies only the item
reference (and, for ``block``, the reason).
"""

from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)


__all__ = [
    "ITEMS_BLOCK_USAGE",
    "ITEMS_FREEZE_USAGE",
    "ITEMS_THAW_USAGE",
    "ITEMS_UNBLOCK_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "items_block",
    "items_freeze",
    "items_thaw",
    "items_unblock",
]


ITEMS_FREEZE_USAGE = "yoke items freeze <PREFIX-N> [--session-id S] [--json]"
ITEMS_THAW_USAGE = "yoke items thaw <PREFIX-N> [--session-id S] [--json]"
ITEMS_BLOCK_USAGE = (
    "yoke items block <PREFIX-N> --reason TEXT [--session-id S] [--json]"
)
ITEMS_UNBLOCK_USAGE = "yoke items unblock <PREFIX-N> [--session-id S] [--json]"

USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "items.freeze.run": ITEMS_FREEZE_USAGE,
    "items.thaw.run": ITEMS_THAW_USAGE,
    "items.block.run": ITEMS_BLOCK_USAGE,
    "items.unblock.run": ITEMS_UNBLOCK_USAGE,
}


_CLAIM_NOTE = """
Claim behavior (identical for all four flag verbs)
  These commands need no work claim on the item, and never acquire,
  steal, or release one. A flag verb is coordination *about* an item
  rather than a change *to* it: the write moves the item on the board
  and in dispatch routing while leaving its lifecycle status, spec, and
  plan untouched. Requiring a claim would also refuse the verb in its
  main case, because an operator reaches for freeze or block precisely
  when another session is holding the item. Content and lifecycle
  writes (`yoke items scalar update`, `yoke lifecycle transition`)
  still require the claim.

Frozen items
  Block and unblock work on a frozen item. The frozen guard on
  `items scalar update` stops content drift on a parked item; recording
  why a parked item is also blocked is coordination, not drift.
"""


def _build_parser(prog: str, usage: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=f"{usage}\n{description}{_CLAIM_NOTE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "item", help="Item id (PREFIX-N, zero-padded, or project-local number)."
    )
    return parser


def _receipt(changed: Callable[[Dict[str, Any]], str], unchanged: str) -> Any:
    """Build a human writer that reports the post-write flag state."""

    def _write(response: Any, stdout: TextIO, stderr: TextIO) -> None:
        del stderr
        result = response.result or {}
        ref = str(result.get("item_ref") or result.get("item_id") or "item")
        if result.get("changed"):
            print(f"{ref}: {changed(result)}", file=stdout)
        else:
            print(f"{ref}: {unchanged}", file=stdout)

    return _write


def _dispatch(
    function_id: str,
    parsed: argparse.Namespace,
    payload: Dict[str, Any],
    human_writer: Any,
) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=human_writer,
    )


# ---------------------------------------------------------------------------
# freeze / thaw
# ---------------------------------------------------------------------------


def items_freeze(args: List[str]) -> int:
    parser = _build_parser(
        "yoke items freeze",
        ITEMS_FREEZE_USAGE,
        """
Park an item: set `frozen` so it leaves the board's normal status
sections for the Freezer, without changing its lifecycle status. The
item keeps `implementing` / `planned` / whatever it holds, and returns
to the matching section when thawed.

Refuses a done item — a done item is already off the active board.
Advance it back into an in-flight status first if you truly need it
parked. Freezing an already-frozen item is a reported no-op.
""",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_FREEZE_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "items.freeze.run",
        parsed,
        {},
        _receipt(
            lambda r: (
                f"frozen — status {r.get('status')} preserved, hidden from the "
                "active board."
            ),
            "already frozen — no change.",
        ),
    )


def items_thaw(args: List[str]) -> int:
    parser = _build_parser(
        "yoke items thaw",
        ITEMS_THAW_USAGE,
        """
Unpark an item: clear `frozen` so it returns to whichever board section
its preserved lifecycle status dictates. Thawing an item that is not
frozen is a reported no-op.
""",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_THAW_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "items.thaw.run",
        parsed,
        {},
        _receipt(
            lambda r: f"thawed — back on the board in {r.get('status')}.",
            "not frozen — no change.",
        ),
    )


# ---------------------------------------------------------------------------
# block / unblock
# ---------------------------------------------------------------------------


def items_block(args: List[str]) -> int:
    parser = _build_parser(
        "yoke items block",
        ITEMS_BLOCK_USAGE,
        """
Mark an item blocked with an operator-supplied reason, preserving its
lifecycle status. The reason is stored verbatim and surfaces in the
rendered body's Block section, the decision-engine escalate context,
and the blocked details.

Blocking an already-blocked item replaces the recorded reason rather
than refusing. Refuses a done item. The reason is written before the
flag, so a failure between the two writes never leaves a half-applied
block — no reader surfaces a reason without the flag.

Item-level `blocked` is unrelated to `path_claims.state='blocked'`,
which is a coordination state on a single path-claim row owned by the
path-claim activation flow.
""",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Why the item is blocked. Stored verbatim in items.blocked_reason.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_BLOCK_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "items.block.run",
        parsed,
        {"reason": parsed.reason},
        _receipt(
            lambda r: (
                f"blocked — status {r.get('status')} preserved. "
                f"Reason: {r.get('blocked_reason')}"
            ),
            "already blocked with that reason — no change.",
        ),
    )


def items_unblock(args: List[str]) -> int:
    parser = _build_parser(
        "yoke items unblock",
        ITEMS_UNBLOCK_USAGE,
        """
Clear an item's blocked flag and its recorded reason, returning it to
active dispatch in its preserved lifecycle status. Unblocking an item
that is not blocked is a reported no-op.

Path-claim coordination state is independent by design and is not
released here; use the path-claim CLI surface for that.
""",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_UNBLOCK_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "items.unblock.run",
        parsed,
        {},
        _receipt(
            lambda r: f"unblocked — back in dispatch in {r.get('status')}.",
            "not blocked — no change.",
        ),
    )
