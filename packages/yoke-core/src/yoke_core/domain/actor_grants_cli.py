"""Operator CLI for actor role grants (org scope + project scope).

Sanctioned surface for granting/listing the auth grants that back
``permission_decision`` — org roles via ``actor_org_roles`` and project roles
via ``actor_project_roles``. Mirrors the ``projects`` operator-CLI pattern;
the canonical agent shape wraps these as ``yoke`` subcommands.

  python3 -m yoke_core.domain.actor_grants_cli grant-org \
      --actor 2 --org default --role admin
  python3 -m yoke_core.domain.actor_grants_cli grant-project \
      --actor 2 --project yoke --role owner
  python3 -m yoke_core.domain.actor_grants_cli list --actor 2
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, List, Optional

from yoke_core.domain.actor_permissions import (
    ORG_ROLES,
    PROJECT_ROLES,
    grant_actor_org_role,
    grant_actor_project_role,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.org_schema import org_id_by_slug
from yoke_core.domain.project_identity import resolve_project_id


def _resolve_org_id(conn: Any, token: str) -> int:
    token = token.strip()
    if token.isdigit():
        row = conn.execute(
            "SELECT id FROM organizations WHERE id = %s"
            if _is_pg(conn)
            else "SELECT id FROM organizations WHERE id = ?",
            (int(token),),
        ).fetchone()
        if row is None:
            raise LookupError(f"organization id {token} not found")
        return int(row[0])
    org_id = org_id_by_slug(conn, token)
    if org_id is None:
        raise LookupError(f"organization {token!r} not found")
    return org_id


def _is_pg(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return db_backend.connection_is_postgres(conn)


def _assert_actor_exists(conn: Any, actor_id: int) -> None:
    ph = "%s" if _is_pg(conn) else "?"
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {ph}", (actor_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"actor id {actor_id} not found")


def cmd_grant_org(args: argparse.Namespace) -> int:
    if args.role not in ORG_ROLES:
        print(
            f"Error: {args.role!r} is not an org role. Valid: {', '.join(ORG_ROLES)}",
            file=sys.stderr,
        )
        return 2
    conn = connect()
    try:
        _assert_actor_exists(conn, args.actor)
        org_id = _resolve_org_id(conn, args.org)
        grant_actor_org_role(
            conn,
            actor_id=args.actor,
            org_id=org_id,
            role_name=args.role,
            granted_by_actor_id=args.granted_by,
        )
        print(f"Granted org role {args.role} to actor {args.actor} on org {org_id}")
        return 0
    finally:
        conn.close()


def cmd_grant_project(args: argparse.Namespace) -> int:
    if args.role not in PROJECT_ROLES:
        print(
            f"Error: {args.role!r} is not a project role. "
            f"Valid: {', '.join(PROJECT_ROLES)}",
            file=sys.stderr,
        )
        return 2
    conn = connect()
    try:
        _assert_actor_exists(conn, args.actor)
        project_id = resolve_project_id(conn, args.project)
        grant_actor_project_role(
            conn,
            actor_id=args.actor,
            project_id=project_id,
            role_name=args.role,
            granted_by_actor_id=args.granted_by,
        )
        print(
            f"Granted project role {args.role} to actor {args.actor} "
            f"on project {project_id}"
        )
        return 0
    finally:
        conn.close()


def cmd_list(args: argparse.Namespace) -> int:
    conn = connect()
    try:
        ph = "%s" if _is_pg(conn) else "?"
        org_rows = conn.execute(
            "SELECT o.slug, r.name FROM actor_org_roles aor "
            "JOIN organizations o ON o.id = aor.org_id "
            "JOIN roles r ON r.id = aor.role_id "
            f"WHERE aor.actor_id = {ph} ORDER BY o.slug, r.name",
            (args.actor,),
        ).fetchall()
        proj_rows = conn.execute(
            "SELECT p.slug, r.name FROM actor_project_roles apr "
            "JOIN projects p ON p.id = apr.project_id "
            "JOIN roles r ON r.id = apr.role_id "
            f"WHERE apr.actor_id = {ph} ORDER BY p.slug, r.name",
            (args.actor,),
        ).fetchall()
        print(f"actor {args.actor} grants:")
        for slug, role in org_rows:
            print(f"  org/{slug}: {role}")
        for slug, role in proj_rows:
            print(f"  project/{slug}: {role}")
        if not org_rows and not proj_rows:
            print("  (none)")
        return 0
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="actor_grants_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    g_org = sub.add_parser("grant-org", help="Grant an org role to an actor")
    g_org.add_argument("--actor", type=int, required=True)
    g_org.add_argument("--org", required=True, help="org slug or id")
    g_org.add_argument("--role", required=True, help=f"one of: {', '.join(ORG_ROLES)}")
    g_org.add_argument("--granted-by", dest="granted_by", type=int, default=None)
    g_org.set_defaults(func=cmd_grant_org)

    g_proj = sub.add_parser("grant-project", help="Grant a project role to an actor")
    g_proj.add_argument("--actor", type=int, required=True)
    g_proj.add_argument("--project", required=True, help="project slug or id")
    g_proj.add_argument(
        "--role", required=True, help=f"one of: {', '.join(PROJECT_ROLES)}"
    )
    g_proj.add_argument("--granted-by", dest="granted_by", type=int, default=None)
    g_proj.set_defaults(func=cmd_grant_project)

    g_list = sub.add_parser("list", help="List an actor's grants")
    g_list.add_argument("--actor", type=int, required=True)
    g_list.set_defaults(func=cmd_list)

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
