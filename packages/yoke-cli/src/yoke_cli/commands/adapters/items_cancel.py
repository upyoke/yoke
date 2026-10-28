"""``yoke items cancel`` adapter for ``items.cancel.run``.

Consumes the structured close path: work-claim scoping, frozen-item
handling, worktree-lane release, dependency reconciliation, and GitHub
close/comment happen in the handler. The caller supplies the item, a
one-line reason, and an optional superseding-item ``--ref``.

The handler releases the lane ROWS; the directories and branches they
describe live on this machine, so the shared terminal-lane retirement in
:mod:`yoke_cli.commands._helpers` runs here afterwards, exactly as it does
for a lifecycle transition that lands on ``cancelled``. For a cancelled item
that retirement deletes every lane outright (``cancelled_lane_discard``).
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
    "[--abandon-merged] [--project P] [--session-id S] [--json]"
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
    if parsed.abandon_merged:
        payload["abandon_merged"] = True
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
        usage=ITEMS_CANCEL_USAGE,
        description=(
            "Cancel an item that will never resume. For work that will come "
            "back, use `yoke items freeze` instead.\n\n"
            "The command claims the item for you, sets it to cancelled with "
            "the reason, closes the GitHub issue, and releases the claim. "
            "It refuses if another session holds the item.\n\n"
            "Cancelling removes every dependency that names the item, both "
            "the ones it waits on and the ones where other items wait on it, "
            "because a cancelled item can never satisfy a dependency. The "
            "receipt lists each removed edge. Each dependent item with a live "
            "holder gets one message naming the cancelled item and the --ref "
            "replacement, if any; edges are not moved onto the replacement, "
            "so a holder who still needs that work adds the dependency "
            "itself with `yoke items dependency add`.\n\n"
            "Cancelling is an administrative close, not work, so the "
            "session's model level is not checked. A session in any "
            "project may cancel."
            "\n\n"
            "Cancelling deletes all of the item's lanes, because the work is "
            "not wanted: every lane worktree on this machine is removed even "
            "when dirty, locked or unmerged, then its local branch and its "
            "branch on origin. Each lane's head SHAs and discarded "
            "uncommitted path count are written to the item's Progress Log "
            "first. Other machines delete their copies on their relay's "
            "next lane sweep. A step git refuses prints a warning naming "
            "the lane.\n\n"
            "Frozen items: cancel does not require a prior thaw. Freeze and "
            "cancel are different intents; a cancelled item is terminal, so "
            "frozen is cleared as part of this close. There is no --thaw "
            "flag.\n\n"
            "--abandon-merged lets a caller with project items.write permission "
            "close merged work that cannot finish. It preserves merge "
            "evidence and records the actor, session, prior status and reason "
            "in resolution_comment in the same transaction. It does not "
            "undo the code merge or mark the item delivered. Live deployment "
            "run membership refuses merged_item_live_deployment_run: first "
            "use yoke deployment-runs remove-item RUN ITEM --reason TEXT "
            "for each named run, then retry abandonment. Removal obeys its "
            "own gates; if unavailable, finish or cancel the run first."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="Item to cancel.")
    parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="One-line reason, stored as the item's resolution.",
    )
    parser.add_argument(
        "--ref",
        default=None,
        metavar="PREFIX-M",
        help="Item that replaces this one, if any; stored as resolution_ref.",
    )
    add_session_arg(parser)
    parser.add_argument(
        "--abandon-merged", action="store_true",
        help="Close merged work with project items.write permission; see above.",
    )
    add_json_arg(parser)
    return parser


def _write_receipt(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    ref = str(result.get("public_ref") or "item")
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
        _write_dependency_report(result.get("dependency_reconciliation") or {}, stdout)
        return
    print(f"{ref}: already cancelled with that reason — no change.", file=stdout)


def _write_dependency_report(recon: Dict[str, Any], stdout: TextIO) -> None:
    """List removed dependency edges and what each dependent's holder heard."""
    outbound = recon.get("outbound_removed") or []
    if outbound:
        print(f"Removed {len(outbound)} dependency edge(s) this item waited on.", file=stdout)
    inbound = recon.get("inbound_removed") or []
    if inbound:
        print(f"Removed {len(inbound)} dependency edge(s) waiting on this item:", file=stdout)
        for edge in inbound:
            print(
                f"  - {edge.get('dependent_item')} gate={edge.get('gate_point')} "
                f"satisfaction={edge.get('satisfaction')}",
                file=stdout,
            )
    for notice in recon.get("holder_notices") or []:
        dependent = notice.get("dependent_item")
        delivery = notice.get("delivery")
        if delivery == "no_live_holder":
            print(f"  {dependent} has no live holder; no message sent.", file=stdout)
        elif delivery == "cancelling_session":
            print(f"  {dependent} is held by this session; no message sent.", file=stdout)
        else:
            print(
                f"  Told {dependent}'s holder session "
                f"{notice.get('holder_session_id')} ({delivery}).",
                file=stdout,
            )
    if recon.get("notice_advisory"):
        print(f"Warning: {recon['notice_advisory']}", file=stdout)


__all__ = [
    "ITEMS_CANCEL_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "items_cancel",
]
