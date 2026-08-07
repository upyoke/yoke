"""CLI facade for https doctor local+relay compose helpers.

The compose implementation lives in
:mod:`yoke_core.engines.doctor_https_compose` so the engine owns the
checkout-local HC execution. This module loads it dynamically — client
packages must not take a static ``yoke_core`` import.
"""

from __future__ import annotations

import importlib

_mod = importlib.import_module("yoke_core.engines.doctor_https_compose")

false_na_source_slugs = _mod.false_na_source_slugs
machine_has_checkout_for = _mod.machine_has_checkout_for
merge_relayed_with_local = _mod.merge_relayed_with_local
recount = _mod.recount
resolve_operator_project = _mod.resolve_operator_project
run_local_source_checks = _mod.run_local_source_checks

__all__ = [
    "false_na_source_slugs",
    "machine_has_checkout_for",
    "merge_relayed_with_local",
    "recount",
    "resolve_operator_project",
    "run_local_source_checks",
]
