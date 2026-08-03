"""Stage rows within immutable workflow definitions."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from yoke_core.domain.workflow_definition_validation_support import (
    WorkflowDefinitionError,
    require_exact_keys,
    require_mapping,
    require_nonempty_text,
    require_sequence,
)
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog

_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_STAGE_KEYS = frozenset(
    {"id", "label", "glyph", "board_bucket", "description", "gates"}
)
_GATE_REF_KEYS = frozenset({"id", "mode"})


def validate_stages(definition: Mapping[str, Any]) -> tuple[list[str], set[str]]:
    stages = require_sequence(definition.get("stages"), "stages")
    if len(stages) < 2:
        raise WorkflowDefinitionError("stages must contain at least two rows")
    ids: list[str] = []
    labels: list[str] = []
    catalog = {row["id"]: row for row in workflow_gate_catalog()}
    gate_pairs: set[tuple[str, Optional[str]]] = set()
    for index, raw_stage in enumerate(stages):
        path = f"stages[{index}]"
        stage = require_mapping(raw_stage, path)
        require_exact_keys(stage, _STAGE_KEYS, path)
        stage_id = require_nonempty_text(stage.get("id"), f"{path}.id")
        if not _ID_RE.fullmatch(stage_id):
            raise WorkflowDefinitionError(f"{path}.id must use lowercase kebab-case")
        ids.append(stage_id)
        labels.append(require_nonempty_text(stage.get("label"), f"{path}.label"))
        if "glyph" in stage:
            require_nonempty_text(stage.get("glyph"), f"{path}.glyph")
        if "board_bucket" in stage:
            bucket = require_nonempty_text(
                stage.get("board_bucket"), f"{path}.board_bucket"
            )
            if bucket not in {
                "idea",
                "planning",
                "refined",
                "implementing",
                "reviewing",
                "implemented",
                "release",
                "done",
                "unknown",
            }:
                raise WorkflowDefinitionError(f"{path}.board_bucket is invalid")
        if "description" in stage:
            require_nonempty_text(stage["description"], f"{path}.description")
        for gate_index, raw_gate in enumerate(
            require_sequence(stage.get("gates"), f"{path}.gates")
        ):
            gate_path = f"{path}.gates[{gate_index}]"
            gate = require_mapping(raw_gate, gate_path)
            require_exact_keys(gate, _GATE_REF_KEYS, gate_path)
            gate_id = require_nonempty_text(gate.get("id"), f"{gate_path}.id")
            catalog_row = catalog.get(gate_id)
            if catalog_row is None:
                raise WorkflowDefinitionError(
                    f"{gate_path}.id references unknown gate {gate_id!r}"
                )
            mode = gate.get("mode")
            valid_modes = {row["id"] for row in catalog_row["modes"]}
            if valid_modes:
                mode = require_nonempty_text(mode, f"{gate_path}.mode")
                if mode not in valid_modes:
                    raise WorkflowDefinitionError(
                        f"{gate_path}.mode references unknown mode {mode!r}"
                    )
            elif mode is not None:
                raise WorkflowDefinitionError(
                    f"{gate_path}.mode is not supported by gate {gate_id!r}"
                )
            pair = (gate_id, mode)
            if pair in gate_pairs:
                raise WorkflowDefinitionError(
                    f"{path}.gates repeats {gate_id!r} mode {mode!r}"
                )
            gate_pairs.add(pair)
        gate_pairs.clear()
    if len(ids) != len(set(ids)):
        raise WorkflowDefinitionError("stage ids must be unique")
    if len(labels) != len({label.casefold() for label in labels}):
        raise WorkflowDefinitionError("stage labels must be unique")
    return ids, set(ids)


__all__ = ["validate_stages"]
