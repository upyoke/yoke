"""Operator CLI for actor-bound API tokens."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import json_helper
from yoke_core.domain.actor_permissions import PROJECT_ROLES
from yoke_core.domain.api_tokens import (
    DEFAULT_ADMIN_ACTOR_LABEL,
    INITIAL_ADMIN_TOKEN_NAME,
    bootstrap_admin_token,
    bootstrap_project_service_token,
    mint_token,
    revoke_token,
)
from yoke_core.domain.db_helpers import connect


class _RawTokenFileWriteError(ValueError):
    """A protected token-file write failed before or after atomic replace."""

    def __init__(self, message: str, *, replacement_committed: bool) -> None:
        super().__init__(message)
        self.replacement_committed = replacement_committed


def _is_pg(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return db_backend.connection_is_postgres(conn)


def _assert_actor_exists(conn: Any, actor_id: int) -> None:
    ph = "%s" if _is_pg(conn) else "?"
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {ph}",
        (actor_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"actor id {actor_id} not found")


def _emit_token(
    *,
    token_id: int,
    actor_id: int,
    raw_token: str | None,
) -> None:
    payload = {"actor_id": actor_id, "token_id": token_id}
    if raw_token is not None:
        payload["raw_token"] = raw_token
    print(json_helper.dumps_compact(payload))


def _validated_raw_token_path(raw_path: str) -> Path:
    target = Path(raw_path).expanduser()
    if not target.parent.is_dir():
        raise ValueError(f"raw token file parent does not exist: {target.parent}")
    if target.is_symlink():
        raise ValueError(f"raw token file must not be a symlink: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"raw token file must be a regular file: {target}")
    return target


def _write_raw_token_file(target: Path, raw_token: str) -> None:
    descriptor = -1
    temporary: Path | None = None
    replacement_committed = False
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(raw_token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        replacement_committed = True
        temporary = None
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        if replacement_committed:
            message = (
                f"raw token file was replaced at {target}, but directory "
                "durability sync failed; the token remains active in that "
                f"file: {exc}"
            )
        else:
            message = f"could not write raw token file {target}: {exc}"
        raise _RawTokenFileWriteError(
            message,
            replacement_committed=replacement_committed,
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def cmd_bootstrap_admin(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        created = bootstrap_admin_token(
            conn,
            actor_label=args.actor_label,
            project=args.project,
            token_name=args.name,
        )
        _emit_token(
            token_id=created.token_id,
            actor_id=created.actor_id,
            raw_token=created.raw_token,
        )
        return 0
    finally:
        conn.close()


def cmd_mint(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        _assert_actor_exists(conn, args.actor)
        created = mint_token(
            conn,
            actor_id=args.actor,
            name=args.name,
            expires_at=args.expires_at,
        )
        _emit_token(
            token_id=created.token_id,
            actor_id=created.actor_id,
            raw_token=created.raw_token,
        )
        return 0
    finally:
        conn.close()


def cmd_bootstrap_project_service(args: argparse.Namespace) -> int:
    token_path = (
        _validated_raw_token_path(args.raw_token_file)
        if args.raw_token_file is not None
        else None
    )
    conn = connect()
    try:
        created = bootstrap_project_service_token(
            conn,
            system_component=args.system_component,
            project=args.project,
            role_name=args.role,
            token_name=args.name,
        )
        if token_path is not None:
            try:
                _write_raw_token_file(token_path, created.raw_token)
            except ValueError as exc:
                replacement_committed = (
                    isinstance(exc, _RawTokenFileWriteError)
                    and exc.replacement_committed
                )
                if not replacement_committed:
                    revoke_token(
                        conn,
                        token_id=created.token_id,
                        actor_id=created.actor_id,
                    )
                raise
        _emit_token(
            token_id=created.token_id,
            actor_id=created.actor_id,
            raw_token=None if token_path is not None else created.raw_token,
        )
        return 0
    finally:
        conn.close()


def cmd_revoke(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        revoke_token(conn, token_id=args.token_id, actor_id=args.actor)
        print(json_helper.dumps_compact({"revoked_token_id": args.token_id}))
        return 0
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="api_tokens_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser(
        "bootstrap-admin",
        help="Create/resolve the initial admin actor, grant authority, and mint a token",
    )
    bootstrap.add_argument("--actor-label", default=DEFAULT_ADMIN_ACTOR_LABEL)
    bootstrap.add_argument(
        "--project",
        default=None,
        help="Project slug for a project-owner grant; omit for the org-admin grant.",
    )
    bootstrap.add_argument("--name", default=INITIAL_ADMIN_TOKEN_NAME)
    bootstrap.set_defaults(func=cmd_bootstrap_admin)

    mint = sub.add_parser("mint", help="Mint a token for an existing actor")
    mint.add_argument("--actor", type=int, required=True)
    mint.add_argument("--name", required=True)
    mint.add_argument("--expires-at", default=None)
    mint.set_defaults(func=cmd_mint)

    service_help = (
        "Idempotently ensure a project service actor/role and mint a fresh "
        "token; every invocation creates another active token."
    )
    service = sub.add_parser(
        "bootstrap-project-service",
        help=service_help,
        description=service_help,
    )
    service.add_argument("--system-component", required=True)
    service.add_argument("--project", required=True)
    service.add_argument(
        "--role",
        required=True,
        help=f"Project-scoped role: {', '.join(PROJECT_ROLES)}.",
    )
    service.add_argument("--name", required=True)
    service.add_argument(
        "--raw-token-file",
        default=None,
        help=(
            "Atomically create/replace this 0600 file and omit the raw token "
            "from stdout."
        ),
    )
    service.set_defaults(func=cmd_bootstrap_project_service)

    revoke = sub.add_parser("revoke", help="Revoke a token by id")
    revoke.add_argument("--token-id", type=int, required=True)
    revoke.add_argument("--actor", type=int, default=None)
    revoke.set_defaults(func=cmd_revoke)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
