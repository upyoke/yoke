"""Validated decision facts carried by human approval requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    LIFECYCLE_TRANSITION_APPROVAL,
    QA_NEEDS_REVIEW,
)


SUBJECT_CONTEXT_INVALID = "decision_request_subject_context_invalid"
SUBJECT_CONTEXT_RECOVERY = (
    "Create the request through its owning QA, lifecycle, or deployment "
    "gate so the subject facts are populated from authoritative state."
)

APPROVAL_SOURCE_ITEM_POSTURE = "item_posture"
APPROVAL_SOURCE_WORKFLOW_DEFAULT = "workflow_approval_default"


class DecisionRequestSubjectContextError(ValueError):
    """A gate request omitted or contradicted facts needed for its decision."""

    code = SUBJECT_CONTEXT_INVALID


def _fail(kind: str, detail: str) -> NoReturn:
    raise DecisionRequestSubjectContextError(
        f"{SUBJECT_CONTEXT_INVALID}: {kind} subject_context {detail}. "
        f"Recovery: {SUBJECT_CONTEXT_RECOVERY}"
    )


def _mapping(kind: str, value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(kind, f"requires {field} to be an object")
    return value


def _sequence(kind: str, value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail(kind, f"requires {field} to be an array")
    return value


def _text(kind: str, value: Any, field: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        _fail(kind, f"requires a non-empty {field}")
    return clean


def _positive_int(kind: str, value: Any, field: str) -> int:
    if isinstance(value, bool):
        _fail(kind, f"requires {field} to be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        _fail(kind, f"requires {field} to be a positive integer")
    if number < 1:
        _fail(kind, f"requires {field} to be a positive integer")
    return number


def _nonnegative_int(kind: str, value: Any, field: str) -> int:
    if isinstance(value, bool):
        _fail(kind, f"requires {field} to be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        _fail(kind, f"requires {field} to be a non-negative integer")
    if number < 0:
        _fail(kind, f"requires {field} to be a non-negative integer")
    return number


def _required(kind: str, context: Mapping[str, Any], fields: set[str]) -> None:
    missing = sorted(fields.difference(context))
    if missing:
        _fail(kind, "is missing required facts: " + ", ".join(missing))


def _validate_qa(context: Mapping[str, Any]) -> None:
    kind = QA_NEEDS_REVIEW
    _required(
        kind,
        context,
        {
            "requirement_id",
            "run_id",
            "expected_outcome",
            "verdict_reason",
            "artifacts",
            "artifact_count",
            "evidence_state",
            "evidence_summary",
        },
    )
    _positive_int(kind, context["requirement_id"], "requirement_id")
    _positive_int(kind, context["run_id"], "run_id")
    _text(kind, context["expected_outcome"], "expected_outcome")
    _text(kind, context["verdict_reason"], "verdict_reason")
    _text(kind, context["evidence_summary"], "evidence_summary")
    artifacts = _sequence(kind, context["artifacts"], "artifacts")
    count = _nonnegative_int(kind, context["artifact_count"], "artifact_count")
    if count != len(artifacts):
        _fail(kind, "requires artifact_count to equal the artifacts array length")
    expected_state = "attached" if count else "missing"
    if context["evidence_state"] != expected_state:
        _fail(kind, f"requires evidence_state={expected_state!r} for {count} artifacts")
    for index, raw in enumerate(artifacts):
        artifact = _mapping(kind, raw, f"artifacts[{index}]")
        _required(kind, artifact, {"artifact_id", "artifact_type"})
        _positive_int(kind, artifact["artifact_id"], f"artifacts[{index}].artifact_id")
        _text(kind, artifact["artifact_type"], f"artifacts[{index}].artifact_type")


def _validate_lifecycle(context: Mapping[str, Any]) -> None:
    kind = LIFECYCLE_TRANSITION_APPROVAL
    _required(
        kind,
        context,
        {
            "item_id",
            "item_ref",
            "item_title",
            "from_stage",
            "to_stage",
            "workflow_id",
            "workflow_version_id",
            "branch_changes",
            "approval_source",
        },
    )
    _positive_int(kind, context["item_id"], "item_id")
    for field in ("item_ref", "item_title", "from_stage", "to_stage", "workflow_id"):
        _text(kind, context[field], field)
    _positive_int(kind, context["workflow_version_id"], "workflow_version_id")
    changes = _mapping(kind, context["branch_changes"], "branch_changes")
    _required(kind, changes, {"branch", "commit_sha", "touched_files", "summary"})
    for field in ("branch", "commit_sha"):
        if changes[field] is not None:
            _text(kind, changes[field], f"branch_changes.{field}")
    _text(kind, changes["summary"], "branch_changes.summary")
    paths = _sequence(kind, changes["touched_files"], "branch_changes.touched_files")
    for index, value in enumerate(paths):
        _text(kind, value, f"branch_changes.touched_files[{index}]")
    source = _mapping(kind, context["approval_source"], "approval_source")
    _required(kind, source, {"kind", "entry"})
    source_kind = str(source["kind"])
    if source_kind not in {
        APPROVAL_SOURCE_ITEM_POSTURE,
        APPROVAL_SOURCE_WORKFLOW_DEFAULT,
    }:
        _fail(kind, f"has unknown approval_source kind {source_kind!r}")
    _text(kind, source["entry"], "approval_source.entry")


def _validate_deployment(context: Mapping[str, Any]) -> None:
    kind = DEPLOYMENT_STAGE_APPROVAL
    _required(kind, context, {"run_id", "flow", "stage", "batch", "shipping"})
    _text(kind, context["run_id"], "run_id")
    _text(kind, context["stage"], "stage")
    flow = _mapping(kind, context["flow"], "flow")
    _required(kind, flow, {"id", "name"})
    _text(kind, flow["id"], "flow.id")
    _text(kind, flow["name"], "flow.name")
    batch = _mapping(kind, context["batch"], "batch")
    _required(kind, batch, {"item_count", "items"})
    items = _sequence(kind, batch["items"], "batch.items")
    count = _nonnegative_int(kind, batch["item_count"], "batch.item_count")
    if count != len(items):
        _fail(kind, "requires batch.item_count to equal the batch.items length")
    for index, raw in enumerate(items):
        item = _mapping(kind, raw, f"batch.items[{index}]")
        _required(kind, item, {"item_id", "item_ref", "title"})
        _positive_int(kind, item["item_id"], f"batch.items[{index}].item_id")
        _text(kind, item["item_ref"], f"batch.items[{index}].item_ref")
        _text(kind, item["title"], f"batch.items[{index}].title")
    shipping = _mapping(kind, context["shipping"], "shipping")
    _required(kind, shipping, {"release_lineage", "target_environment", "summary"})
    if shipping["release_lineage"] is not None:
        _text(kind, shipping["release_lineage"], "shipping.release_lineage")
    _text(kind, shipping["target_environment"], "shipping.target_environment")
    _text(kind, shipping["summary"], "shipping.summary")


_VALIDATORS = {
    QA_NEEDS_REVIEW: _validate_qa,
    LIFECYCLE_TRANSITION_APPROVAL: _validate_lifecycle,
    DEPLOYMENT_STAGE_APPROVAL: _validate_deployment,
}


def validate_subject_context(
    kind: str,
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate gate-specific facts and return a detached JSON-ready object."""
    context = dict(value or {})
    validator = _VALIDATORS.get(kind)
    if validator is not None:
        validator(context)
    return context


__all__ = [
    "APPROVAL_SOURCE_ITEM_POSTURE",
    "APPROVAL_SOURCE_WORKFLOW_DEFAULT",
    "DecisionRequestSubjectContextError",
    "SUBJECT_CONTEXT_INVALID",
    "SUBJECT_CONTEXT_RECOVERY",
    "validate_subject_context",
]
