"""Refuse a settings write that would orphan bound QA evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    target_digest,
)
from yoke_core.domain.qa_requirement_rebind_identity import (
    REBIND_RECIPE,
    _identity_row,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)


class StrandedQaEvidenceError(ValueError):
    """A settings write would orphan bound QA evidence without acknowledgement."""

    def __init__(self, message: str, stranded: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.stranded = stranded


def _preview_target(
    conn: Any, identity: Mapping[str, Any], settings: Mapping[str, Any]
) -> dict[str, Any] | None:
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )

    overlay = dict(identity)
    overlay["settings"] = json.dumps(dict(settings))
    try:
        return environment_execution_target(conn, overlay, require_runtime_match=False)
    except (QaExecutionTargetError, ValueError, TypeError):
        return None


def list_stranded_requirements(conn: Any, *, digest: str) -> list[dict[str, Any]]:
    if not digest or not _table_exists(conn, "qa_requirements"):
        return []
    return [
        {
            "requirement_id": int(row["id"]),
            "item_id": int(row["item_id"]) if row["item_id"] is not None else None,
            "deployment_run_id": str(row["deployment_run_id"] or "") or None,
        }
        for row in query_rows(
            conn,
            "SELECT id, item_id, deployment_run_id FROM qa_requirements "
            "WHERE execution_target_digest=%s AND retracted_at IS NULL "
            "ORDER BY id",
            (str(digest),),
        )
    ]


def refuse_or_describe_stranded_evidence(
    conn: Any,
    *,
    environment_id: int,
    assignments: Mapping[str, Any],
    acknowledge: bool,
) -> list[dict[str, Any]]:
    """Refuse a digest-moving settings write unless it is acknowledged."""
    identity = _identity_row(conn, environment_id)
    if identity is None:
        return []
    current_settings = parse_settings_object(
        str(identity.get("settings") or "{}"), what="environment settings"
    )
    proposed_settings = apply_key_path_assignments(
        dict(current_settings), dict(assignments)
    )
    current = _preview_target(conn, identity, current_settings)
    proposed = _preview_target(conn, identity, proposed_settings)
    if current is None:
        return []
    if proposed is not None and target_digest(current) == target_digest(proposed):
        return []
    stranded = list_stranded_requirements(conn, digest=target_digest(current))
    if not stranded:
        return []
    items = sorted({row["item_id"] for row in stranded if row["item_id"] is not None})
    summary = (
        f"this write moves the QA execution-target digest and would strand "
        f"{len(stranded)} requirement(s)"
        + (f" on item(s) {items}" if items else "")
        + "; pass acknowledge_stranded_evidence to continue, then rebind "
        "each still-valid row with " + REBIND_RECIPE.format(requirement_id="<id>")
    )
    if not acknowledge:
        raise StrandedQaEvidenceError(summary, stranded)
    return stranded


__all__ = [
    "StrandedQaEvidenceError",
    "list_stranded_requirements",
    "refuse_or_describe_stranded_evidence",
]
