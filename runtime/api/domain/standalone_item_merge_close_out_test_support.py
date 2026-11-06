# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace as SimpleNamespace

from yoke_core.domain import standalone_item_merge as sim

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)

from yoke_core.domain import standalone_item_merge_release_status as release_status

from yoke_core.domain import standalone_item_merge_evidence as merge_evidence

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge_recovery as recovery

from yoke_core.domain import standalone_item_merge_terminal as terminal

from yoke_core.domain import standalone_item_merge_verify as verify

from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

LANE_SHA = "1" * 40
