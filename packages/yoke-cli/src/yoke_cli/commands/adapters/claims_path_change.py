"""CLI adapters for widening and amending registered path claims."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_cli.commands.adapters.claims_path_narrow_evidence import (
    NarrowEvidenceError,
    collect_narrow_boundary_evidence,
)
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file


CLAIM_PATH_WIDEN_USAGE = (
    "yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... "
    "--reason TEXT --item PREFIX-N [--allow-planned] "
    "[--directory-paths PATH1,PATH2,...] "
    "[(--db-claim-json JSON | --db-claim-file PATH)] "
    "[--session-id S] [--json]"
)
CLAIM_PATH_AMEND_USAGE = (
    "yoke claims path amend --claim-id N "
    "(--add-paths PATH1,PATH2,... | --remove-paths PATH1,PATH2,...) "
    "--reason TEXT --item PREFIX-N [--integration-target BRANCH] "
    "[--allow-planned] [--directory-paths PATH1,PATH2,...] "
    "[(--db-claim-json JSON | --db-claim-file PATH)] "
    "[--session-id S] [--json]"
)


# A deferral keeps only the large file inventory off the write path; the
# lane head the boundary check reads is bound either way, so narrowing stays
# verifiable while the inventory uploads on a later sync.
_BOUNDARY_READY_SYNC_STATES = frozenset({"ok", "deferred"})

AMEND_NARROW_HELP = (
    "Narrowing verifies that the coverage you keep still contains every "
    "committed change on the lane, so it needs the lane's synced head. A "
    "large path snapshot may defer its file inventory to a later sync; that "
    "does not block narrowing. When the sync genuinely fails, the refusal "
    "names the exact `yoke project snapshot sync` command that binds the "
    "lane head, and narrowing succeeds once that command does."
)


def _boundary_sync_refusal(sync_status: Dict[str, Any]) -> str:
    message = sync_status.get("message") or "snapshot sync did not complete"
    repair_command = sync_status.get("repair_command") or ""
    remedy = f"; run `{repair_command}` and retry" if repair_command else ""
    return f"cannot verify narrowing boundary: {message}{remedy}"


def claims_path_widen(args: List[str]) -> int:
    return _claims_path_change(
        args,
        function_id="claims.path.widen",
        prog="yoke claims path widen",
        usage=CLAIM_PATH_WIDEN_USAGE,
    )


def claims_path_amend(args: List[str]) -> int:
    return _claims_path_change(
        args,
        function_id="claims.path.amend",
        prog="yoke claims path amend",
        usage=CLAIM_PATH_AMEND_USAGE,
    )


def _claims_path_change(
    args: List[str], *, function_id: str, prog: str, usage: str
) -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=usage,
        epilog=AMEND_NARROW_HELP if function_id == "claims.path.amend" else None,
    )
    parser.add_argument("--claim-id", required=True, help="path_claims.id to change.")
    if function_id == "claims.path.amend":
        path_group = parser.add_mutually_exclusive_group(required=True)
        path_group.add_argument(
            "--add-paths",
            help="Comma-separated list of repo-relative paths to add.",
        )
        path_group.add_argument(
            "--remove-paths",
            help="Comma-separated declared paths to remove.",
        )
    else:
        parser.add_argument(
            "--add-paths",
            required=True,
            help="Comma-separated list of repo-relative paths to add.",
        )
    parser.add_argument("--reason", required=True, help="Reason for the change.")
    parser.add_argument(
        "--item",
        required=True,
        help="Owning item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--allow-planned",
        action="store_true",
        help="Permit coverage over not-yet-committed paths.",
    )
    parser.add_argument(
        "--directory-paths",
        default=None,
        help="Comma-separated subset of --add-paths that are directory targets.",
    )
    parser.add_argument(
        "--integration-target",
        default=None,
        help="Claim integration branch; required when removing paths.",
    )
    db_claim_group = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        db_claim_group,
        "--db-claim-json",
        "--db-claim-file",
        dest="db_claim_json",
        help_text="Full unified DB-claim amendment as a JSON object.",
        file_help="Read the unified DB-claim amendment from a JSON file.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2

    try:
        claim_id = int(parsed.claim_id)
    except ValueError as exc:
        return usage_error(str(exc))

    removing = getattr(parsed, "remove_paths", None) is not None
    if removing and not parsed.integration_target:
        return usage_error("--integration-target is required with --remove-paths")
    if removing and (parsed.allow_planned or parsed.directory_paths):
        return usage_error(
            "--allow-planned and --directory-paths apply only with --add-paths"
        )
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "reason": parsed.reason,
    }
    if removing:
        remove_paths = split_comma(parsed.remove_paths)
        if not remove_paths:
            return usage_error("--remove-paths must list at least one path")
        payload["remove_paths"] = remove_paths
    else:
        add_paths = split_comma(parsed.add_paths)
        if not add_paths:
            return usage_error("--add-paths must list at least one path")
        payload["add_paths"] = add_paths
        payload["allow_planned"] = bool(parsed.allow_planned)
        if parsed.directory_paths:
            payload["directory_paths"] = split_comma(parsed.directory_paths)
    try:
        db_claim_raw = resolve_text_file(
            parsed.db_claim_json,
            parsed.db_claim_json_file,
            "--db-claim-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    if db_claim_raw is not None:
        if removing:
            return usage_error("DB claim input applies only with --add-paths")
        try:
            db_claim = json.loads(db_claim_raw)
        except json.JSONDecodeError as exc:
            return usage_error(f"DB claim JSON is invalid: {exc}")
        if not isinstance(db_claim, dict):
            return usage_error("DB claim JSON must be an object")
        payload["db_claim"] = db_claim
    if removing:
        try:
            evidence = collect_narrow_boundary_evidence(
                repo_root=None,
                integration_target=parsed.integration_target,
            )
        except NarrowEvidenceError as exc:
            return usage_error(str(exc))
        sync_status = sync_local_snapshot_for_write(
            project=parsed.project,
            repo_root=evidence["repo_root"],
            integration_target=parsed.integration_target,
            session_id=parsed.session_id,
        )
        if sync_status.get("status") not in _BOUNDARY_READY_SYNC_STATES:
            return usage_error(_boundary_sync_refusal(sync_status))
        payload["boundary_evidence"] = evidence
    else:
        sync_local_snapshot_for_write(
            project=parsed.project,
            integration_target=None,
            session_id=parsed.session_id,
        )
    return dispatch_and_emit(
        function_id=function_id,
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "AMEND_NARROW_HELP",
    "CLAIM_PATH_AMEND_USAGE",
    "CLAIM_PATH_WIDEN_USAGE",
    "claims_path_amend",
    "claims_path_widen",
]
