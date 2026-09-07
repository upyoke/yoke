"""The one window in which a run's release lineage may still be written.

A run prepared before its work merges cannot name the commit it will deploy,
because that commit does not exist yet: the merge creates it. So preparation
leaves ``release_lineage`` empty and the merge binds it afterward, which is
the only reason the column is writable after creation at all.

That window closes when the run leaves ``created``. After that the lineage is
the answer to "what did this run deploy", and the delivery gate compares it
against the merge it is supposed to prove; a lineage that can still move is a
lineage that can be made to agree with anything. So the write is refused
outside ``status='created'``, and refused again when the run already carries a
different commit — writing the same commit twice stays allowed, because an
interrupted continuation re-runs and must find that a no-op rather than a
conflict.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_scalar


LINEAGE_FIELD = "release_lineage"

#: Refusal for a preparation that tries to name the commit it will deploy.
PREPARE_NAMES_NO_LINEAGE = (
    "a prepared run cannot name a release lineage: the merge that creates "
    "that commit has not happened yet. Prepare without --release-lineage, "
    "then bind it at the merge that completes the pair with "
    "`yoke deployment-runs continue-for-item ITEM`"
)

_FULL_COMMIT = re.compile(r"[0-9a-f]{40}")


def refuse_lineage_write(
    conn: Any,
    run_id: str,
    value: str,
) -> Optional[str]:
    """Return a named refusal when *run_id* may not take *value* as lineage.

    Returns ``None`` when the write is allowed, including the idempotent case
    where the run already carries exactly *value*.
    """
    if not _FULL_COMMIT.fullmatch(value):
        return (
            f"Error: release_lineage '{value}' is not a full 40-hex commit; "
            "bind the exact merge commit the run will deploy"
        )
    row = conn.execute(
        "SELECT status, COALESCE(release_lineage, '') AS release_lineage "
        "FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return f"Error: deployment run '{run_id}' not found"
    status = str(row["status"] if hasattr(row, "keys") else row[0])
    current = str(row["release_lineage"] if hasattr(row, "keys") else row[1])
    if current == value:
        return None
    if status != "created":
        return (
            f"Error: deployment run '{run_id}' is {status}; release_lineage "
            "is bindable only while status='created'. Prepare a new run with "
            "`yoke deployment-runs start-for-item ITEM` for a different commit"
        )
    if current:
        return (
            f"Error: deployment run '{run_id}' already names release_lineage "
            f"{current}; refusing to rebind it to {value}. Cancel the run with "
            f"`yoke deployment-runs terminalize {run_id} --disposition "
            "cancelled --reason TEXT` and prepare a new one"
        )
    return None


def lineage_of(conn: Any, run_id: str) -> str:
    """Return the run's currently bound lineage, or an empty string."""
    return (
        query_scalar(
            conn,
            "SELECT COALESCE(release_lineage, '') FROM deployment_runs "
            "WHERE id=%s",
            (run_id,),
        )
        or ""
    )


__all__ = [
    "LINEAGE_FIELD",
    "PREPARE_NAMES_NO_LINEAGE",
    "lineage_of",
    "refuse_lineage_write",
]
