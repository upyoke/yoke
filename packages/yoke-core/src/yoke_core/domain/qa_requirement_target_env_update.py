"""Re-point one QA requirement at a different named environment.

Split from :mod:`qa_requirement_config_update`, which owns the update
dispatch and the case-content field. This is the target-identity field: it
resolves an environment name into the immutable endpoint snapshot and
digest a requirement is judged against, so it reaches for the environment
target resolvers the content path never needs.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one
# Re-pointing a requirement admitted into a started run would move the
# target its recorded evidence was judged against, so it is refused with
# the same frozen-snapshot code the content path uses.
from yoke_core.domain.qa_requirement_frozen_snapshot import (
    FROZEN_REQUIREMENT_MESSAGE,
)
from yoke_core.domain.qa_requirement_pass_currency import _marker
from yoke_core.domain.schema_common import _table_exists


def _prepare_target_env(
    conn: Any, existing: Any, value: Any
) -> tuple[Optional[tuple[Any, ...]], str]:
    run_id = existing["deployment_run_id"]
    project_id = None
    if run_id:
        run = query_one(
            conn,
            f"SELECT status, composition_frozen_at, project_id "
            f"FROM deployment_runs WHERE id={_marker(conn)}",
            (str(run_id),),
        )
        if run is None or str(run["status"] or "") != "created" or str(
            run["composition_frozen_at"] or existing.get("execution_target_digest") or ""
        ).strip():
            return None, FROZEN_REQUIREMENT_MESSAGE
        project_id = int(run["project_id"])
    name = str(value or "").strip() or None
    from yoke_core.domain.qa_environment_execution_target import (
        persistable_named_environment_target,
    )
    from yoke_core.domain.qa_execution_environment_target import (
        QaExecutionTargetError,
        canonical_target,
        target_digest,
    )

    owner = (
        existing["item_id"]
        if existing["item_id"] is not None
        else existing["epic_id"]
    )
    if owner is not None and project_id is None and _table_exists(conn, "items"):
        project_row = query_one(
            conn,
            f"SELECT project_id FROM items WHERE id={_marker(conn)}",
            (int(owner),),
        )
        if project_row is not None and project_row["project_id"] is not None:
            project_id = int(project_row["project_id"])
    if name and project_id is None and _table_exists(conn, "environments"):
        return None, (
            "requirement has no project to resolve an execution target against"
        )
    try:
        snapshot = None
        if name and project_id is not None and _table_exists(conn, "environments"):
            snapshot = persistable_named_environment_target(
                conn, project_id=int(project_id), environment_name=name
            )
    except QaExecutionTargetError as exc:
        return None, str(exc)
    target_json = canonical_target(snapshot) if snapshot else None
    digest = target_digest(snapshot) if snapshot else None
    return (name, target_json, digest), ""


__all__ = ["_prepare_target_env"]
