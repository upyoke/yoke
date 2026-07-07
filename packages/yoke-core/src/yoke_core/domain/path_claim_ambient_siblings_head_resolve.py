"""Integration-head SHA + local-checkout lookup helpers for ambient siblings.

Split out of :mod:`path_claim_ambient_siblings` after the parent grew
past the 350-line gate. Owns the small surface that resolves the
current integration-target head SHA and this machine's checkout for a
project referenced by a non-terminal claim on that target.

Both helpers are best-effort — they return ``None`` on any miss
(missing DB columns, unresolvable refs, missing checkout mapping) so the
caller's age-hint bucket can degrade to ``"unknown"`` rather than
raise during render.
"""

from __future__ import annotations

import subprocess
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_integration_head_sha(
    conn: Any, integration_target: str,
) -> Optional[str]:
    """Resolve the current integration-target head SHA via git rev-parse."""
    repo_path = _resolve_repo_path_for_target(conn, integration_target)
    if not repo_path:
        return None
    for ref in (
        f"refs/remotes/origin/{integration_target}",
        f"refs/heads/{integration_target}",
    ):
        try:
            proc = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--verify", ref],
                capture_output=True, text=True, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if sha:
                return sha
    return None


def _resolve_repo_path_for_target(
    conn: Any, integration_target: str,
) -> Optional[str]:
    """Look up this machine's checkout from any claim on this target."""
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT i.project_id "
            "FROM path_claims pc "
            "JOIN items i ON i.id = pc.item_id "
            f"WHERE pc.integration_target = {p} "
            "AND i.project_id IS NOT NULL "
            "LIMIT 1",
            (integration_target,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        return None
    value = row[0] if not hasattr(row, "keys") else row["project_id"]
    checkout = checkout_for_project_id(int(value)) if value is not None else None
    return str(checkout) if checkout is not None else None


__all__ = ["resolve_integration_head_sha"]
