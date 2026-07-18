"""Project-level deployment-flow default accessor.

The ``deploy_defaults`` Project Structure family stores at most one default
``deployment_flows.id`` per project. Absence of the entry is a valid state
meaning "no project default" — callers decide whether to infer, ask, or
leave the item's flow blank.

This module is the Python accessor plus operator write surface for domains
that need the project default without speaking Project Structure's op list
vocabulary. It does not cache; every read hits the aggregate.

CLI usage::

    python3 -m yoke_core.domain.deploy_defaults set <project-id> <flow-id>
    python3 -m yoke_core.domain.deploy_defaults clear <project-id>

Agent-facing reads use ``yoke project-structure deploy-defaults get``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, List, Optional

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain import project_structure as ps
from yoke_core.domain.project_identity import resolve_project_id


FAMILY = "deploy_defaults"


def get_default_flow(
    project_id: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return the configured default deployment flow id, or ``None``.

    Absence of a ``deploy_defaults`` entry returns ``None``. An entry whose
    payload cannot be parsed (malformed JSON, missing ``deployment_flow``
    key, non-string value) also returns ``None`` rather than raising —
    callers treat that as "no project default" and fall back.
    """
    slice_ = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    entries = slice_.get("entries") or []
    if not entries:
        return None
    payload = entries[0].get("payload") or {}
    flow = payload.get("deployment_flow")
    if isinstance(flow, str) and flow:
        return flow
    return None


def set_default_flow(
    project_id: str,
    flow_id: str,
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> None:
    """Upsert the project's default deployment flow."""
    if not isinstance(flow_id, str) or not flow_id:
        raise ValueError("flow_id must be a non-empty string")
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "put",
            "family": FAMILY,
            "attachment": "project",
            "payload": {"deployment_flow": flow_id},
        }],
        actor=actor,
        db_path=db_path,
    )


def set_default_flow_on_connection(
    conn: Any,
    project_id: str,
    flow_id: str,
) -> bool:
    """Upsert a default inside the caller-owned database transaction."""
    if not isinstance(flow_id, str) or not flow_id:
        raise ValueError("flow_id must be a non-empty string")
    numeric_project_id = resolve_project_id(conn, project_id)
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT payload FROM project_structure "
        f"WHERE project_id={placeholder} AND family='deploy_defaults' "
        "AND attachment_value='project' AND entry_key=''",
        (numeric_project_id,),
    ).fetchone()
    if row is not None:
        try:
            payload = json_helper.loads_text(str(row[0] or "{}"))
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and payload.get("deployment_flow") == flow_id:
            return False
    from yoke_core.domain.project_structure_write import apply_patch_on_connection

    apply_patch_on_connection(
        conn,
        project_id,
        ops=[{
            "op": "put",
            "family": FAMILY,
            "attachment": "project",
            "payload": {"deployment_flow": flow_id},
        }],
    )
    return True


def clear_default_flow(
    project_id: str,
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> bool:
    """Remove the project's default deployment flow.

    Returns ``True`` when an entry was removed, ``False`` when no entry
    existed — so callers can differentiate "already empty" from "removed".
    """
    state = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    if not state.get("entries"):
        return False
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "remove",
            "family": FAMILY,
            "attachment": "project",
        }],
        actor=actor,
        db_path=db_path,
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_set(args: argparse.Namespace) -> int:
    try:
        set_default_flow(args.project_id, args.flow_id, actor=args.actor)
    except (ValueError, ps.ProjectStructureError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Set deploy_defaults for '{args.project_id}' -> {args.flow_id}")
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    try:
        removed = clear_default_flow(args.project_id, actor=args.actor)
    except ps.ProjectStructureError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if removed:
        print(f"Cleared deploy_defaults for '{args.project_id}'")
    else:
        print(f"No deploy_defaults entry to clear for '{args.project_id}'")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.deploy_defaults",
        description="Write the project-level deployment-flow default.",
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_set = sub.add_parser("set", help="Upsert the project default flow id")
    p_set.add_argument("project_id")
    p_set.add_argument("flow_id")
    p_set.add_argument("--actor")

    p_clear = sub.add_parser("clear", help="Remove the project default entry")
    p_clear.add_argument("project_id")
    p_clear.add_argument("--actor")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.subcmd:
        parser.print_help(sys.stderr)
        return 2
    dispatch = {"set": _cmd_set, "clear": _cmd_clear}
    return dispatch[args.subcmd](args)


if __name__ == "__main__":
    sys.exit(main())
