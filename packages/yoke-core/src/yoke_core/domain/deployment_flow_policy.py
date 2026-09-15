"""Release-policy validation for deployment-flow stage definitions.

Legacy flow stages remain ordinary execution steps.  The richer definition
schema adds explicit execution/QA kinds, per-stage target selectors, QA scope,
case selection, verdict authority, and informational notification policy.
Runtime support is versioned separately so configuration can land before an
executor starts accepting those definitions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.approval_policy import parse_approval_policy
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.project_identity import resolve_project


LEGACY_DEFINITION_SCHEMA_VERSION = 1
RELEASE_POLICY_SCHEMA_VERSION = 2
CURRENT_EXECUTION_SCHEMA_VERSION = LEGACY_DEFINITION_SCHEMA_VERSION

STAGE_KIND_EXECUTION = "execution"
STAGE_KIND_QA = "qa"
STAGE_KINDS = frozenset({STAGE_KIND_EXECUTION, STAGE_KIND_QA})
QA_STEP_RUNNER = "qa"
QA_SCOPES = frozenset({"item", "run"})
VERDICT_MODES = frozenset({"agent_only", "human_if_unsure", "required_human"})
HUMAN_VERDICT_MODES = frozenset({"human_if_unsure", "required_human"})
TARGET_KINDS = frozenset({"persistent_environment", "run_preview"})

_ADVANCED_STAGE_KEYS = frozenset(
    {"stage_kind", "scope", "target", "cases", "verdict", "notification"}
)


def _mapping(raw: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must be an object")
    return raw


def _validate_cases(raw: Any, *, path: str) -> None:
    cases = _mapping(raw, path=path)
    extra = set(cases) - {"plan_id", "case_keys"}
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    plan_id = cases.get("plan_id")
    if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
        raise ValueError(f"{path}.plan_id must be a positive integer")
    case_keys = cases.get("case_keys")
    if case_keys is not None:
        if not isinstance(case_keys, list) or any(
            not isinstance(value, str) or not value.strip() for value in case_keys
        ):
            raise ValueError(f"{path}.case_keys must be non-empty names")
        if len(case_keys) != len(set(case_keys)):
            raise ValueError(f"{path}.case_keys must not contain duplicates")


def _validate_verdict(raw: Any, *, path: str) -> None:
    verdict = _mapping(raw, path=path)
    extra = set(verdict) - {"mode", "reviewers"}
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    mode = verdict.get("mode")
    if mode not in VERDICT_MODES:
        raise ValueError(
            f"{path}.mode must be one of: {', '.join(sorted(VERDICT_MODES))}"
        )
    reviewers = verdict.get("reviewers")
    if mode in HUMAN_VERDICT_MODES:
        if reviewers is None:
            raise ValueError(f"{path}.reviewers is required for mode={mode}")
        parse_approval_policy(reviewers, path=f"{path}.reviewers")
    elif reviewers is not None:
        raise ValueError(
            f"{path}.reviewers is not decision authority for mode=agent_only"
        )


def _validate_notification(raw: Any, *, path: str) -> None:
    notification = _mapping(raw, path=path)
    extra = set(notification) - {"enabled", "recipients"}
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    enabled = notification.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError(f"{path}.enabled must be a boolean")
    recipients = notification.get("recipients")
    if enabled:
        if recipients is None:
            raise ValueError(f"{path}.recipients is required when enabled")
        recipient_map = _mapping(recipients, path=f"{path}.recipients")
        if "mode" in recipient_map:
            raise ValueError(
                f"{path}.recipients has no ANY/ALL mode; notification is informational"
            )
        extra_recipients = set(recipient_map) - {"roles", "actors", "item_owners"}
        if extra_recipients:
            raise ValueError(
                f"{path}.recipients has unknown fields: {sorted(extra_recipients)}"
            )
        item_owners = recipient_map.get("item_owners", False)
        if not isinstance(item_owners, bool):
            raise ValueError(f"{path}.recipients.item_owners must be a boolean")
        policy = parse_approval_policy(
            {
                "roles": recipient_map.get("roles") or [],
                "actors": recipient_map.get("actors") or [],
            },
            path=f"{path}.recipients",
            require_addressee=False,
        )
        if not item_owners and not policy.gates:
            raise ValueError(
                f"{path}.recipients must name roles, actors, or item_owners"
            )
    elif recipients is not None:
        raise ValueError(f"{path}.recipients must be omitted when disabled")


def _validate_target(
    raw: Any,
    *,
    path: str,
    prior_stages: Mapping[str, Mapping[str, Any]],
    stage_kind: str,
) -> None:
    target = _mapping(raw, path=path)
    kind = target.get("kind")
    if kind not in TARGET_KINDS:
        raise ValueError(
            f"{path}.kind must be one of: {', '.join(sorted(TARGET_KINDS))}"
        )
    if kind == "persistent_environment":
        extra = set(target) - {"kind", "environment"}
        environment = target.get("environment")
        if extra:
            raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
        if not isinstance(environment, str) or not environment.strip():
            raise ValueError(f"{path}.environment must be a non-empty name")
        return

    extra = set(target) - {"kind", "capability", "source_stage"}
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    capability = target.get("capability")
    source_stage = target.get("source_stage")
    if bool(capability) == bool(source_stage):
        raise ValueError(f"{path} must name exactly one of capability or source_stage")
    if capability is not None and (
        not isinstance(capability, str) or not capability.strip()
    ):
        raise ValueError(f"{path}.capability must be a non-empty name")
    if source_stage is not None:
        if not isinstance(source_stage, str) or not source_stage.strip():
            raise ValueError(f"{path}.source_stage must be a non-empty name")
        if source_stage not in prior_stages:
            raise ValueError(
                f"{path}.source_stage must name an earlier stage, got {source_stage!r}"
            )
        source = prior_stages[source_stage]
        source_target = source.get("target")
        if (
            source.get("stage_kind") != STAGE_KIND_EXECUTION
            or not isinstance(source_target, Mapping)
            or source_target.get("kind") != "run_preview"
            or not source_target.get("capability")
        ):
            raise ValueError(
                f"{path}.source_stage must name an earlier preview-producing "
                "execution stage"
            )
    if stage_kind == STAGE_KIND_QA and source_stage is None:
        raise ValueError(f"{path} on a QA stage must consume an earlier run preview")


def validate_release_stage_policy(stages: list[dict[str, Any]]) -> int:
    """Validate advanced policy fields and return the required schema version."""
    seen: dict[str, Mapping[str, Any]] = {}
    required_version = LEGACY_DEFINITION_SCHEMA_VERSION
    for index, stage in enumerate(stages):
        name = str(stage.get("name") or "")
        if name in seen:
            raise ValueError(f"stage {index} duplicates stage name {name!r}")
        seen[name] = stage
        if not (
            _ADVANCED_STAGE_KEYS & set(stage)
            or stage.get("step_runner") == QA_STEP_RUNNER
        ):
            continue
        required_version = RELEASE_POLICY_SCHEMA_VERSION
        path = f"stage {index} ({name})"
        stage_kind = stage.get("stage_kind")
        if stage_kind not in STAGE_KINDS:
            raise ValueError(
                f"{path}.stage_kind must be one of: {', '.join(sorted(STAGE_KINDS))}"
            )
        if "target" in stage:
            _validate_target(
                stage["target"],
                path=f"{path}.target",
                prior_stages={key: value for key, value in seen.items() if key != name},
                stage_kind=str(stage_kind),
            )
        if stage_kind == STAGE_KIND_EXECUTION:
            if stage.get("step_runner") == QA_STEP_RUNNER:
                raise ValueError(f"{path} execution stage cannot use the QA runner")
            if stage.get("scope", "run") != "run":
                raise ValueError(f"{path}.scope must be run for execution stages")
            forbidden = {"cases", "verdict", "notification"} & set(stage)
            if forbidden:
                raise ValueError(
                    f"{path} execution stage has QA-only fields: {sorted(forbidden)}"
                )
            continue
        if stage.get("step_runner") != QA_STEP_RUNNER:
            raise ValueError(f"{path} QA stage must use step_runner={QA_STEP_RUNNER}")
        if stage.get("scope") not in QA_SCOPES:
            raise ValueError(
                f"{path}.scope must be one of: {', '.join(sorted(QA_SCOPES))}"
            )
        if "target" not in stage:
            raise ValueError(f"{path}.target is required for QA")
        if "cases" in stage:
            _validate_cases(stage["cases"], path=f"{path}.cases")
        if "verdict" not in stage:
            raise ValueError(f"{path}.verdict is required for QA")
        _validate_verdict(stage["verdict"], path=f"{path}.verdict")
        if "notification" in stage:
            _validate_notification(stage["notification"], path=f"{path}.notification")
    return required_version


def definition_schema_version(stages_json: str) -> int:
    stages = json.loads(stages_json)
    return validate_release_stage_policy(stages)


def validate_stage_references(
    conn: Any,
    *,
    project: str,
    stages_json: str,
) -> None:
    """Require every stage target and reusable QA plan to belong to the project."""
    stages = json.loads(stages_json)
    ident = resolve_project(conn, project)
    assert ident is not None
    from yoke_core.domain.environment_reference import resolve

    for index, stage in enumerate(stages):
        target = stage.get("target") if isinstance(stage, Mapping) else None
        if not isinstance(target, Mapping):
            continue
        kind = target.get("kind")
        if kind == "persistent_environment":
            environment = str(target.get("environment") or "")
            try:
                resolve(conn, project_id=ident.id, name=environment)
            except LookupError as exc:
                raise LookupError(
                    f"stage {index} target environment {environment!r} is not "
                    f"registered for project {project!r}"
                ) from exc
        elif kind == "run_preview":
            capability = target.get("capability")
            if not capability:
                # A source_stage reference chains to an earlier run_preview
                # stage, which was already validated on its own turn through
                # this loop; nothing further to resolve here.
                continue
            capability = str(capability)
            has_capability = query_scalar(
                conn,
                "SELECT COUNT(*) FROM project_capabilities "
                "WHERE project_id=%s AND type=%s",
                (ident.id, capability),
            )
            if not has_capability:
                raise LookupError(
                    f"stage {index} target capability {capability!r} is not "
                    f"registered for project {project!r}; register it with: "
                    f"yoke projects capability-settings merge --project {project} "
                    f"--cap-type {capability} --set <key>=<value>"
                )
    from yoke_core.domain.deployment_requirement_snapshots import (
        validate_flow_plan_references,
    )

    validate_flow_plan_references(conn, project_id=ident.id, stages=stages)


def require_supported_definition_schema(
    schema_version: int,
    *,
    operation: str,
) -> None:
    if int(schema_version) <= CURRENT_EXECUTION_SCHEMA_VERSION:
        return
    raise ValueError(
        f"{operation} requires deployment-flow schema {schema_version}, but this "
        f"serving runtime executes through schema {CURRENT_EXECUTION_SCHEMA_VERSION}; "
        "keep the definition disabled until the matching runtime is deployed"
    )


__all__ = [
    "CURRENT_EXECUTION_SCHEMA_VERSION",
    "LEGACY_DEFINITION_SCHEMA_VERSION",
    "QA_STEP_RUNNER",
    "RELEASE_POLICY_SCHEMA_VERSION",
    "definition_schema_version",
    "require_supported_definition_schema",
    "validate_release_stage_policy",
    "validate_stage_references",
]
