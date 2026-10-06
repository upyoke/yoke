"""Flag adapter for attesting commits to an item's merge receipt."""

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


MERGE_RECEIPT_COMMITS_ATTEST_USAGE = (
    "yoke merge-receipt commits attest <PREFIX-N> --commit SHA [--commit SHA ...] "
    "--reason R [--project P] [--session-id S] [--json]"
)

_DESCRIPTION = """\
Optionally tie commits made outside Yoke to an item's landed merge receipt.

Releases carry commits without an item owner and list their SHA, subject and
author as commits made outside Yoke. Attestation is never required to release.
When a commit is this item's work, attest its full SHA here: attribution then
credits it to the item, and the item's delivery obligations follow. Do not
attest unrelated work to an item.

The attestation is stored on the item's newest landed receipt entry beside the
commits the merge derived, with the reason given. It changes no lifecycle state
and does not rewrite carried-work records already frozen on historical runs.
"""


def merge_receipt_commits_attest(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke merge-receipt commits attest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_DESCRIPTION,
    )
    parser.add_argument("item", help="Item id (PREFIX-N).")
    parser.add_argument(
        "--commit",
        action="append",
        required=True,
        help="A full commit SHA that is this item's work. Repeat per commit.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Why these commits are this item's work.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or numeric id the item belongs to.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MERGE_RECEIPT_COMMITS_ATTEST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        result = response.result or {}
        landing = f"{result.get('branch')} -> {result.get('target')}"
        for sha in result.get("attested") or []:
            print(f"attested {sha} to {parsed.item} ({landing})", file=stdout)
        for sha in result.get("already_recorded") or []:
            print(f"already recorded {sha} on {parsed.item} ({landing})", file=stdout)

    return dispatch_and_emit(
        function_id="merge_receipt.commits.attest",
        target=item_target("item", parsed.item, parsed.project),
        payload={"commits": list(parsed.commit), "reason": parsed.reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["MERGE_RECEIPT_COMMITS_ATTEST_USAGE", "merge_receipt_commits_attest"]
