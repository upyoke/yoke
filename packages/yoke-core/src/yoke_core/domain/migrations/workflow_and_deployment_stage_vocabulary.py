"""Cut workflow and deployment stages over to their domain vocabulary."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.flow_validation import validate_stages
from yoke_core.domain.workflow_definition_codec import definition_digest


MIGRATION_NAME = "workflow_and_deployment_stage_vocabulary"
WORKFLOW_SCHEMA_VERSION = 3


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _object(raw: Any, *, subject: str) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{subject} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{subject} must be a JSON object")
    return value


def _array(raw: Any, *, subject: str) -> list[Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{subject} is not valid JSON") from exc
    if not isinstance(value, list):
        raise AssertionError(f"{subject} must be a JSON array")
    return value


def _rewrite_workflow(definition: dict[str, Any]) -> dict[str, Any]:
    rewritten = dict(definition)
    old_bindings = rewritten.pop("executor_bindings", None)
    if old_bindings is not None and "skill_bindings" in rewritten:
        raise AssertionError("workflow definition carries both binding vocabularies")
    bindings = old_bindings if old_bindings is not None else rewritten.get(
        "skill_bindings"
    )
    if not isinstance(bindings, list):
        raise AssertionError("workflow definition has no skill bindings")

    normalized: list[dict[str, Any]] = []
    for index, raw_binding in enumerate(bindings):
        if not isinstance(raw_binding, dict):
            raise AssertionError(f"workflow binding {index} is not an object")
        binding = dict(raw_binding)
        old_skill = binding.pop("executor_id", None)
        if old_skill is not None and "skill_id" in binding:
            raise AssertionError(
                f"workflow binding {index} carries both skill id vocabularies"
            )
        if old_skill is not None:
            binding["skill_id"] = old_skill
        if not str(binding.get("skill_id") or ""):
            raise AssertionError(f"workflow binding {index} has no skill id")
        normalized.append(binding)

    rewritten["skill_bindings"] = normalized
    schema_version = rewritten.get("schema_version")
    if schema_version == 2:
        rewritten["schema_version"] = WORKFLOW_SCHEMA_VERSION
    elif schema_version not in {1, WORKFLOW_SCHEMA_VERSION}:
        raise AssertionError(
            f"workflow definition has unsupported schema version {schema_version!r}"
        )
    return rewritten


def _rewrite_stages(stages: list[Any]) -> list[Any]:
    rewritten: list[Any] = []
    for index, raw_stage in enumerate(stages):
        if not isinstance(raw_stage, dict):
            raise AssertionError(f"deployment stage {index} is not an object")
        stage = dict(raw_stage)
        old_runner = stage.pop("executor", None)
        if old_runner is not None and "step_runner" in stage:
            raise AssertionError(
                f"deployment stage {index} carries both runner vocabularies"
            )
        if old_runner is not None:
            stage["step_runner"] = old_runner
        rewritten.append(stage)
    validate_stages(json_helper.dumps_compact(rewritten))
    return rewritten


def apply(conn: Any) -> None:
    """Rewrite storage keys without changing stage behavior or row identity."""
    marker = _marker(conn)
    workflow_rows = conn.execute(
        "SELECT id, definition_json FROM workflow_versions ORDER BY id"
    ).fetchall()
    for row in workflow_rows:
        definition = _rewrite_workflow(
            _object(row[1], subject=f"workflow version {row[0]}")
        )
        conn.execute(
            "UPDATE workflow_versions SET definition_json="
            f"{marker}, definition_digest={marker} WHERE id={marker}",
            (
                json_helper.dumps_compact(definition),
                definition_digest(definition),
                row[0],
            ),
        )

    flow_rows = conn.execute(
        "SELECT id, stages FROM deployment_flows ORDER BY id"
    ).fetchall()
    for row in flow_rows:
        stages = _rewrite_stages(
            _array(row[1], subject=f"deployment flow {row[0]}")
        )
        conn.execute(
            f"UPDATE deployment_flows SET stages={marker} WHERE id={marker}",
            (json_helper.dumps_compact(stages), row[0]),
        )


def invariants(conn: Any) -> None:
    """Prove all live definitions use only the new vocabulary."""
    for row in conn.execute(
        "SELECT id, definition_json, definition_digest "
        "FROM workflow_versions ORDER BY id"
    ).fetchall():
        definition = _object(row[1], subject=f"workflow version {row[0]}")
        if definition.get("schema_version") not in {1, WORKFLOW_SCHEMA_VERSION}:
            raise AssertionError(
                f"workflow version {row[0]} has stale schema version"
            )
        if "executor_bindings" in definition:
            raise AssertionError(
                f"workflow version {row[0]} retains executor_bindings"
            )
        bindings = definition.get("skill_bindings")
        if not isinstance(bindings, list):
            raise AssertionError(f"workflow version {row[0]} has no skill bindings")
        for binding in bindings:
            if "executor_id" in binding or not str(binding.get("skill_id") or ""):
                raise AssertionError(
                    f"workflow version {row[0]} has stale skill binding vocabulary"
                )
        if definition_digest(definition) != str(row[2]):
            raise AssertionError(f"workflow version {row[0]} digest is stale")

    for row in conn.execute(
        "SELECT id, stages FROM deployment_flows ORDER BY id"
    ).fetchall():
        stages = _array(row[1], subject=f"deployment flow {row[0]}")
        validate_stages(json_helper.dumps_compact(stages))
        for stage in stages:
            if "executor" in stage:
                raise AssertionError(
                    f"deployment flow {row[0]} retains executor stage vocabulary"
                )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
