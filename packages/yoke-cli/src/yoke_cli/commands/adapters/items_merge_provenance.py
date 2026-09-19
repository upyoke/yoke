"""``yoke items merge-provenance operator-correct`` flag adapter.

Covers ``items.merge_provenance.operator_correct`` — the human-only repair
of how an item's landing is recorded. Two corrections, either or both:

``--merged-at``
    For a terminal item whose ``merged_at`` was never recorded, which
    happens when a branch lands outside the merge boundary (a hand-run
    ``gh pr merge``, for example) and the item then reaches a terminal
    stage with the field still unset. Terminal items are otherwise
    immutable, and that is deliberate: the ordinary scalar-write path
    requires a work claim, and a terminal item cannot be claimed. This is
    the single named exception, so it stays narrow — it fills an unset
    value and nothing else. See ``.yoke/docs/reference/lifecycle.md``.

``--pr-number``
    For an item pointing at a pull request that never merged while a
    sibling one carried its commits in. The replacement is verified
    against GitHub before anything is written.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)


__all__ = [
    "items_merge_provenance_operator_correct",
    "ITEMS_MERGE_PROVENANCE_OPERATOR_CORRECT_USAGE",
]


ITEMS_MERGE_PROVENANCE_OPERATOR_CORRECT_USAGE = (
    "yoke items merge-provenance operator-correct <PREFIX-N> "
    "[--merged-at YYYY-MM-DDTHH:MM:SSZ] [--pr-number N] --reason TEXT "
    "[--session-id S] [--json]"
)

_EPILOG = """\
When to reach for --merged-at
-----------------------------
Only when an item is ALREADY terminal and its merged_at is unset. A live
item records its merge through the merge boundary — `yoke merge item
<PREFIX-N>` — which stamps the timestamp itself; use that instead.

  * a hook context is refused (this command is human-only)
  * an item that is not yet terminal      -> use `yoke merge item`
  * an item whose merged_at is already set -> recorded provenance is immutable
  * a timestamp that does not parse, or that is in the future

When to reach for --pr-number
-----------------------------
When the item records a pull request that never merged — typically because
this lane's commits reached the base under a sibling pull request, leaving
this one open forever. Close-out then keeps asking that open pull request
about a merge it never performed. Repointing the item at the real carrier
is what lets the merge-group receipt and the landing observation resolve.

  * the replacement must be MERGED on this project's repository; GitHub is
    read before anything is written, and an open one is refused by name
  * the predecessor's queue admission, landing stamp and observation row
    are dropped with the number they belonged to

Every accepted correction emits its WARN event — OperatorMergedAtCorrection
or OperatorLandingPullRequestCorrection — carrying the operator reason,
before the write lands.

Examples
--------
  yoke items merge-provenance operator-correct YOK-1234 \\
    --merged-at 2026-08-01T18:42:00Z \\
    --reason "branch landed via gh pr merge; PR merge path unavailable"

  yoke items merge-provenance operator-correct YOK-1234 --pr-number 1276 \\
    --reason "PR 1259 never merged; 1276 carried these commits"

Recovering the real timestamp: read the merge commit's date from git, e.g.
`git log -1 --format=%cI <merge-sha>`, and convert it to UTC.
"""


def items_merge_provenance_operator_correct(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items merge-provenance operator-correct",
        description=ITEMS_MERGE_PROVENANCE_OPERATOR_CORRECT_USAGE,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument(
        "--merged-at",
        default="",
        dest="merged_at",
        help=(
            "When the branch actually landed, as YYYY-MM-DDTHH:MM:SSZ "
            "(UTC). Must not be in the future. Fills an unset value on an "
            "already-terminal item."
        ),
    )
    parser.add_argument(
        "--pr-number",
        default="",
        dest="pr_number",
        help=(
            "The pull request that actually merged this item's work. "
            "Verified merged against GitHub before the item is repointed."
        ),
    )
    parser.add_argument(
        "--reason",
        required=True,
        help=(
            "Non-empty operator justification. Recorded on the WARN "
            "correction event."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project context for bare numeric item refs.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, ITEMS_MERGE_PROVENANCE_OPERATOR_CORRECT_USAGE
    )
    if parsed is None:
        return 2

    if not (parsed.merged_at or parsed.pr_number):
        parser.error("pass --merged-at, --pr-number, or both")
    payload: Dict[str, Any] = {
        "merged_at": parsed.merged_at,
        "pr_number": parsed.pr_number,
        "operator_reason": parsed.reason,
    }
    return dispatch_and_emit(
        function_id="items.merge_provenance.operator_correct",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
