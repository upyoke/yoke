"""``yoke items cancel`` adapter for ``items.cancel.run``.

Consumes the structured close path: work-claim scoping, frozen-item
handling, worktree-lane release, dependency reconciliation, and GitHub
close/comment happen in the handler. The caller supplies the item, a
one-line reason, and an optional superseding-item ``--ref``.
"""

from __future__ import annotations

from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)


ITEMS_CANCEL_USAGE = (
    "yoke items cancel <PREFIX-N> --reason TEXT [--ref PREFIX-M] "
    "[--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "items.cancel.run": ITEMS_CANCEL_USAGE,
}


def items_cancel(args: List[str]) -> int:
    parser = _build_parser()
    parsed = parse_or_usage_error(parser, args, ITEMS_CANCEL_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"reason": parsed.reason}
    if parsed.ref:
        payload["ref"] = parsed.ref
    return dispatch_and_emit(
        function_id="items.cancel.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_receipt,
    )


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="yoke items cancel",
        description=(
            f"{ITEMS_CANCEL_USAGE}\n"
            "Cancel an item that will never resume. This is the sibling of "
            "`yoke items freeze`, which parks work that will come back.\n\n"
            "The command takes the item claim for you, writes cancelled with "
            "the reason, reconciles item_dependencies, closes the GitHub "
            "issue, and releases the claim. A foreign holder is refused.\n\n"
            "Frozen items: cancel does not require a prior thaw. Freeze and "
            "cancel are different intents; a cancelled item is terminal, so "
            "frozen is cleared as part of this close. There is no --thaw "
            "flag.\n\n"
            "--ref records the superseding item when one exists."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "item", help="Item id (PREFIX-N, zero-padded, or project-local number)."
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="One-line reason stored in items.resolution.",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Optional superseding item PREFIX-N stored as resolution_ref.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _write_receipt(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    ref = str(result.get("public_ref") or result.get("item_id") or "item")
    if result.get("changed"):
        extra = ""
        if result.get("frozen_cleared"):
            extra = " Frozen was cleared as part of the terminal close."
        print(
            f"{ref}: cancelled — {result.get('reason')}."
            f"{extra} For work that will resume later, use "
            "`yoke items freeze` instead.",
            file=stdout,
        )
        return
    print(f"{ref}: already cancelled with that reason — no change.", file=stdout)


__all__ = [
    "ITEMS_CANCEL_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "items_cancel",
]
