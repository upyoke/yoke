"""Stage-shape validation for deployment flows.

Validates the JSON ``stages`` array carried by ``deployment_flows`` rows.
A stage is either the executor-shape (``name`` + ``executor`` in the
:data:`VALID_EXECUTORS` vocabulary) or the kind-shape (``kind`` in the
:data:`VALID_STAGE_KINDS` vocabulary with kind-specific required fields).

Cross-referencing a ``migration_apply`` stage's ``model_name`` against
the project's declared ``migration_model`` capability lives in
:mod:`yoke_core.domain.flow_cross_reference` — this module is
project-agnostic shape validation only.
"""
from __future__ import annotations

import json
import re as _re

VALID_EXECUTORS = frozenset({
    "auto", "health-check", "environment-activate", "core-container-deploy",
    "ephemeral-deploy", "ephemeral-teardown", "ephemeral-verify",
    "human-approval", "github-actions-workflow",
})

# Stage "kind" vocabulary.  A stage with a ``kind`` field uses the
# governance-layer shape (§6.1e of the governed-DB-mutation spec) instead
# of the executor-shape above.  The kind binds a declared migration
# model to a lifecycle phase at which its governed apply runs.
VALID_STAGE_KINDS = frozenset({"migration_apply"})

# Lifecycle phases accepted for ``kind: "migration_apply"`` at governed DB-mutation gate.  Other
# phases are schema-reserved; the validator rejects them as "not yet
# supported in this slice."  Aligned with
# :data:`yoke_core.domain.lifecycle` terminology — ``implementing`` is
# the only wired option until future substrate unlocks more.
VALID_MIGRATION_APPLY_LIFECYCLE_PHASES = frozenset({"implementing"})
_ALL_LIFECYCLE_PHASES = frozenset({
    "implementing", "reviewing-implementation",
    "polishing-implementation", "release",
})

_STAGE_MODEL_NAME_RE = _re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_migration_apply_stage(i: int, stage: dict) -> None:
    """Validate a ``kind: "migration_apply"`` stage (§6.1e).

    Required keys: ``kind``, ``model_name``, ``lifecycle_phase``.
    Optional keys: ``name`` (operator-visible label; overrides the
    pipeline's kind-derived stage name — see
    ``deploy_pipeline_reporting._parse_stages``). The governed apply
    itself runs inside the ticket lifecycle; the pipeline stage verifies
    its evidence (``deploy_pipeline_migration``).
    """
    # Executor/kind exclusivity takes precedence over generic
    # unknown-keys reporting so operators get the concrete guidance.
    if "executor" in stage:
        raise ValueError(
            f'stage {i} cannot carry both "kind" and "executor"; '
            f"kind-based stages do not run through the executor vocabulary"
        )
    allowed = {"kind", "model_name", "lifecycle_phase", "name"}
    extra = set(stage.keys()) - allowed
    if extra:
        raise ValueError(
            f'stage {i} (kind=migration_apply) has unknown keys: {sorted(extra)}'
        )
    model_name = stage.get("model_name")
    if not isinstance(model_name, str) or not model_name:
        raise ValueError(
            f'stage {i} (kind=migration_apply) missing required field "model_name"'
        )
    if not _STAGE_MODEL_NAME_RE.match(model_name):
        raise ValueError(
            f'stage {i} (kind=migration_apply) model_name "{model_name}" '
            f"must be slug-shape (lowercase alnum, '_', '-')"
        )
    lifecycle_phase = stage.get("lifecycle_phase")
    if lifecycle_phase is None:
        raise ValueError(
            f'stage {i} (kind=migration_apply) missing required field "lifecycle_phase"'
        )
    if lifecycle_phase not in VALID_MIGRATION_APPLY_LIFECYCLE_PHASES:
        if lifecycle_phase in _ALL_LIFECYCLE_PHASES:
            raise ValueError(
                f'stage {i} (kind=migration_apply) lifecycle_phase '
                f'"{lifecycle_phase}" is recognized but not yet supported in this slice'
            )
        raise ValueError(
            f'stage {i} (kind=migration_apply) has invalid lifecycle_phase '
            f'"{lifecycle_phase}"'
        )


def validate_stages(stages_json: str) -> None:
    """Validate stages JSON.

    A stage is either the executor-shape (``name`` + ``executor`` in the
    VALID_EXECUTORS vocabulary) or the kind-shape (``kind`` in the
    VALID_STAGE_KINDS vocabulary with kind-specific required fields).
    """
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"stages is not valid JSON: {e}")

    if not isinstance(stages, list):
        raise ValueError("stages must be a JSON array")
    if not stages:
        raise ValueError("stages array must not be empty")

    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ValueError(f"stage {i} is not an object")

        if "kind" in stage:
            kind = stage["kind"]
            if kind not in VALID_STAGE_KINDS:
                raise ValueError(
                    f'stage {i} has invalid kind "{kind}". '
                    f"Must be one of: {' '.join(sorted(VALID_STAGE_KINDS))}"
                )
            if kind == "migration_apply":
                _validate_migration_apply_stage(i, stage)
            continue

        if "name" not in stage:
            raise ValueError(f'stage {i} missing required field "name"')
        if "executor" not in stage:
            raise ValueError(f'stage {i} missing required field "executor"')
        if stage["executor"] not in VALID_EXECUTORS:
            raise ValueError(
                f'stage {i} has invalid executor "{stage["executor"]}". '
                f"Must be one of: {' '.join(sorted(VALID_EXECUTORS))}"
            )
