"""``path-claims`` subcommand dispatcher for ``db_router``.

Operators run subcommands (``register``, ``activate``, ``get``,
``list``, ``boundary``, the amend verbs, ``release``, ``cancel``,
``override``). Each resolves the canonical DB through shared IO
helpers, delegates to the matching domain module, and emits JSON on
stdout. Large amend handlers live in sibling modules to keep this
dispatcher within the line budget.
"""

from __future__ import annotations
import argparse
import sys
from typing import Optional, Sequence

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.domain.path_claims import PathClaimError
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckError,
    boundary_check_for_claim,
)
from yoke_core.domain.path_claims_dispatch_amend import (
    cmd_cancel_amendment,
    cmd_widen,
)
from yoke_core.domain.path_claims_dispatch_narrow import cmd_narrow
from yoke_core.domain.path_claims_dispatch_override import cmd_override
from yoke_core.domain.path_claims_dispatch_ownership import deny_if_not_owner
from yoke_core.domain.path_claims_dispatch_io import (
    open_conn as _open_conn,
    parse_item_id as _parse_item_id,
    parse_paths as _parse_paths,
    print_error as _print_error,
    print_json as _print_json,
    split_states as _split_states,
)
from yoke_core.domain.path_claims_dispatch_state import (
    cmd_activate,
    cmd_cancel,
    cmd_release,
)
from yoke_core.domain.path_claims_read import (
    claim_projection,
    cross_claim_conflicts,
    item_view,
)
from yoke_core.domain.path_claims_register import (
    PathClaimRegistrationError,
    register_for_item,
)
from yoke_core.domain.path_claims_resolve import PathResolveError


def cmd_register(argv: Sequence[str]) -> int:
    from yoke_core.domain.path_claims_dispatch_help import REGISTER_DESCRIPTION
    parser = argparse.ArgumentParser(prog="path-claims register", add_help=True,
        description=REGISTER_DESCRIPTION, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--item", required=True)
    parser.add_argument("--integration-target", default=None)
    parser.add_argument(
        "--paths", default="",
        help="Comma-separated POSIX paths. Required for --mode exclusive.",
    )
    parser.add_argument(
        "--directory-paths", default="",
        help="Subset of --paths to mark as directory kind (with --allow-planned).",
    )
    parser.add_argument(
        "--tentative-paths", default="",
        help="Subset of --paths to mint as tentative.",
    )
    parser.add_argument(
        "--mode", choices=("exclusive", "exception"), default="exclusive",
    )
    reason_group = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        reason_group, "--reason", "--reason-file", dest="reason",
        help_text="Required for --mode exception: operator no-claim justification.",
    )
    parser.add_argument(
        "--allow-planned", action="store_true", default=False,
        help="Mint planned path_targets rows for unknown paths.",
    )
    parser.add_argument("--upstream-claim-id", type=int, default=None)
    parser.add_argument("--actor-id", type=int, default=None)
    parser.add_argument("--session-id", default=None)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        # --help raises SystemExit(0) after usage to stdout.
        if exc.code == 0:
            return 0
        _print_error("USAGE", "see --help for path-claims register")
        return 2
    try:
        item_id = _parse_item_id(args.item)
    except ValueError as exc:
        _print_error("USAGE", str(exc))
        return 2
    paths = _parse_paths(args.paths)
    directory_paths = _parse_paths(args.directory_paths)
    tentative_paths = _parse_paths(args.tentative_paths)
    if args.mode == "exclusive" and not paths:
        _print_error("USAGE", "--paths must list at least one path for --mode exclusive")
        return 2
    if tentative_paths and not args.allow_planned:
        _print_error("USAGE", "--tentative-paths requires --allow-planned")
        return 2
    if not set(tentative_paths).issubset(set(paths)):
        _print_error("USAGE", "--tentative-paths must be a subset of --paths")
        return 2
    try:
        reason = resolve_text_file(args.reason, args.reason_file, "--reason-file")
    except ValueError as exc:
        _print_error("USAGE", str(exc))
        return 2
    if args.mode == "exception":
        if paths:
            _print_error(
                "USAGE",
                "--paths must be empty for --mode exception",
            )
            return 2
        if not (reason or "").strip():
            _print_error(
                "USAGE",
                "--reason is required for --mode exception",
            )
            return 2
    conn = _open_conn()
    try:
        if deny_if_not_owner(conn, action="register", item_id=item_id):
            return 1
        from yoke_core.domain.path_claims_register_validate_integration_target import resolve_and_validate_integration_target as _vit  # noqa: E501
        try:
            args.integration_target = _vit(conn, item_id=item_id, supplied_target=args.integration_target)
        except PathClaimRegistrationError as exc:
            _print_error("VALIDATION", str(exc))
            return 1
        # Derive a serial upstream from item_dependencies before
        # register's overlap classifier would reject.
        from yoke_core.domain.path_claims_dependency_resolver import (
            auto_resolve_upstream,
            cross_check_explicit_upstream,
        )
        derived_upstream_id = args.upstream_claim_id
        if derived_upstream_id is None and args.mode == "exclusive" and paths:
            derived_upstream_id = auto_resolve_upstream(
                conn, item_id=item_id,
                integration_target=args.integration_target, paths=paths,
                directory_paths=directory_paths or None,
                allow_planned=args.allow_planned,
                tentative_paths=tentative_paths or None,
            )
        elif derived_upstream_id is not None and args.mode == "exclusive":
            advisory = cross_check_explicit_upstream(
                conn, item_id=item_id, upstream_claim_id=derived_upstream_id,
            )
            if advisory:
                print(advisory, file=sys.stderr)
        try:
            claim_id = register_for_item(
                conn,
                item_id=item_id,
                integration_target=args.integration_target,
                paths=paths,
                upstream_claim_id=derived_upstream_id,
                actor_id=args.actor_id,
                session_id=args.session_id,
                mode=args.mode,
                exception_reason=reason,
                allow_planned=args.allow_planned,
                directory_paths=directory_paths or None,
                tentative_paths=tentative_paths or None,
            )
        except (PathClaimRegistrationError, PathResolveError) as exc:
            _print_error("VALIDATION", str(exc))
            return 1
        except PathClaimError as exc:
            # Overlap rejection -> dedicated denial composer.
            from yoke_core.domain.path_claim_register import (
                render_overlap_denial_for_register,
            )
            body = render_overlap_denial_for_register(
                conn, exc=exc, item_id=item_id,
                integration_target=args.integration_target, paths=paths,
                allow_planned=args.allow_planned, session_id=args.session_id,
            )
            _print_error("VALIDATION", body if body is not None else str(exc))
            return 1
        projection = claim_projection(conn, claim_id)
    finally:
        conn.close()
    _print_json({"success": True, "claim": projection})
    return 0


