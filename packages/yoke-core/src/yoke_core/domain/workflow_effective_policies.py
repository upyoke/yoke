"""Central resolution of an item's pinned workflow policies and posture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_FILE_BUDGET_REQUIRED,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_SURVEY_OPTIONAL,
    WORKFLOW_PATH_SURVEY_REQUIRED,
)
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)


@dataclass(frozen=True)
class EffectiveWorkflowPolicies:
    """One item's immutable definition policies after allowed tightening."""

    runtime: WorkflowRuntime
    posture: Mapping[str, Any]
    values: Mapping[str, Any]

    @property
    def file_budget(self) -> str:
        return str(self.values["file_budget"])

    @property
    def path_claims(self) -> str:
        return str(self.values["path_claims"])

    @property
    def path_survey(self) -> str:
        return str(self.values["path_survey"])

    @property
    def requires_file_budget(self) -> bool:
        return self.file_budget != WORKFLOW_FILE_BUDGET_OPTIONAL

    @property
    def requires_path_claims(self) -> bool:
        return self.path_claims != WORKFLOW_PATH_CLAIMS_OPTIONAL

    @property
    def requires_path_survey(self) -> bool:
        return self.path_survey != WORKFLOW_PATH_SURVEY_OPTIONAL

    @property
    def requires_budget_claim_parity(self) -> bool:
        return self.requires_file_budget and self.requires_path_claims


def _tighten_optional(
    value: str,
    *,
    selected: bool,
    optional: str,
    required: str,
) -> str:
    if value == optional and selected:
        return required
    return value


def resolve_effective_workflow_policies(
    runtime: WorkflowRuntime,
    posture: Mapping[str, Any] | None,
) -> EffectiveWorkflowPolicies:
    """Resolve definition defaults plus allowed item-level tightening.

    Schema-v1 definitions predate the independent File Budget axis. Their
    effective budget follows the effective path-claim setting so existing
    immutable pins retain the coupled behavior they were published with.
    """
    selected = dict(posture or {})
    values = dict(runtime.policies)
    raw_path_claims = str(values["path_claims"])
    effective_path_claims = _tighten_optional(
        raw_path_claims,
        selected=selected.get("path_claims") is True,
        optional=WORKFLOW_PATH_CLAIMS_OPTIONAL,
        required=WORKFLOW_PATH_CLAIMS_REQUIRED,
    )
    if "file_budget" in values:
        effective_file_budget = _tighten_optional(
            str(values["file_budget"]),
            selected=selected.get("file_budget") is True,
            optional=WORKFLOW_FILE_BUDGET_OPTIONAL,
            required=WORKFLOW_FILE_BUDGET_REQUIRED,
        )
    else:
        effective_file_budget = effective_path_claims
    values["path_claims"] = effective_path_claims
    values["file_budget"] = effective_file_budget
    raw_path_survey = values.get("path_survey")
    if raw_path_survey is None and runtime.workflow_id in {"blitz", "dash"}:
        raw_path_survey = WORKFLOW_PATH_SURVEY_REQUIRED
    if raw_path_survey is not None:
        values["path_survey"] = _tighten_optional(
            str(raw_path_survey),
            selected=selected.get("path_survey") is True,
            optional=WORKFLOW_PATH_SURVEY_OPTIONAL,
            required=WORKFLOW_PATH_SURVEY_REQUIRED,
        )
    return EffectiveWorkflowPolicies(
        runtime=runtime,
        posture=selected,
        values=values,
    )


def load_item_effective_workflow_policies(
    conn: Any,
    item_id: int,
) -> EffectiveWorkflowPolicies:
    """Load one item's pinned version and resolve its stored posture."""
    runtime = load_item_workflow_runtime(conn, int(item_id))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT workflow_posture FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    raw = row["workflow_posture"] if hasattr(row, "keys") else row[0]
    if isinstance(raw, Mapping):
        posture = dict(raw)
    else:
        try:
            parsed = json.loads(str(raw or "{}"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"item {item_id} has invalid workflow posture"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ValueError(f"item {item_id} workflow posture is not an object")
        posture = dict(parsed)
    return resolve_effective_workflow_policies(runtime, posture)


__all__ = [
    "EffectiveWorkflowPolicies",
    "load_item_effective_workflow_policies",
    "resolve_effective_workflow_policies",
]
