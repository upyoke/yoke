"""``yoke merge-review`` product adapter for candidate-review clearance."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


MERGE_REVIEW_CANDIDATE_EVALUATE_USAGE = (
    "yoke merge-review candidate evaluate ITEM --commit SHA "
    "[--branch NAME] [--target BRANCH] [--touched-file PATH ...] "
    "[--project P] [--session-id S] [--json]"
)

USAGE_BY_FUNCTION_ID = {
    "merge_review.candidate.evaluate": MERGE_REVIEW_CANDIDATE_EVALUATE_USAGE,
}


def merge_review_candidate_evaluate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke merge-review candidate evaluate",
        description=(
            "Report whether one exact candidate head may land, and raise the "
            "review that would clear it. An item whose posture selects "
            "merge_candidate_review may not be merged until an authorized "
            "project owner or operator has approved that head: this reports "
            "satisfied=false and names the decision request to answer with "
            "`yoke decision-requests resolve REQUEST_ID approve`. The "
            "clearance is bound to the commit, so any new commit needs its "
            "own review, and evaluating a newer head withdraws the open "
            "review of the head it replaced. The merge boundary calls this "
            "itself; run it by hand to see where a candidate stands, or to "
            "put the review in a reviewer's Inbox before the merge is tried. "
            "An item that does not select the posture always reports "
            "required=false."
        ),
    )
    parser.add_argument("item", help="Item reference, such as PREFIX-N.")
    parser.add_argument(
        "--commit",
        required=True,
        help="Full 40-character candidate head the landing would carry.",
    )
    parser.add_argument("--branch", default="", help="Branch carrying the candidate.")
    parser.add_argument(
        "--target",
        default="",
        help="Base branch the candidate would land on.",
    )
    parser.add_argument(
        "--touched-file",
        action="append",
        default=None,
        dest="touched_file",
        help="Path the candidate changes; repeat for each path.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project that owns the item reference.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        MERGE_REVIEW_CANDIDATE_EVALUATE_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "commit_sha": parsed.commit,
        "branch": parsed.branch,
        "target": parsed.target,
        "touched_files": list(parsed.touched_file or []),
    }
    return dispatch_and_emit(
        function_id="merge_review.candidate.evaluate",
        target=TargetRef(
            kind="item",
            public_ref=str(parsed.item),
            project_id=parsed.project,
        ),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "MERGE_REVIEW_CANDIDATE_EVALUATE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "merge_review_candidate_evaluate",
]