def cmd_get(argv: Sequence[str]) -> int:
    """Print the JSON projection for a single path claim by its id."""
    parser = argparse.ArgumentParser(prog="path-claims get", add_help=True)
    parser.add_argument(
        "claim_id", type=int,
        help="Path-claim id (integer) to read. Same shape as service_client.",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        _print_error("USAGE", "see --help for path-claims get")
        return 2
    conn = _open_conn()
    try:
        try:
            projection = claim_projection(conn, args.claim_id)
        except PathClaimError as exc:
            _print_error("NOT_FOUND", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    _print_json(projection)
    return 0


def cmd_list(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="path-claims list", add_help=False)
    parser.add_argument("--item", required=True)
    parser.add_argument(
        "--state", action="append", default=None,
        help="Filter by state; repeatable and/or comma-separated. Default: all states.",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        _print_error("USAGE", "see --help for path-claims list")
        return 2
    try:
        item_id = _parse_item_id(args.item)
    except ValueError as exc:
        _print_error("USAGE", str(exc))
        return 2
    conn = _open_conn()
    try:
        claims = item_view(conn, item_id, states=_split_states(args.state))
    finally:
        conn.close()
    _print_json(claims)
    return 0


def cmd_boundary(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="path-claims boundary", add_help=True)
    parser.add_argument("claim_id", type=int)
    parser.add_argument(
        "--repo-path", required=True,
        help="Worktree (or working tree) where the claim's branch lives.",
    )
    parser.add_argument(
        "--worktree-head", default=None,
        help="Override the worktree HEAD SHA (defaults to git rev-parse HEAD).",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        # --help raises SystemExit(0) after usage to stdout.
        if exc.code == 0:
            return 0
        _print_error("USAGE", "see --help for path-claims boundary")
        return 2
    conn = _open_conn()
    try:
        try:
            result = boundary_check_for_claim(
                conn,
                claim_id=args.claim_id,
                repo_path=args.repo_path,
                worktree_head=args.worktree_head,
            )
        except PathClaimError as exc:
            _print_error("NOT_FOUND", str(exc), claim_id=args.claim_id)
            return 1
        except BoundaryCheckError as exc:
            _print_error("BOUNDARY_IO", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    _print_json(result.to_dict())
    return 0


def cmd_conflicts(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="path-claims conflicts", add_help=False)
    parser.add_argument("--integration-target", default=None)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        _print_error("USAGE", "see --help for path-claims conflicts")
        return 2
    conn = _open_conn()
    try:
        conflicts = cross_claim_conflicts(
            conn, integration_target=args.integration_target
        )
    finally:
        conn.close()
    _print_json(conflicts)
    return 0


_SUBCOMMANDS = {
    "register": cmd_register,
    "activate": cmd_activate,
    "get": cmd_get,
    "list": cmd_list,
    "conflicts": cmd_conflicts,
    "boundary": cmd_boundary,
    "widen": cmd_widen,
    "narrow": cmd_narrow,
    "cancel-amendment": cmd_cancel_amendment,
    "release": cmd_release,
    "cancel": cmd_cancel,
    "override": cmd_override,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help", "help"):
        print("Usage: path-claims <subcommand> [args...]")
        print(f"Subcommands: {', '.join(sorted(_SUBCOMMANDS))}")
        return 0
    sub = args[0]
    handler = _SUBCOMMANDS.get(sub)
    if handler is None:
        _print_error("USAGE", f"unknown subcommand {sub!r}")
        return 2
    return handler(args[1:])


__all__ = [
    "cmd_activate", "cmd_boundary", "cmd_cancel", "cmd_cancel_amendment",
    "cmd_conflicts", "cmd_get", "cmd_list", "cmd_narrow", "cmd_register",
    "cmd_release", "cmd_widen", "main",
]


if __name__ == "__main__":  # pragma: no cover - module-mode entry
    raise SystemExit(main())
