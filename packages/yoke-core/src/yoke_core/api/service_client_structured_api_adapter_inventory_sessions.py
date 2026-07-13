"""Session and charge adapter inventory rows."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


SESSION_ADAPTERS = [
    AdapterEntry(
        function_id="sessions.begin",
        cli_invocation=(
            "yoke sessions begin --executor E --provider P --model M "
            "--workspace W"
        ),
    ),
    AdapterEntry(
        function_id="sessions.touch",
        cli_invocation="yoke sessions touch [--mode MODE]",
    ),
    AdapterEntry(
        function_id="sessions.checkpoint",
        cli_invocation=(
            "yoke sessions checkpoint --step N --action ACTION "
            "--chainable BOOL"
        ),
    ),
    _read_entry(
        function_id="sessions.checkpoint_read",
        cli_invocation="yoke sessions checkpoint-read",
    ),
    AdapterEntry(
        function_id="sessions.offer",
        cli_invocation=(
            "yoke sessions offer --executor E --provider P --workspace W"
        ),
    ),
    _read_entry(
        function_id="sessions.ownership_guard",
        cli_invocation="yoke sessions ownership-guard --item YOK-N",
    ),
    AdapterEntry(
        function_id="charge.schedule",
        cli_invocation="yoke charge schedule [--project P] [--wip-cap N]",
    ),
]


__all__ = ["SESSION_ADAPTERS"]
