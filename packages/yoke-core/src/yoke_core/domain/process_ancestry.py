"""Portable process-ancestry walk — re-exported from the shared contract.

The implementation lives in :mod:`yoke_contracts.process_ancestry` so the
product CLI client (which depends only on ``yoke-contracts``) and the
engine core resolve ambient identity through one body. This shim
preserves the ``yoke_core.domain.process_ancestry`` import surface for
in-tree callers and tests.
"""

from __future__ import annotations

from yoke_contracts.process_ancestry import (
    HARNESS_PROCESS_BASENAMES,
    ProcessAnchor,
    ancestor_pids,
    find_nearest_harness_anchor,
    is_harness_process_name,
    parent_map,
    process_command_name,
    process_start_time,
)

__all__ = [
    "HARNESS_PROCESS_BASENAMES",
    "ProcessAnchor",
    "ancestor_pids",
    "find_nearest_harness_anchor",
    "is_harness_process_name",
    "parent_map",
    "process_command_name",
    "process_start_time",
]
