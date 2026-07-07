"""Compatibility shim for the product-owned hook relay."""

from yoke_harness.hooks.relay import (
    HOOKS_EVALUATE_PATH,
    degrade_to_noop,
    detect_executor,
    evaluate_hook_event,
    evaluate_local_subset,
    merge_allow_stdout,
    relay_hook_event,
)

__all__ = [
    "HOOKS_EVALUATE_PATH",
    "degrade_to_noop",
    "detect_executor",
    "evaluate_hook_event",
    "evaluate_local_subset",
    "merge_allow_stdout",
    "relay_hook_event",
]
