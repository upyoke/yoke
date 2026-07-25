"""Runtime interpretation of an item's pinned workflow version."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    definition_digest,
)
from yoke_core.domain.workflow_definition_builders import (
    IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS,
)

ENGINE_TERMINAL_STAGE_IDS = frozenset({"cancelled", "stopped"})
ENGINE_WAIT_STAGE_IDS = frozenset({"blocked", "failed"})
ENGINE_EXCEPTIONAL_STAGE_IDS = (
    ENGINE_TERMINAL_STAGE_IDS | ENGINE_WAIT_STAGE_IDS
)


@dataclass(frozen=True)
class WorkflowRuntime:
    """One immutable workflow version interpreted for execution."""

    workflow_id: str
    workflow_version_id: int
    version: int
    definition_digest: str
    definition: Mapping[str, Any]

    @property
    def stages(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.definition["stages"])

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(str(stage["id"]) for stage in self.stages)

    @property
    def terminal_stage_ids(self) -> frozenset[str]:
        return frozenset(
            str(value) for value in self.definition["terminal_stage_ids"]
        )

    @property
    def policies(self) -> Mapping[str, Any]:
        return self.definition["policies"]

    def stage(self, stage_id: str) -> Optional[Mapping[str, Any]]:
        return next(
            (
                stage
                for stage in self.stages
                if str(stage["id"]) == stage_id
            ),
            None,
        )

    def stage_index(self, stage_id: str) -> Optional[int]:
        try:
            return self.stage_ids.index(stage_id)
        except ValueError:
            return None

    def next_stage_id(self, stage_id: str) -> Optional[str]:
        position = self.stage_index(stage_id)
        if position is None or position + 1 >= len(self.stage_ids):
            return None
        return self.stage_ids[position + 1]

    def accepts_stage(self, stage_id: str) -> bool:
        return (
            stage_id in self.stage_ids
            or stage_id in ENGINE_EXCEPTIONAL_STAGE_IDS
        )

    def is_forward_transition(
        self,
        from_stage_id: str,
        to_stage_id: str,
    ) -> bool:
        before = self.stage_index(from_stage_id)
        after = self.stage_index(to_stage_id)
        return before is not None and after is not None and after > before

    def has_reached_stage(
        self,
        current_stage_id: str,
        target_stage_id: str,
    ) -> bool:
        """Whether the current ordered stage is at or beyond a target."""
        current = self.stage_index(current_stage_id)
        target = self.stage_index(target_stage_id)
        return (
            current is not None
            and target is not None
            and current >= target
        )

    def gates_for_stage(
        self,
        stage_id: str,
    ) -> tuple[Mapping[str, Any], ...]:
        stage = self.stage(stage_id)
        if stage is None:
            return ()
        return tuple(stage["gates"])

    def gate_ids_for_stage(self, stage_id: Optional[str]) -> frozenset[str]:
        if stage_id is None:
            return frozenset()
        return frozenset(
            str(gate["id"]) for gate in self.gates_for_stage(stage_id)
        )

    def executor_for_stage(self, stage_id: str) -> Optional[str]:
        position = self.stage_index(stage_id)
        if position is None or stage_id in self.terminal_stage_ids:
            return None
        for binding in self.definition["executor_bindings"]:
            start = self.stage_index(str(binding["from_stage_id"]))
            stop = self.stage_index(str(binding["through_stage_id"]))
            if (
                start is not None
                and stop is not None
                and start <= position < stop
            ):
                return str(binding["executor_id"])
        raise WorkflowRegistryError(
            f"workflow {self.workflow_id}@{self.version} has no executor "
            f"for stage {stage_id!r}"
        )

    def executor_has_started(
        self,
        stage_id: str,
        executor_ids: frozenset[str],
    ) -> bool:
        """Whether the current stage is inside, not at the entry to, a binding."""
        position = self.stage_index(stage_id)
        if position is None:
            return False
        for binding in self.definition["executor_bindings"]:
            if str(binding["executor_id"]) not in executor_ids:
                continue
            start = self.stage_index(str(binding["from_stage_id"]))
            stop = self.stage_index(str(binding["through_stage_id"]))
            if (
                start is not None
                and stop is not None
                and start < position < stop
            ):
                return True
        return False

    def implementation_has_started(self, stage_id: str) -> bool:
        """Whether an implementation executor has begun its bound segment."""
        return self.executor_has_started(
            stage_id,
            IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS,
        )

    def is_before_implementation(self, stage_id: str) -> bool:
        """Whether a definition stage precedes its implementation segment."""
        position = self.stage_index(stage_id)
        if position is None:
            return False
        starts = []
        for binding in self.definition["executor_bindings"]:
            if (
                str(binding["executor_id"])
                not in IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS
            ):
                continue
            start = self.stage_index(str(binding["from_stage_id"]))
            if start is not None:
                starts.append(start)
        return bool(starts) and position <= min(starts)

    def allows_completed_claim_release(self, stage_id: str) -> bool:
        """Whether a stage is a definition-owned successful handoff."""
        if stage_id in self.terminal_stage_ids:
            return True
        through_stages = {
            str(binding["through_stage_id"])
            for binding in self.definition["executor_bindings"]
        }
        if stage_id in through_stages:
            return True
        position = self.stage_index(stage_id)
        return (
            self.policies["delivery"] == "release_stage"
            and position is not None
            and position == len(self.stage_ids) - 2
        )

    def requires_item_path_claim_probe(self, stage_id: str) -> bool:
        """Whether leaving *stage_id* activates an item-level path claim."""
        from yoke_core.domain.workflow_gate_catalog import (
            GATE_CLAIM_ACTIVATION,
        )

        return (
            self.policies["path_claims"] == "required"
            and GATE_CLAIM_ACTIVATION
            in self.gate_ids_for_stage(self.next_stage_id(stage_id))
        )

    def allows_entry_surface(self, entry_surface: str) -> bool:
        return entry_surface in self.definition["entry_surfaces"]


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _runtime_from_row(row: Any) -> WorkflowRuntime:
    values = dict(row)
    raw_definition = values["definition_json"]
    try:
        definition = json.loads(str(raw_definition))
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkflowRegistryError(
            "stored workflow definition is not valid JSON"
        ) from exc
    if not isinstance(definition, dict):
        raise WorkflowRegistryError(
            "stored workflow definition is not an object"
        )
    stored_digest = str(values["definition_digest"])
    if definition_digest(definition) != stored_digest:
        raise WorkflowRegistryError(
            f"workflow version {values['workflow_id']}@{values['version']} "
            "does not match its immutable digest"
        )
    return WorkflowRuntime(
        workflow_id=str(values["workflow_id"]),
        workflow_version_id=int(values["workflow_version_id"]),
        version=int(values["version"]),
        definition_digest=stored_digest,
        definition=definition,
    )


def workflow_runtime_from_row(row: Any) -> WorkflowRuntime:
    """Interpret a joined workflow-version row without another DB query."""
    return _runtime_from_row(row)


def load_workflow_runtime(
    conn: Any,
    *,
    workflow_id: str,
    workflow_version_id: int,
) -> WorkflowRuntime:
    """Load and verify one explicitly pinned workflow version."""
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT v.id AS workflow_version_id, v.workflow_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM workflow_versions v "
        f"WHERE v.id = {placeholder} AND v.workflow_id = {placeholder}",
        (workflow_version_id, workflow_id),
    ).fetchone()
    if row is None:
        raise WorkflowRegistryError(
            f"unknown workflow pin {workflow_id}@version-id:{workflow_version_id}"
        )
    return _runtime_from_row(row)


def builtin_workflow_runtime(workflow_id: str) -> WorkflowRuntime:
    """Build a non-persistent runtime for pure domain tests and tooling."""
    fixture = builtin_workflow_definition(workflow_id)
    definition = fixture["definition"]
    return WorkflowRuntime(
        workflow_id=workflow_id,
        workflow_version_id=0,
        version=int(fixture["version"]),
        definition_digest=definition_digest(definition),
        definition=definition,
    )


def load_item_workflow_runtime(
    conn: Any,
    item_id: int,
) -> WorkflowRuntime:
    """Load and verify the immutable workflow version pinned by an item."""
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT i.workflow_id, i.workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"WHERE i.id = {placeholder}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise WorkflowRegistryError(f"item {item_id} does not exist")
    values = dict(row)
    if (
        values.get("workflow_id") is None
        or values.get("workflow_version_id") is None
        or values.get("version") is None
    ):
        raise WorkflowRegistryError(
            f"item {item_id} has no complete workflow-version pin"
        )
    return _runtime_from_row(row)


__all__ = [
    "ENGINE_EXCEPTIONAL_STAGE_IDS",
    "ENGINE_TERMINAL_STAGE_IDS",
    "ENGINE_WAIT_STAGE_IDS",
    "WorkflowRuntime",
    "builtin_workflow_runtime",
    "load_item_workflow_runtime",
    "load_workflow_runtime",
    "workflow_runtime_from_row",
]
