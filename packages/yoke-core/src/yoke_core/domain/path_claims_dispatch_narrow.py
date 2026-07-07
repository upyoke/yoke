"""Narrow CLI handler for ``path-claims narrow``.

Splits out of :mod:`yoke_core.domain.path_claims_dispatch_amend` so
the narrow surface can carry the explicit ``--drop-paths`` /
``--keep-paths`` flag pair without crowding the widen/cancel-amendment
handlers.

The flag pair is mutually exclusive at parse time. ``--keep-paths``
reads the claim's current ``declared_paths`` via
:func:`yoke_core.domain.path_claims_read.claim_projection` and
translates the keep set into the drop set the domain function
:func:`yoke_core.domain.path_claims_amend.narrow` already takes.

The legacy bare ``--paths`` form is rejected with a usage error that
names the two replacements; no deprecated alias is retained because
the migration runs in the same slice that introduces the new flags.
"""

from __future__ import annotations

import argparse
from typing import Sequence

from yoke_core.domain import path_claims_events as _events
from yoke_core.domain.path_claims import PathClaimError
from yoke_core.domain.path_claims_amend import (
    AmendmentError,
    NarrowWouldOrphanCommittedWork,
    narrow,
)
from yoke_core.domain.path_claims_dispatch_amend import (
    _emit_amendment_blocked,
    _project_for_claim_id,
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


_BARE_PATHS_ERROR = (
    "--paths is not accepted by `path-claims narrow`. "
    "Use --drop-paths to remove paths from the claim, or "
    "--keep-paths to keep specific paths (all others are removed)."
)


def _has_flag(argv: Sequence[str], name: str) -> bool:
    prefix = name + "="
    for tok in argv:
        if tok == name or tok.startswith(prefix):
            return True
    return False


class _UsageError(Exception):
    def __init__(self, message: str, **context) -> None:
        super().__init__(message)
        self.message = message
        self.context = context


def cmd_narrow(argv: Sequence[str]) -> int:
    argv_list = list(argv)
    # Pre-argparse rejections so error messages name both replacements.
    if _has_flag(argv_list, "--paths"):
        print_error("USAGE", _BARE_PATHS_ERROR)
        return 2
    if _has_flag(argv_list, "--drop-paths") and _has_flag(argv_list, "--keep-paths"):
        print_error(
            "USAGE",
            "--drop-paths and --keep-paths are mutually exclusive; pass exactly one.",
        )
        return 2

    parser = argparse.ArgumentParser(prog="path-claims narrow", add_help=True)
    parser.add_argument("claim_id", type=int)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--drop-paths",
        default=None,
        help=(
            "Comma-separated project-relative POSIX paths to remove "
            "from the claim's coverage."
        ),
    )
    group.add_argument(
        "--keep-paths",
        default=None,
        help=(
            "Comma-separated project-relative POSIX paths to keep on "
            "the claim. All other paths currently on the claim are removed."
        ),
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--repo-path",
        required=True,
        help="Worktree where the claim's branch lives (for the boundary check).",
    )
    parser.add_argument("--worktree-head", default=None)
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print_error(
            "USAGE",
            "see --help for path-claims narrow (--drop-paths or --keep-paths required)",
        )
        return 2

    if args.drop_paths is None and args.keep_paths is None:
        print_error(
            "USAGE",
            "specify --drop-paths to remove paths or --keep-paths to keep specific paths.",
        )
        return 2

    conn = open_conn()
    try:
        if deny_if_not_owner(conn, action="narrow", claim_id=args.claim_id):
            return 1
        project = _project_for_claim_id(conn, args.claim_id)
        if not project:
            print_error(
                "VALIDATION",
                f"claim {args.claim_id} has no item project",
                claim_id=args.claim_id,
            )
            return 1

        try:
            drop_paths = _resolve_drop_paths(conn, args)
        except _UsageError as exc:
            print_error("USAGE", exc.message, **exc.context)
            return 2
        except PathClaimError as exc:
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1

        try:
            target_ids = resolve_paths_to_target_ids(conn, project, drop_paths)
            amendment_id = narrow(
                conn,
                claim_id=args.claim_id,
                drop_target_ids=target_ids,
                reason=args.reason,
                repo_path=args.repo_path,
                worktree_head=args.worktree_head,
            )
            projection = claim_projection(conn, args.claim_id)
            _events.emit_amended(
                conn=conn,
                claim=projection,
                amendment_id=amendment_id,
                amendment_kind="narrow",
                payload={"removed": list(target_ids)},
                reason=args.reason,
                project=project,
            )
        except NarrowWouldOrphanCommittedWork as exc:
            _emit_amendment_blocked(
                conn=conn, claim_id=args.claim_id,
                kind="narrow", exc=exc, project=project,
            )
            print_error(
                "VALIDATION", str(exc),
                claim_id=args.claim_id,
                offending_paths=exc.offending_paths,
                offending_target_ids=exc.offending_target_ids,
            )
            return 1
        except (AmendmentError, PathClaimError, PathResolveError) as exc:
            _emit_amendment_blocked(
                conn=conn, claim_id=args.claim_id,
                kind="narrow", exc=exc, project=project,
            )
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    print_json(
        {"success": True, "amendment_id": amendment_id, "claim": projection}
    )
    return 0


def _resolve_drop_paths(conn, args) -> list:
    """Translate the explicit flag pair into the domain's drop_paths list."""
    if args.drop_paths is not None:
        paths = parse_paths(args.drop_paths)
        if not paths:
            raise _UsageError("--drop-paths must list at least one path")
        return paths
    keep_paths = parse_paths(args.keep_paths)
    if not keep_paths:
        raise _UsageError(
            "--keep-paths must list at least one path "
            "(use `path-claims release` or `path-claims cancel` "
            "to remove the entire claim)"
        )
    projection = claim_projection(conn, args.claim_id)
    declared_set = set(projection.get("declared_paths") or [])
    keep_set = set(keep_paths)
    unknown = sorted(keep_set - declared_set)
    if unknown:
        raise _UsageError(
            "--keep-paths includes path(s) not currently on claim "
            f"{args.claim_id}: {', '.join(unknown)}. "
            "Use `path-claims widen` first to add new paths.",
            offending_paths=unknown,
            claim_id=args.claim_id,
        )
    return sorted(declared_set - keep_set)


__all__ = ["cmd_narrow"]
