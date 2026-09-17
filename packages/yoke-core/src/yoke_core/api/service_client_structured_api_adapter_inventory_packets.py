"""Adapter inventory rows for the packet and agent-render families.

Split out of :mod:`service_client_structured_api_adapter_inventory` (350-cap
split) so the packet-rendering surfaces have one home. Every row here backs
a handler that runs where the checkout lives rather than relaying, because
each one renders or measures the packets this build produces.
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

PACKET_ADAPTERS: List[AdapterEntry] = [
    AdapterEntry(
        function_id="packets.render.run",
        cli_invocation=("python3 -m yoke_core.domain.schema_api_context render"),
    ),
    _read_entry(
        function_id="packets.check.run",
        cli_invocation=("python3 -m yoke_core.domain.schema_api_context check"),
    ),
    _read_entry(
        function_id="packets.budget.get",
        cli_invocation="yoke packets budget get [--json]",
        notes=(
            "Packet line budget, current usage, and headroom per role plus "
            "the aggregate. Named by the budget-exceeded messages so the "
            "discovery path from a failed cap is one command."
        ),
    ),
    _read_entry(
        function_id="packets.startup_delivery.get",
        cli_invocation=(
            "yoke packets startup-delivery get [--target-root PATH] [--json]"
        ),
        notes=(
            "Per harness, the combined instruction payload each startup "
            "channel delivers, its budget, its headroom, and the contributing "
            "files. Answers what a per-packet budget cannot: whether the text "
            "a surface is handed fits the channel carrying it."
        ),
    ),
    AdapterEntry(
        function_id="agents.render.run",
        cli_invocation="python3 -m yoke_core.domain.agents_render render",
    ),
    _read_entry(
        function_id="agents.render.check",
        cli_invocation="python3 -m yoke_core.domain.agents_render check",
    ),
]

__all__ = ["PACKET_ADAPTERS"]
