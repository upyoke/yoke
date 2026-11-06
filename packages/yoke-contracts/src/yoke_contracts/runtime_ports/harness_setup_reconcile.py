"""Runtime interface for harness setup reconcile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HarnessSetupReconcile(Protocol):
    """Operations and values supplied by the executing adapter."""

    Callable: Any
    FAILURES: Any
    HARNESS_MACHINE_HOOKS: Any
    HarnessSetupResult: type[Any]
    HarnessSetupRow: type[Any]
    Path: Any
    RECOVERY: Any
    Sequence: Any
    all_registered_checkouts: Any
    asdict: Any
    claude_state_path: Any
    configure_harness_unattended_posture: Any
    cursor_trust_file: Any
    dataclass: Any
    ensure_global_skill: Any
    ensure_machine_hooks: Any
    global_skill_ready: Any
    grant_folder_trust: Any
    inspect_harness_setup: Callable[..., Any]
    inspect_hook_file_trust: Any
    inspect_hook_trust: Any
    inspect_machine_hooks: Any
    io: Any
    json: Any
    main_checkout: Any
    mint_installed_checkout_trust: Any
    mirror_hook_trust: Any
    posture: Any
    posture_findings: Any
    reconcile_harness_setup: Callable[..., Any]
    registered_worktree_paths: Any
    retrust_recovery: Any
    tomllib: Any


def get_harness_setup_reconcile() -> HarnessSetupReconcile:
    return cast(HarnessSetupReconcile, load_port("harness_setup_reconcile", HarnessSetupReconcile))
