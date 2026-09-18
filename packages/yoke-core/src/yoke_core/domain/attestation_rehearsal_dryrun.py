"""Refine-time dry-run validator for ``db_compatibility_attestation.rehearsal_commands``.

Resolves which commands an item declared, then hands them to
:mod:`attestation_rehearsal_command_shape`, which parses and stats each
one against the worktree filesystem without executing it. The pure
read-and-dry-run contract ("does not modify any DB row, lease, or
path-claim") is satisfied by construction: the validator never spawns a
subprocess, never writes, never touches the lease table. The known
rehearsal failure modes (literal ``<worktree>`` placeholder; wrong-path
pytest argument) are both path-existence failures and detect cleanly via
shlex + os.path — the executing-validator's "extra depth" was reproducing
what the production runner already does at implementation entry.

Short-circuits — the validator returns an empty list (no work, no
side effects) when:

* ``items.db_mutation_profile.state != "declared"``,
* ``items.db_compatibility_attestation`` is absent / unparseable,
* the attestation's ``frozen_at`` is unset, or
* ``rehearsal_commands`` is empty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.attestation_rehearsal_command_shape import (
    issue_payloads_for_commands,
    validate_command_shapes,
)
from yoke_core.domain.db_compatibility_attestation import (
    _safe_parse_dict as _parse_attestation,
)
from yoke_core.domain.db_mutation_profile import (
    STATE_DECLARED as _PROFILE_STATE_DECLARED,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _read_optional_item_column(
    conn: Any, item_id: int, column: str,
) -> Any:
    """Read one items column, tolerating missing columns on slim schemas."""
    p = _p(conn)
    transaction = getattr(conn, "transaction", None)
    if callable(transaction):
        try:
            with transaction():
                row = conn.execute(
                    f"SELECT {column} FROM items WHERE id = {p}",
                    (item_id,),
                ).fetchone()
        except db_backend.operational_error_types(conn=conn):
            return None
    else:
        try:
            row = conn.execute(
                f"SELECT {column} FROM items WHERE id = {p}",
                (item_id,),
            ).fetchone()
        except db_backend.operational_error_types(conn=conn):
            return None
    if row is None:
        return None
    return row[0]


def _read_profile(conn: Any, item_id: int) -> Optional[Dict[str, Any]]:
    raw = _read_optional_item_column(conn, item_id, "db_mutation_profile")
    if raw is None:
        return None
    return _parse_attestation(raw)


def _read_attestation(
    conn: Any,
    item_id: int,
) -> Optional[Dict[str, Any]]:
    raw = _read_optional_item_column(conn, item_id, "db_compatibility_attestation")
    if raw is None:
        return None
    return _parse_attestation(raw)


def _planned_claim_paths(conn: Any, item_id: int) -> Set[str]:
    p = _p(conn)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT pt.path_string
            FROM path_claims pc
            JOIN path_claim_targets pct ON pct.claim_id = pc.id
            JOIN path_targets pt ON pt.id = pct.target_id
            WHERE pc.owner_kind = 'item'
              AND pc.owner_item_id = {p}
              AND pc.state IN ('planned', 'blocked', 'active')
              AND pt.materialization_state = 'planned'
            """,
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return set()
    return {str(row[0]) for row in rows if row[0]}


def rehearsal_command_inputs(
    conn: Any, item_id: int,
) -> Tuple[List[str], Set[str]]:
    """Return the control-plane inputs the shape check reads per item.

    ``([], set())`` means "no governed mutation declared, or nothing to
    validate". Separated from the stat-ing pass so a host holding the
    control plane but no checkout can resolve these and hand them to the
    host that does have the files.
    """
    profile = _read_profile(conn, item_id)
    if not profile or profile.get("state") != _PROFILE_STATE_DECLARED:
        return ([], set())

    attestation = _read_attestation(conn, item_id)
    if not attestation or not attestation.get("frozen_at"):
        return ([], set())
    commands = [str(cmd) for cmd in (attestation.get("rehearsal_commands") or [])]
    if not commands:
        return ([], set())
    return (commands, _planned_claim_paths(conn, item_id))


def validate_attestation_rehearsal_commands(
    conn: Any,
    item_id: int,
    *,
    repo_root: Path,
) -> List[Any]:
    """Parse-and-stat every ``rehearsal_commands`` entry.

    Returns one ``ValidationOutcome`` per command. An empty list means
    "no governed mutation declared, or nothing to validate" — callers
    treat that as PASS without further action.
    """
    commands, planned_paths = rehearsal_command_inputs(conn, item_id)
    return validate_command_shapes(
        commands, repo_root=repo_root, planned_paths=planned_paths,
    )


def issue_payloads_for_item(
    conn: Any,
    item_id: int,
    *,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    """Return one ``Issue``-shaped dict per failing rehearsal command."""
    from yoke_core.domain.project_identity import render_item_ref

    commands, planned_paths = rehearsal_command_inputs(conn, item_id)
    return issue_payloads_for_commands(
        commands,
        repo_root=repo_root,
        planned_paths=planned_paths,
        public_ref=render_item_ref(conn, item_id),
    )


def verify_attestation_rehearsal_commands(
    conn: Any, item_id: int, *, repo_root: Path,
):
    """Thin facade that returns ``Issue`` rows for the readiness check.

    Lives here (not in :mod:`idea_readiness_check`) to keep the
    readiness file under its 350-line cap, which takes precedence
    over surface locality.
    Re-exported from :mod:`idea_readiness_check` for callers that
    expect the wrapper at its named location.

    ``repo_root`` is the item project's checkout, resolved once by the
    caller: every path token is stat-ed against it, so the tree must be
    the item's own rather than whatever the host stands in.
    """
    from yoke_core.domain.idea_readiness_results import Issue

    return [
        Issue(**p)
        for p in issue_payloads_for_item(conn, item_id, repo_root=repo_root)
    ]


__all__ = [
    "issue_payloads_for_item",
    "rehearsal_command_inputs",
    "validate_attestation_rehearsal_commands",
    "verify_attestation_rehearsal_commands",
]
