"""Item-project checkout resolution for the readiness checks.

File Budget paths and function-owner refs are project-relative, so every
readiness check that reads files needs the checkout for the *item's*
project on the host executing the check. That checkout is resolved once
here, from this machine's registered project mapping, and passed to each
checkout-dependent check.

There is deliberately no ambient fallback. A hosted API host has no
project checkout at all: the walk-up / cwd / ``git rev-parse`` fallbacks
this resolution used to carry either raised on that host or silently
validated an item against whatever tree the server process happened to
stand in. When no checkout is available the caller records an
:class:`UnavailableValidation` naming the unperformed check instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from . import db_backend
from yoke_core.domain.idea_readiness_results import UnavailableValidation
from yoke_core.domain.project_checkout_locations import checkout_for_project_id

CHECKOUT_UNAVAILABLE_REASON = "project_checkout_unavailable"

# Every readiness check that reads the item project's files. Named
# individually so an unavailable run says exactly what went unverified.
CHECKOUT_DEPENDENT_CHECKS = (
    "verify_function_owners",
    "verify_file_budget_line_counts",
    "verify_attestation_rehearsal_commands",
    "collect_symlink_advisories",
)


def item_project_checkout(
    conn: Optional[Any], item_id: int,
) -> Optional[Path]:
    """Return this machine's checkout for the item's project, or ``None``.

    ``None`` means the file-backed checks cannot run here — it never means
    "use some other tree".
    """
    project_id, _slug = item_project_identity(conn, item_id)
    if project_id is None:
        return None
    candidate = checkout_for_project_id(project_id)
    if candidate is None or not candidate.is_dir():
        return None
    return candidate


def item_project_identity(
    conn: Optional[Any], item_id: int,
) -> Tuple[Optional[int], str]:
    """Return ``(project_id, project_slug)`` for an item, best effort."""
    if conn is None or not item_id:
        return (None, "")
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT i.project_id, p.slug FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return (None, "")
    if not row or not row[0]:
        return (None, "")
    return (int(row[0]), str(row[1] or ""))


def checkout_unavailable(
    check: str, conn: Optional[Any], item_id: int,
) -> UnavailableValidation:
    """Name one readiness check the executing host could not perform."""
    project_id, slug = item_project_identity(conn, item_id)
    project = slug or (f"id {project_id}" if project_id else "this item's project")
    register = (
        f"yoke project register <checkout> --project-id {project_id}"
        if project_id
        else "yoke project register <checkout> --project-id <id>"
    )
    return UnavailableValidation(
        check=check,
        reason=CHECKOUT_UNAVAILABLE_REASON,
        recovery=(
            f"{check} reads files, and the host that ran this check has no "
            f"checkout for project {project}. Re-run readiness from a machine "
            f"whose checkout for that project is registered "
            f"(`{register}`). Project checkouts are not installed on the "
            f"hosted API host, so rerunning there cannot resolve this."
        ),
        context={"project_id": project_id, "project": slug},
    )


def unavailable_checkout_dependent_checks(
    conn: Optional[Any], item_id: int,
) -> List[UnavailableValidation]:
    """Report every checkout-dependent check as unperformed."""
    return [
        checkout_unavailable(check, conn, item_id)
        for check in CHECKOUT_DEPENDENT_CHECKS
    ]


__all__ = [
    "CHECKOUT_DEPENDENT_CHECKS",
    "CHECKOUT_UNAVAILABLE_REASON",
    "checkout_unavailable",
    "item_project_checkout",
    "item_project_identity",
    "unavailable_checkout_dependent_checks",
]
