"""Adapter inventory rows for the sourced model-reference family."""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

MODELS_ADAPTERS: List[AdapterEntry] = [
    _read_entry(
        function_id="models.lookup.run",
        cli_invocation="yoke models lookup MODEL_ID [--json]",
        notes="Launch --model lookup; researched=false is unknown, never a gate.",
    ),
    _read_entry(
        function_id="models.get.run",
        cli_invocation="yoke models get [--model-id MODEL_ID] [--json]",
        notes="Published catalog revision, or one lookup when --model-id is passed.",
    ),
    _read_entry(
        function_id="models.validate.run",
        cli_invocation="yoke models validate --stdin [--json]",
        notes="Validate one proposed record JSON object before publication.",
    ),
    _read_entry(
        function_id="models.diff.run",
        cli_invocation="yoke models diff --stdin [--json]",
        notes="Validate and compare a complete candidate against the latest revision.",
    ),
    _read_entry(
        function_id="models.level_proposal.run",
        cli_invocation="yoke models level-proposal [--stdin] [--levels-only] [--json]",
        notes="Propose level changes from the catalog; approval stores the levels.",
    ),
    _read_entry(
        function_id="models.revisions.run",
        cli_invocation="yoke models revisions [--json]",
        notes="List immutable effective-dated catalog revisions.",
    ),
    _read_entry(
        function_id="models.publish.run",
        cli_invocation="yoke models publish --stdin --expected-base REV --source-note TEXT",
        notes="Publish a sourced complete revision; org admin required.",
    ),
    _read_entry(
        function_id="models.restore.run",
        cli_invocation="yoke models restore REV --expected-base REV --source-note TEXT",
        notes="Copy an older catalog into a new revision; org admin required.",
    ),
    _read_entry(
        function_id="universe.levels.get",
        cli_invocation="yoke universe levels get",
        notes="Read the universe execution levels, lowest first, and whether they are stored or the shipped default.",
    ),
    _read_entry(
        function_id="universe.level_capacity.get",
        cli_invocation="yoke universe level-capacity get",
        notes="Read what each level can launch now: per option its pools, standing and blocking pool, and where the next launch goes; plus each project's override.",
    ),
    _read_entry(
        function_id="universe.levels.set",
        cli_invocation="yoke universe levels set --stdin",
        notes="Replace the universe execution levels; each option is validated against what its surface accepts. Org admin required.",
    ),
]

__all__ = ["MODELS_ADAPTERS"]
