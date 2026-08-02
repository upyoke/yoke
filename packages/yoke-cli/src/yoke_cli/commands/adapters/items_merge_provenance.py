"""``yoke items merge-provenance operator-correct`` flag adapter.

Covers ``items.merge_provenance.operator_correct`` — the human-only repair
for a terminal item whose ``merged_at`` was never recorded, which happens
when a branch lands outside the merge boundary (a hand-run ``gh pr merge``,
for example) and the item then reaches a terminal stage with the field
still unset.

Terminal items are otherwise immutable, and that is deliberate: the
ordinary scalar-write path requires a work claim, and a terminal item
cannot be claimed. This surface is the single named exception, so it is
deliberately narrow — it fills an unset value on an already-terminal item
and nothing else. See ``.yoke/docs/lifecycle.md`` for the contract.
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
    "--merged-at YYYY-MM-DDTHH:MM:SSZ --reason TEXT [--session-id S] [--json]"
)

_EPILOG = """\
When to reach for this
----------------------
Only when an item is ALREADY terminal and its merged_at is unset. A live
item records its merge through the merge boundary — `yoke merge item
<PREFIX-N>` — which stamps the timestamp itself; use that instead.

What it refuses
---------------
  * a hook context (this command is human-only)
  * an item that is not yet terminal      -> use `yoke merge item`
  * an item whose merged_at is already set -> recorded provenance is immutable
  * a timestamp that does not parse, or that is in the future

Every accepted correction emits a WARN OperatorMergedAtCorrection event
carrying the operator reason, before the write lands.

Example
-------
  yoke items merge-provenance operator-correct YOK-1234 \\
    --merged-at 2026-08-01T18:42:00Z \\
    --reason "branch landed via gh pr merge; PR merge path unavailable"

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
        required=True,
        dest="merged_at",
        help=(
            "When the branch actually landed, as YYYY-MM-DDTHH:MM:SSZ "
            "(UTC). Must not be in the future."
        ),
    )
    parser.add_argument(
        "--reason",
        required=True,
        help=(
            "Non-empty operator justification. Recorded on the WARN "
            "OperatorMergedAtCorrection event."
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

    payload: Dict[str, Any] = {
        "merged_at": parsed.merged_at,
        "operator_reason": parsed.reason,
    }
    return dispatch_and_emit(
        function_id="items.merge_provenance.operator_correct",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
