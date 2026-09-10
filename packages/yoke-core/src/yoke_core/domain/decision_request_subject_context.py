"""Validated decision facts carried by human approval requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

from yoke_core.domain.deployment_run_release_effect import CONSEQUENCES, DEPLOYS
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


def workflow_default_approval_source(stage: str) -> dict[str, str]:
    """Identify the workflow policy entry that selected an approval."""
    return {
        "kind": APPROVAL_SOURCE_WORKFLOW_DEFAULT,
        "entry": f"approval_defaults.{stage}",
    }


def item_posture_approval_source() -> dict[str, str]:
    """Identify the item posture entry that selected an approval."""
    return {
        "kind": APPROVAL_SOURCE_ITEM_POSTURE,
        "entry": "workflow_posture.approval_on_done",
    }


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


#: What a QA review is a review OF. The three homes ask different questions --
#: an item's verification decides whether a branch is sound, a deployment run's
#: post-release check records what a shipped release did -- so the surface that
#: renders the decision must be told which one it is holding.
REVIEW_SUBJECT_KINDS = ("item", "deployment_run", "plan")


def _validate_review_subject(context: Mapping[str, Any]) -> None:
    kind = QA_NEEDS_REVIEW
    subject = _mapping(kind, context["subject"], "subject")
    _required(
        kind,
        subject,
        {
            "kind",
            "item_id",
            "item_ref",
            "item_title",
            "deployment_run_id",
            "target_environment",
            "qa_phase",
        },
    )
    if subject["kind"] not in REVIEW_SUBJECT_KINDS:
        _fail(kind, f"has unknown subject kind {str(subject['kind'])!r}")
    _text(kind, subject["qa_phase"], "subject.qa_phase")
    if subject["kind"] == "item" and subject["item_id"] is None:
        _fail(kind, "requires subject.item_id for an item review")
    if subject["kind"] == "deployment_run" and not subject["deployment_run_id"]:
        _fail(kind, "requires subject.deployment_run_id for a deployment review")


def _validate_qa(context: Mapping[str, Any]) -> None:
    kind = QA_NEEDS_REVIEW
    _required(
        kind,
        context,
        {
            "requirement_id",
            "run_id",
            "subject",
            "code_revision",
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
    _validate_review_subject(context)
    if context["code_revision"] is not None:
        _text(kind, context["code_revision"], "code_revision")
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


def _validate_carried(kind: str, value: Any) -> None:
    """A new request always answers what the release carries, even negatively.

    Membership answers which items the pipeline owns; an environment run owns
    none while still shipping every change merged since the last release. The
    derived answer is required so no card can imply an empty release, and its
    unavailable form is a named reason rather than an absence.
    """
    carried = _mapping(kind, value, "carried")
    _required(kind, carried, {"derivation", "items", "commits"})
    derivation = _mapping(kind, carried["derivation"], "carried.derivation")
    # `contents_known` separates "this release carries nothing" from "the
    # contents could not be determined", which a reader must never conflate.
    _required(kind, derivation, {"status", "contents_known", "reason", "recovery"})
    for field in ("status", "reason", "recovery"):
        _text(kind, derivation[field], f"carried.derivation.{field}")
    for index, raw in enumerate(_sequence(kind, carried["items"], "carried.items")):
        entry = _mapping(kind, raw, f"carried.items[{index}]")
        _required(kind, entry, {"item_id", "ref", "commit_shas"})
        _positive_int(kind, entry["item_id"], f"carried.items[{index}].item_id")
        _text(kind, entry["ref"], f"carried.items[{index}].ref")


def _validate_release_effect(kind: str, value: Any) -> None:
    """A new request always says whether resolving it deploys anything.

    A gate that reaches nothing outside the control plane and one that ships a
    production release are opposite decisions, and the approver can only tell
    them apart if the request carries the answer plus the facts behind it.
    "Could not be established" is the third answer rather than a missing one,
    and both it and a non-deploying claim have to name the consequence they
    assert instead; an affirmative deploy is described by the release contents
    the reader already has.
    """
    effect = _mapping(kind, value, "release_effect")
    _required(kind, effect, {"consequence", "headline", "effect", "basis"})
    consequence = str(effect["consequence"])
    if consequence not in CONSEQUENCES:
        _fail(kind, f"has unknown release_effect consequence {consequence!r}")
    _text(kind, effect["headline"], "release_effect.headline")
    if consequence != DEPLOYS:
        _text(kind, effect["effect"], "release_effect.effect")
    basis = _sequence(kind, effect["basis"], "release_effect.basis")
    if not basis:
        _fail(kind, "requires release_effect.basis to name at least one fact")
    for index, entry in enumerate(basis):
        _text(kind, entry, f"release_effect.basis[{index}]")


def _validate_deployment(context: Mapping[str, Any]) -> None:
    kind = DEPLOYMENT_STAGE_APPROVAL
    _required(
        kind,
        context,
        {
            "run_id",
            "flow",
            "stage",
            "stage_position",
            "batch",
            "shipping",
            "carried",
            "release_effect",
        },
    )
    _validate_carried(kind, context["carried"])
    _validate_release_effect(kind, context["release_effect"])
    # Where the gate sits in its flow, so a sign-off after the release is not
    # described as though it were about to deploy.
    position = _mapping(kind, context["stage_position"], "stage_position")
    _required(kind, position, {"index", "total", "remaining"})
    for index, value_ in enumerate(
        _sequence(kind, position["remaining"], "stage_position.remaining")
    ):
        _text(kind, value_, f"stage_position.remaining[{index}]")
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
    "REVIEW_SUBJECT_KINDS",
    "DecisionRequestSubjectContextError",
    "SUBJECT_CONTEXT_INVALID",
    "SUBJECT_CONTEXT_RECOVERY",
    "item_posture_approval_source",
    "validate_subject_context",
    "workflow_default_approval_source",
]
