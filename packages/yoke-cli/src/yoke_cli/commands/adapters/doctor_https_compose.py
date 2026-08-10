"""CLI facade for https doctor local+relay compose helpers.

The compose implementation lives in
:mod:`yoke_core.engines.doctor_https_compose` and
:mod:`yoke_core.engines.doctor_https_only` so the engine owns the
checkout-local HC execution. This module loads them dynamically — client
packages must not take a static ``yoke_core`` import.
"""

from __future__ import annotations

import importlib

_compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
_only = importlib.import_module("yoke_core.engines.doctor_https_only")

caller_project_local_slugs = _only.caller_project_local_slugs
checkout_root_for_project = _compose.checkout_root_for_project
false_na_source_slugs = _compose.false_na_source_slugs
https_relay_needed = _only.https_relay_needed
local_project_only_result = _only.local_project_only_result
machine_has_checkout_for = _compose.machine_has_checkout_for
merge_relayed_with_local = _compose.merge_relayed_with_local
partition_only_slugs = _only.partition_only_slugs
prepare_https_only_payload = _only.prepare_https_only_payload
recount = _compose.recount
resolve_operator_project = _compose.resolve_operator_project
run_local_project_checks = _only.run_local_project_checks
run_local_source_checks = _compose.run_local_source_checks

__all__ = [
    "caller_project_local_slugs",
    "checkout_root_for_project",
    "false_na_source_slugs",
    "https_relay_needed",
    "local_project_only_result",
    "machine_has_checkout_for",
    "merge_relayed_with_local",
    "partition_only_slugs",
    "prepare_https_only_payload",
    "recount",
    "resolve_operator_project",
    "run_local_project_checks",
    "run_local_source_checks",
]
