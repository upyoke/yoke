"""``yoke lifecycle repair-status`` transport adapter."""

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


LIFECYCLE_REPAIR_STATUS_USAGE = (
    "yoke lifecycle repair-status <PREFIX-N> --to STATUS --reason TEXT "
    "[--from STATUS] [--dry-run] [--session-id S] [--json]"
)


def lifecycle_repair_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke lifecycle repair-status",
        description=("Operator-only, audited repair of one item's lifecycle status."),
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument(
        "--to",
        dest="to_status",
        required=True,
        help="Target lifecycle status declared by the item's workflow.",
    )
    parser.add_argument(
        "--from",
        dest="from_status",
        default=None,
        help="Optional precondition: current status must equal this.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Operator-authored incident or reconciliation rationale.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview without changing item state.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        LIFECYCLE_REPAIR_STATUS_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "target_status": parsed.to_status,
        "reason": parsed.reason,
        "dry_run": bool(parsed.dry_run),
    }
    if parsed.from_status:
        payload["source_status"] = parsed.from_status
    return dispatch_and_emit(
        function_id="lifecycle.repair_status.execute",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "LIFECYCLE_REPAIR_STATUS_USAGE",
    "lifecycle_repair_status",
]
