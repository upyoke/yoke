"""Reviewed repair-document adapter; no checkout or lane is required."""

import argparse
import json
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.operator_data_repair import repair_review_digest
from yoke_cli.commands._helpers import (
    add_json_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)


USAGE = "yoke operator data-repair --content-file FILE (--print-digest | --reviewed-sha256 SHA) [--dry-run] [--json]"


def operator_data_repair(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke operator data-repair",
        description=USAGE
        + "\n\nReview the complete JSON repair document before approving its digest. A session holding a live steering seat on the document's project, whose actor is an org administrator, may execute one bounded UPDATE or DELETE with exact before/after snapshots; other callers refuse with steering_seat_required. The command owns its transaction and stores SQL hash, row images and outcome in migration_audit. No work lane is needed. See docs/public/databases/operator-data-repair.md for the document schema and restrictions.",
    )
    parser.add_argument("--content-file", required=True)
    approval = parser.add_mutually_exclusive_group(required=True)
    approval.add_argument(
        "--print-digest",
        action="store_true",
        help="Print the canonical document digest for independent operator review; performs no repair.",
    )
    approval.add_argument(
        "--reviewed-sha256",
        help="Digest of the exact document the operator reviewed and approved.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute all guards and the SQL, then roll back row changes; persist the simulation outcome.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    try:
        plan = json.loads(Path(parsed.content_file).read_text(encoding="utf-8"))
        digest = repair_review_digest(plan)
    except (OSError, ValueError, TypeError):
        return usage_error(
            "repair_document_unreadable: read a valid UTF-8 JSON repair document and retry"
        )
    if parsed.print_digest:
        print(digest)
        return 0
    if digest != parsed.reviewed_sha256:
        return usage_error(
            "repair_review_changed: review the current document and supply its exact digest"
        )
    return dispatch_and_emit(
        function_id="operator.data_repair.run",
        target=TargetRef(kind="global"),
        payload={
            "plan": plan,
            "reviewed_sha256": parsed.reviewed_sha256,
            "dry_run": parsed.dry_run,
        },
        session_id=None,
        json_mode=parsed.json_mode,
    )
