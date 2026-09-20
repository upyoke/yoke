"""``yoke items landings ...`` flag adapters.

The audit the single-valued item columns could not serve: which landings an
item actually made, in order, each naming the merge it landed under and the
release that delivered it.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)

ITEM_LANDINGS_LIST_USAGE = (
    "yoke items landings list <PREFIX-N> [--project P] [--session-id S] [--json]"
)

#: How much of a commit sha the human listing shows. Long enough to name a
#: commit in this repository, short enough that a landing fits one line.
_SHA_WIDTH = 12


def _delivery_label(landing: dict) -> str:
    delivery = landing.get("delivery") or {}
    run_id = str(delivery.get("run_id") or "").strip()
    if not run_id:
        return "not delivered"
    flow = str(delivery.get("flow") or "").strip()
    return f"delivered by {run_id}" + (f" ({flow})" if flow else "")


def item_landings_list(args: List[str]) -> int:
    """Read every landing an item has made, oldest first."""
    parser = argparse.ArgumentParser(
        prog="yoke items landings list",
        description=ITEM_LANDINGS_LIST_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or numeric id the item belongs to.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEM_LANDINGS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        rows = (response.result or {}).get("rows") or []
        if not rows:
            print("no landing recorded", file=stdout)
            return
        for landing in rows:
            pr_number = str(landing.get("pr_number") or "").strip()
            print(
                "|".join([
                    str(landing.get("landed_at") or ""),
                    str(landing.get("route") or ""),
                    str(landing.get("merge_sha") or "")[:_SHA_WIDTH],
                    str(landing.get("candidate_sha") or "")[:_SHA_WIDTH],
                    f"#{pr_number}" if pr_number else "",
                    str(landing.get("target_branch") or ""),
                    _delivery_label(landing),
                ]),
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="item_landings.list",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["ITEM_LANDINGS_LIST_USAGE", "item_landings_list"]
