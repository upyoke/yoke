"""Shared hook-runner records and adapter capability vocabulary."""

from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)

__all__ = [
    "AdapterCapability",
    "HookContext",
    "HookDecision",
    "Next",
    "Outcome",
]
