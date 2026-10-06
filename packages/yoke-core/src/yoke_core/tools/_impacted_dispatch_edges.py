"""Function-registry dispatch edges for impacted selection.

A caller that reaches a handler through the function registry names only
the function id — ``dispatch("deployment_runs.create", ...)``, a CLI
adapter keyed on it — and imports nothing of the handler. The import graph
does reach every handler, but only through the module that registers all of
them, which every dispatching module imports; that path is near-total, so a
bounded run drops it and with it the very tests that call the changed
handler.

This module models the dispatch edge directly: the caller walks importers
up from the changed modules without crossing the registration hub, and the
files naming the reached handlers' function ids are selected. The function-id -> handler map is read from the live registry, the one
authority on which ids exist, so registration shape (loops, entry tables,
helper registrars) never hides an edge.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

#: Module whose ``register_all_handlers`` wires every handler. Its imports
#: are the near-total fan-out this module routes around.
DISPATCH_HUB_MODULE = "yoke_core.domain.handlers.__init_register__"
_RECOVERY = f"yoke dev import-check {DISPATCH_HUB_MODULE}"


@dataclass(frozen=True)
class DispatchMap:
    """Function ids per handler module, or why the registry could not load."""

    function_ids: Mapping[str, frozenset[str]] = field(default_factory=dict)
    error: str = ""


def load_dispatch_map(indexed_modules: Iterable[str]) -> DispatchMap:
    """Read the live registry when the indexed tree carries the dispatcher.

    A tree without the registration hub (any project but Yoke's own source)
    has no dispatch edges to model. A hub that fails to import is reported,
    not skipped: the caller widens rather than trusting a selection that
    silently lost every dispatch edge.
    """
    if DISPATCH_HUB_MODULE not in set(indexed_modules):
        return DispatchMap()
    try:
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import list_entries

        register_all_handlers()
        entries = list_entries()
    except Exception as exc:  # noqa: BLE001 — any import failure is the verdict
        return DispatchMap(
            error=(
                f"the function registry failed to load ({type(exc).__name__}: "
                f"{exc}); dispatch edges cannot be modeled. Fix the import "
                f"error, then re-run — `{_RECOVERY}` names the failing module"
            )
        )
    by_module: dict[str, set[str]] = {}
    for entry in entries:
        handler_module = getattr(inspect.unwrap(entry.handler), "__module__", "")
        for module in {handler_module, entry.owner_module}:
            if module:
                by_module.setdefault(module, set()).add(entry.function_id)
    return DispatchMap(
        function_ids={module: frozenset(ids) for module, ids in by_module.items()}
    )


def function_ids_for(modules: Iterable[str], dispatch: DispatchMap) -> frozenset[str]:
    """Function ids registered to any of *modules*."""
    return frozenset(
        function_id
        for module in modules
        for function_id in dispatch.function_ids.get(module, ())
    )


def dispatch_caller_files(
    function_ids: Iterable[str],
    importers: Mapping[str, set[str]],
) -> frozenset[str]:
    """Files naming any of *function_ids* as a string literal.

    The import index already records every dotted string literal as a
    reference key, so a function id's callers are its reverse-index entry.
    """
    return frozenset(
        caller
        for function_id in function_ids
        for caller in importers.get(function_id, ())
    )


__all__ = [
    "DISPATCH_HUB_MODULE",
    "DispatchMap",
    "dispatch_caller_files",
    "function_ids_for",
    "load_dispatch_map",
]
