"""Operator CLI for actor-bound API tokens."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from yoke_core.domain.api_tokens import (
    DEFAULT_ADMIN_ACTOR_LABEL,
    INITIAL_ADMIN_TOKEN_NAME,
    bootstrap_admin_token,
    mint_token,
    revoke_token,
)
from yoke_core.domain.db_helpers import connect


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


def _emit_token(*, token_id: int, actor_id: int, raw_token: str) -> None:
    print(
        json.dumps(
            {
                "token_id": token_id,
                "actor_id": actor_id,
                "raw_token": raw_token,
            },
            sort_keys=True,
        )
    )


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


def cmd_revoke(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        revoke_token(conn, token_id=args.token_id, actor_id=args.actor)
        print(json.dumps({"revoked_token_id": args.token_id}, sort_keys=True))
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
