"""Which QA target kinds this serving runtime can actually observe.

A QA stage reads its target from an earlier stage's receipt, so a target
kind with no registered receipt producer cannot be executed however
complete the rest of the release runtime is. That makes target-kind
support a separate axis from the definition schema version in
:mod:`deployment_flow_policy`, and the two move independently: a producer
arrives for one kind without changing the vocabulary, and the vocabulary
accepts a kind before anything can produce it.

Refusing here — at the gates that activate, update-active, assign and
start a definition — means raising the schema version never advertises a
kind that would only fail mid-run, after earlier stages had already
deployed. The producer's own mid-run refusal stays as defense-in-depth.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA


def _stage_list(stages: Any) -> list[Any]:
    """The decoded stage list, from the list or the JSON callers hold.

    Both are live shapes on the definition paths these guards cover. A
    shape this cannot read raises rather than reporting "nothing
    unsupported", which is the one answer that would let an unobservable
    target through.
    """
    if isinstance(stages, str):
        stages = json_helper.loads_text(stages)
    if not isinstance(stages, list):
        raise ValueError(
            "deployment flow stages must be a list to check target support; "
            f"got {type(stages).__name__}"
        )
    return stages


def _is_qa_stage(stage: Mapping[str, Any]) -> bool:
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        or stage.get("step_runner") == QA_STEP_RUNNER
    )


def unsupported_stage_target_kinds(stages: Any) -> tuple[str, ...]:
    """QA target kinds in *stages* that no receipt producer can observe.

    A QA stage reads its target from an earlier stage's receipt, so a kind
    with no registered producer cannot be executed however complete the
    rest of the runtime is. Reported separately from the schema version
    because the two axes move independently: a producer arrives for one
    kind without changing the vocabulary, and the vocabulary can accept a
    kind before anything can produce it.

    Accepts the decoded stage list or the JSON its callers hold, because
    both are live shapes on the definition paths this guards — and a
    shape it cannot read raises rather than reporting "nothing
    unsupported", which is the one answer that would let an
    unobservable target through.
    """
    from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
        RECEIPT_PRODUCERS,
    )

    stages = _stage_list(stages)
    unsupported: list[str] = []
    for stage in stages:
        if not isinstance(stage, Mapping):
            continue
        if not _is_qa_stage(stage):
            continue
        target = stage.get("target")
        if not isinstance(target, Mapping):
            continue
        kind = str(target.get("kind") or "")
        if kind and kind not in RECEIPT_PRODUCERS and kind not in unsupported:
            unsupported.append(kind)
    return tuple(unsupported)


def unprovable_qa_identity_stages(stages: Any) -> tuple[str, ...]:
    """QA stages whose producing stage cannot prove a candidate identity.

    Supporting a target KIND is not the same as being able to observe one,
    and conflating them advertises more than the runtime can do. A QA stage
    reads its target from an earlier stage's receipt, and that receipt is
    only evidence if the producing step runner returned a *verified*
    identity rather than a diagnostic string. Today only the Yoke core
    health contract does that, so a project that deploys its own
    environment through its own workflow has a perfectly valid
    ``persistent_environment`` target that nothing here can settle.

    Reported per QA stage rather than per kind, because the gap is the
    producing runner: the same kind is supported behind one runner and not
    behind another. Each entry names the QA stage, its source stage, and
    that runner.
    """
    from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
        IDENTITY_PROVING_STEP_RUNNERS,
        RUNNER_VERIFIED_TARGET_KINDS,
    )

    decoded = _stage_list(stages)
    by_name = {
        str(stage.get("name") or ""): stage
        for stage in decoded
        if isinstance(stage, Mapping)
    }
    unprovable: list[str] = []
    for stage in decoded:
        if not isinstance(stage, Mapping) or not _is_qa_stage(stage):
            continue
        target = stage.get("target")
        if not isinstance(target, Mapping):
            continue
        if str(target.get("kind") or "") not in RUNNER_VERIFIED_TARGET_KINDS:
            # This kind's producer reads the target back itself, so the
            # runner that deployed it owes no identity proof.
            continue
        source_name = str(target.get("source_stage") or "")
        source = by_name.get(source_name)
        runner = (
            str(source.get("step_runner") or "") if isinstance(source, Mapping) else ""
        )
        if runner in IDENTITY_PROVING_STEP_RUNNERS:
            continue
        unprovable.append(
            f"{str(stage.get('name') or '')!r} reads its target from "
            f"{source_name!r}, whose step runner "
            f"{runner or '<unresolved>'!r} returns no verified candidate "
            "identity"
        )
    return tuple(unprovable)


def require_provable_qa_identity(stages: Any, *, operation: str) -> None:
    """Refuse a definition whose QA target identity cannot be verified.

    Raised at the same gates the schema version and target kinds guard, so
    the refusal lands before anything deploys. Deploying first and failing
    the receipt afterwards would leave a real environment changed by a run
    that could never complete.
    """
    unprovable = unprovable_qa_identity_stages(stages)
    if not unprovable:
        return
    listed = "; ".join(unprovable)
    raise ValueError(
        f"{operation} declares QA stage(s) whose deployed identity this "
        f"serving runtime cannot verify: {listed}. Register a receipt "
        "producer that reads the served revision for that target through "
        "the project's configured identity capability, and add its step "
        "runner to deploy_pipeline_stage_receipt_producers."
        "IDENTITY_PROVING_STEP_RUNNERS, before enabling this definition"
    )


def require_supported_stage_targets(stages: Any, *, operation: str) -> None:
    """Refuse a definition whose QA target kinds have no producer.

    Raised at the same gates the schema version guards — activating,
    updating an active definition, assigning, starting — so an unsupported
    kind is refused before a run exists rather than after earlier stages
    have already deployed. The mid-run producer refusal stays as
    defense-in-depth.
    """
    unsupported = unsupported_stage_target_kinds(stages)
    if not unsupported:
        return
    listed = ", ".join(sorted(unsupported))
    raise ValueError(
        f"{operation} names QA target kind(s) {listed} that no receipt "
        "producer in this serving runtime can observe; keep the definition "
        "disabled until a producer for that kind is registered in "
        "deploy_pipeline_stage_receipt_producers.RECEIPT_PRODUCERS"
    )


def require_supported_stage_targets_for_flow(
    conn: Any, flow_id: str, *, operation: str
) -> None:
    """Check a stored definition's target kinds, by flow id.

    The three gates that hold only a flow id read its stages through
    here so the read happens one way. A schema with no ``stages`` column
    cannot express a QA target at all, so there is nothing to refuse and
    nothing to read — that is a different answer from "the read failed",
    and it is why the column is checked rather than the query being
    wrapped in a blanket except.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _column_exists

    if not _column_exists(conn, "deployment_flows", "stages"):
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT stages FROM deployment_flows WHERE id={marker}", (flow_id,)
    ).fetchone()
    if row is None:
        return
    stored = str(row[0] or "[]")
    require_supported_stage_targets(stored, operation=operation)
    require_provable_qa_identity(stored, operation=operation)


__all__ = [
    "require_provable_qa_identity",
    "require_supported_stage_targets",
    "require_supported_stage_targets_for_flow",
    "unprovable_qa_identity_stages",
    "unsupported_stage_target_kinds",
]
