"""``widen`` / ``cancel-amendment`` CLI handlers."""

from __future__ import annotations

import argparse
from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.domain import path_claims_events as _events
from yoke_core.domain.path_claims import PathClaimError, get_claim
from yoke_core.domain.path_claims_amend import (
    AmendmentError,
    AmendmentNotFound,
    NarrowWouldOrphanCommittedWork,
    cancel_amendment,
    widen,
)
from yoke_core.domain.path_claims_amend_stale_base import (
    StaleBaseOnNewClaim,
)
from yoke_core.domain.path_claims_dispatch_io import (
    open_conn,
    parse_paths,
    print_error,
    print_json,
)
from yoke_core.domain.path_claims_dispatch_ownership import deny_if_not_owner
from yoke_core.domain.path_claims_read import claim_projection
from yoke_core.domain.path_claims_resolve import (
    PathResolveError,
    resolve_paths_to_target_ids,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _amend_payload_for(kind: str, target_ids) -> dict:
    if kind == "widen":
        return {"added": list(target_ids)}
    return {"target_ids": list(target_ids)}


def _emit_amendment_blocked(
    *, conn, claim_id: int, kind: str, exc: Exception, project: Optional[int],
) -> None:
    offending = (
        list(exc.offending_target_ids)
        if isinstance(exc, NarrowWouldOrphanCommittedWork)
        else []
    )
    _events.emit_amendment_blocked(
        conn=conn,
        claim_id=claim_id,
        amendment_kind=kind,
        reason=str(exc),
        offending_target_ids=offending,
        item_id=None,
        project=project,
    )


def _project_for_claim_id(conn, claim_id: int) -> Optional[int]:
    p = _p(conn)
    row = conn.execute(
        "SELECT i.project_id FROM path_claims pc "
        "JOIN items i ON pc.item_id = i.id "
        f"WHERE pc.id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]) if row[0] else None


DEFAULT_WIDEN_REASON = "coverage-widen"


def _resolve_item_to_claim_id(conn, item_arg: str) -> tuple[Optional[int], Optional[str]]:
    """Resolve ``--item YOK-N`` → one non-terminal exclusive claim id.

    Returns ``(claim_id, None)`` on success; ``(None, message)`` on
    zero/multiple matches. Matches exclusive claims in planned /
    blocked / active states.
    """
    from yoke_core.domain.path_claims_dispatch_io import parse_item_id
    try:
        item_id = parse_item_id(item_arg)
    except ValueError as exc:
        return None, str(exc)
    p = _p(conn)
    rows = conn.execute(
        f"SELECT id FROM path_claims WHERE item_id = {p} AND mode = 'exclusive' "
        "AND state IN ('planned', 'blocked', 'active') ORDER BY id ASC",
        (item_id,),
    ).fetchall()
    if not rows:
        return None, (
            f"--item YOK-{item_id}: no non-terminal exclusive claim "
            "(planned/blocked/active). Pass the positional claim id."
        )
    if len(rows) > 1:
        ids = ", ".join(str(r[0]) for r in rows)
        return None, (
            f"--item YOK-{item_id}: {len(rows)} non-terminal exclusive "
            f"claims match ({ids}). Pass the positional claim id."
        )
    return int(rows[0][0]), None


def cmd_widen(argv: Sequence[str]) -> int:
    """Widen a path claim. Identify by positional id or ``--item YOK-N``."""
    from yoke_core.domain.path_claims_dispatch_help import WIDEN_DESCRIPTION
    parser = argparse.ArgumentParser(prog="path-claims widen", add_help=True,
        description=WIDEN_DESCRIPTION, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "claim_id", type=int, nargs="?", default=None,
        help="Claim id. Optional when --item is supplied.",
    )
    parser.add_argument(
        "--item", default=None,
        help=(
            "Resolve claim id from a YOK-N item; matches the one "
            "non-terminal exclusive claim. Mutually exclusive with claim_id."
        ),
    )
    parser.add_argument(
        "--paths", "--add", required=True,
        help=(
            "Comma-separated project-relative POSIX paths to add. "
            "``--add`` is accepted as a back-compat alias for cross-CLI "
            "naming parity; the canonical flag is ``--paths``."
        ),
    )
    reason_group = parser.add_mutually_exclusive_group()
    add_text_file_pair(reason_group, "--reason", "--reason-file", dest="reason")
    parser.add_argument(
        "--allow-planned", action="store_true", default=False,
        help=(
            "Mint planned path_targets rows for paths not yet in the "
            "registry (matches register's --allow-planned). Without "
            "this flag, unknown paths are rejected by the strict "
            "resolver."
        ),
    )
    parser.add_argument(
        "--directory-paths", default="",
        help=(
            "Comma-separated subset of --paths to mark as directory "
            "kind (only meaningful with --allow-planned)."
        ),
    )
    parser.add_argument(
        "--repo-path", default=None,
        help="Working tree path; enables the stale-base-on-new-claim check.",
    )
    parser.add_argument(
        "--worktree-head", default=None,
        help="Override SHA for the working-branch reconciliation check.",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print_error("USAGE", "see --help for path-claims widen")
        return 2
    if (args.claim_id is None) == (args.item is None):
        print_error("USAGE", "specify exactly one of: claim_id OR --item YOK-N")
        return 2
    paths = parse_paths(args.paths)
    if not paths:
        print_error("USAGE", "--paths must list at least one path")
        return 2
    try:
        reason = resolve_text_file(args.reason, args.reason_file, "--reason-file")
    except ValueError as exc:
        print_error("USAGE", str(exc))
        return 2
    if reason is None or not reason.strip():
        reason = DEFAULT_WIDEN_REASON
    directory_paths = parse_paths(args.directory_paths)
    conn = open_conn()
    try:
        if args.item is not None:
            resolved, err = _resolve_item_to_claim_id(conn, args.item)
            if err is not None:
                print_error("USAGE", err)
                return 2
            args.claim_id = resolved
        if deny_if_not_owner(conn, action="widen", claim_id=args.claim_id):
            return 1
        project = _project_for_claim_id(conn, args.claim_id)
        if not project:
            print_error(
                "VALIDATION",
                f"claim {args.claim_id} has no item project; cannot resolve paths",
                claim_id=args.claim_id,
            )
            return 1
        try:
            if args.allow_planned:
                from yoke_core.domain.path_claims_resolve import (
                    resolve_or_plan_paths_to_target_ids,
                )
                p = _p(conn)
                item_id_for_attr = conn.execute(
                    f"SELECT item_id FROM path_claims WHERE id = {p}",
                    (args.claim_id,),
                ).fetchone()
                target_ids = resolve_or_plan_paths_to_target_ids(
                    conn,
                    project,
                    paths,
                    item_id=(
                        int(item_id_for_attr[0])
                        if item_id_for_attr and item_id_for_attr[0] is not None
                        else None
                    ),
                    claim_id=args.claim_id,
                    directory_paths=directory_paths or None,
                )
            else:
                target_ids = resolve_paths_to_target_ids(
                    conn, project, paths,
                )
            amendment_id = widen(
                conn,
                claim_id=args.claim_id,
                add_target_ids=target_ids,
                reason=reason,
                repo_path=args.repo_path,
                worktree_head=args.worktree_head,
            )
            projection = claim_projection(conn, args.claim_id)
            _events.emit_amended(
                conn=conn,
                claim=projection,
                amendment_id=amendment_id,
                amendment_kind="widen",
                payload=_amend_payload_for("widen", target_ids),
                reason=reason,
                project=project,
            )
        except StaleBaseOnNewClaim as exc:
            _emit_amendment_blocked(
                conn=conn, claim_id=args.claim_id,
                kind="widen", exc=exc, project=project,
            )
            print_error(
                "STALE_BASE_ON_NEW_CLAIM", str(exc),
                claim_id=args.claim_id,
                offending_paths=exc.offending_paths,
                offending_target_ids=exc.offending_target_ids,
                base_commit_sha=exc.base_commit_sha,
                integration_target_head_sha=exc.integration_target_head_sha,
                integration_target=exc.integration_target,
            )
            return 1
        except (AmendmentError, PathClaimError, PathResolveError) as exc:
            _emit_amendment_blocked(
                conn=conn, claim_id=args.claim_id,
                kind="widen", exc=exc, project=project,
            )
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    print_json(
        {"success": True, "amendment_id": amendment_id, "claim": projection}
    )
    return 0


def cmd_cancel_amendment(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="path-claims cancel-amendment", add_help=False
    )
    parser.add_argument("claim_id", type=int)
    parser.add_argument("--amendment-id", type=int, required=True)
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(reason_group, "--reason", "--reason-file", dest="reason")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        print_error("USAGE", "see --help for path-claims cancel-amendment")
        return 2
    try:
        reason = resolve_text_file(args.reason, args.reason_file, "--reason-file")
    except ValueError as exc:
        print_error("USAGE", str(exc))
        return 2
    conn = open_conn()
    try:
        if deny_if_not_owner(conn, action="cancel-amendment", claim_id=args.claim_id):
            return 1
        try:
            new_amendment_id = cancel_amendment(
                conn,
                claim_id=args.claim_id,
                amendment_id=args.amendment_id,
                reason=reason,
            )
            projection = claim_projection(conn, args.claim_id)
            _events.emit_amended(
                conn=conn,
                claim=projection,
                amendment_id=new_amendment_id,
                amendment_kind="cancel",
                payload={"cancelled_amendment_id": args.amendment_id},
                reason=reason,
                project=_project_for_claim_id(conn, args.claim_id),
            )
        except AmendmentNotFound as exc:
            print_error(
                "NOT_FOUND", str(exc),
                claim_id=args.claim_id, amendment_id=args.amendment_id,
            )
            return 1
        except (AmendmentError, PathClaimError) as exc:
            _emit_amendment_blocked(
                conn=conn, claim_id=args.claim_id,
                kind="cancel", exc=exc,
                project=_project_for_claim_id(conn, args.claim_id),
            )
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    print_json(
        {
            "success": True,
            "amendment_id": new_amendment_id,
            "claim": projection,
        }
    )
    return 0


__all__ = ["DEFAULT_WIDEN_REASON", "cmd_cancel_amendment", "cmd_widen"]
