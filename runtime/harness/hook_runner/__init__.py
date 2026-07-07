"""Shared Yoke hook runner package.

This task creates the foundational dataclasses every
subsequent task in the epic depends on. Chain logic, registries, and the
`main()` entrypoint land in later tasks.
"""

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
