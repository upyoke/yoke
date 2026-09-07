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
        notes="Seeded catalog, or one lookup when --model-id is passed.",
    ),
    _read_entry(
        function_id="models.validate.run",
        cli_invocation="yoke models validate --stdin [--json]",
        notes="Validate one proposed record JSON object before editing the seed.",
    ),
]

__all__ = ["MODELS_ADAPTERS"]
