"""Validation for definition-bounded item posture selected at creation."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_FILE_BUDGET_OPTIONAL,
)


class ItemPostureError(ValueError):
    """Raised when a requested posture exceeds its workflow definition."""


def _verification(
    conn: Any,
    *,
    project_id: int,
    raw: Any,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ItemPostureError("verification posture must be an object")
    kind = str(raw.get("kind") or "")
    if kind == "plan":
        if set(raw) != {"kind", "plan_id"}:
            raise ItemPostureError(
                "plan verification requires exactly kind and plan_id"
            )
        plan_id = raw.get("plan_id")
        if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
            raise ItemPostureError("verification plan_id must be a positive integer")
        from yoke_core.domain.qa_plan_management import _plan_row

        plan = _plan_row(conn, plan_id)
        if int(plan["project_id"]) != int(project_id):
            raise ItemPostureError("verification plan is not in the item project")
        return {"kind": "plan", "plan_id": plan_id}
    if kind == "ad_hoc":
        if set(raw) != {"kind", "method_id"}:
            raise ItemPostureError(
                "ad_hoc verification requires exactly kind and method_id"
            )
        method_id = str(raw.get("method_id") or "").strip()
        if not method_id:
            raise ItemPostureError("verification method_id is required")
        from yoke_core.domain.qa_catalog_reads import get_method

        try:
            get_method(conn, method_id=method_id, project=str(project_id))
        except LookupError as exc:
            raise ItemPostureError(str(exc)) from exc
        return {"kind": "ad_hoc", "method_id": method_id}
    raise ItemPostureError("verification kind must be plan or ad_hoc")


def validate_item_posture(
    conn: Any,
    *,
    definition: Mapping[str, Any],
    project_id: int,
    posture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a normalized posture fully allowed by one pinned definition."""
    requested = dict(posture or {})
    allowed = set(definition["policies"]["item_posture_allowlist"])
    unknown = set(requested) - allowed
    if unknown:
        raise ItemPostureError(
            f"workflow disallows item posture keys: {sorted(unknown)}"
        )
    normalized: dict[str, Any] = {}
    for key, value in requested.items():
        if key == "verification":
            normalized[key] = _verification(
                conn, project_id=project_id, raw=value,
            )
            continue
        if (
            key == "file_budget"
            and definition["policies"]["file_budget"]
            != WORKFLOW_FILE_BUDGET_OPTIONAL
        ):
            raise ItemPostureError(
                "file_budget posture only tightens an optional workflow policy"
            )
        if value is not True:
            raise ItemPostureError(
                f"{key} posture must be true when selected; omit it otherwise"
            )
        normalized[key] = True
    return normalized


__all__ = ["ItemPostureError", "validate_item_posture"]
