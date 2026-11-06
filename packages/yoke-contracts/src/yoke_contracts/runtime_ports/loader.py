"""Resolve installed implementations of the runtime interfaces.

Adapters publish standard Python entry points. Domain code names an interface,
never an implementation package; successful resolutions retain module identity.
"""

from __future__ import annotations

from functools import cache
from importlib.metadata import entry_points
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

PORT_GROUP = "yoke.runtime"
RECOVERY = (
    "Install matching Yoke packages through the official installer, then retry. "
    "For a source checkout, sync its locked environment before running again."
)


class RuntimeAdapterUnavailable(RuntimeError):
    """The installed runtime cannot supply a declared interface."""


@cache
def _installed_ports() -> tuple[Any, ...]:
    return tuple(entry_points(group=PORT_GROUP))


def _unavailable(name: str, detail: str) -> RuntimeAdapterUnavailable:
    return RuntimeAdapterUnavailable(
        compose_refusal(
            f"runtime_adapter_unavailable: {name}: {detail}", recovery=RECOVERY
        )
    )


@cache
def load_port(name: str, interface: type[Any]) -> Any:
    """Require exactly one implementation with every declared interface member."""
    matches = [entry for entry in _installed_ports() if entry.name == name]
    if len(matches) != 1:
        raise _unavailable(name, f"expected one implementation; found {len(matches)}")
    try:
        implementation = matches[0].load()
    except Exception as exc:
        raise _unavailable(name, f"implementation could not load ({type(exc).__name__})") from exc
    missing = sorted(
        member
        for member in interface.__annotations__
        if not hasattr(implementation, member)
    )
    if missing:
        raise _unavailable(name, "implementation is missing " + ", ".join(missing))
    return implementation
