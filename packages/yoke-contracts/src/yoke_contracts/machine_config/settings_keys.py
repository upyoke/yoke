"""Recognized machine-local setting keys and defaults.

``~/.yoke/config.json`` under ``settings`` owns machine-local runtime
tunables: timeouts, retry budgets, guardrail modes, and per-machine
thresholds. This module is one source of truth for each key's source
default and one-line meaning — the machine-local sibling of
:mod:`yoke_contracts.project_contract.project_keys`.

Two DB capability rows own everything else. ``project-policy`` owns shared
project behavior; ``session-routing`` owns lane and offer routing. A machine
settings key naming one of those concerns is a dead twin: every live reader
resolves those from the DB, so editing the machine copy silently changes
nothing. :func:`db_owned_capability_for` names the real authority so callers
can point an operator at the surface that decides.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Tuple

from yoke_contracts.project_contract.project_keys import (
    DB_PROJECT_POLICY_KEYS,
    LOCAL_PROJECT_KEYS,
    PROJECT_POLICY_CAPABILITY,
    RECOGNIZED_PROJECT_KEYS,
    SESSION_ROUTING_CAPABILITY,
)

SESSION_STALE_TTL_WITH_HOLDINGS_KEY = "session_stale_ttl_with_holdings_minutes"

# Machine-owned keys: (source default, one-line meaning). The default is the
# value the reader falls back to when the key is absent, so an unset key and a
# key set to its default behave identically.
MACHINE_SETTING_KEYS: Dict[str, Tuple[str, str]] = {
    "max_active_worktrees": (
        "5",
        "linked worktrees allowed before creation preflight refuses",
    ),
    "max_chain_steps": (
        "3",
        "autonomous chain steps allowed before a session checkpoints",
    ),
    "session_stale_ttl_minutes": (
        "20",
        "idle minutes before the stale-session sweep reclaims a session "
        "with no active holdings",
    ),
    SESSION_STALE_TTL_WITH_HOLDINGS_KEY: (
        "1440",
        "idle minutes before the stale-session sweep reclaims a session "
        "with active holdings",
    ),
    "session_reactivation_reacquire_window_s": (
        "300",
        "seconds a released claim stays auto-reacquirable on reactivation",
    ),
    "session_timing_enabled": (
        "false",
        "record per-session timing samples",
    ),
    "session_timing_retain_days": (
        "30",
        "days of session timing samples retained before pruning",
    ),
    "lint_session_cwd_status_mode": (
        "deny",
        "warn or deny for the pre-implementation session-cwd guardrail",
    ),
    "path_claim_activation_db_lock_retry_initial_ms": (
        "100",
        "first backoff before retrying a lock-contended claim activation",
    ),
    "path_claim_activation_db_lock_retry_max_attempts": (
        "3",
        "attempts allowed for a lock-contended claim activation",
    ),
    "coordination_context_spec_truncation_bytes": (
        "4096",
        "spec bytes carried into a coordination decision before truncation",
    ),
    "hook_runner_module_timeout_ms": (
        "10000",
        "per-module budget inside one hook evaluation",
    ),
    "hook_runner_total_timeout_ms": (
        "10000",
        "total harness-wait budget for one hook evaluation",
    ),
    "hook_session_end_cleanup_timeout_ms": (
        "2500",
        "DB busy-wait budget for session-end cleanup during the hook",
    ),
    "monitor_relay_hint_text": (
        "",
        "override text for the relay-only reminder; empty uses the built-in",
    ),
    "watcher_progress_percent_step": (
        "5",
        "percent delta a watcher requires before carrying a progress tick",
    ),
    "test_timeout": (
        "300",
        "seconds one project test command may run during merge",
    ),
    "git_command_timeout": (
        "120",
        "seconds one merge-path git command may run",
    ),
    "post_merge_rebase_timeout": (
        "120",
        "seconds the post-merge local-sync rebase may run",
    ),
    "ci_poll_interval": (
        "30",
        "seconds between CI check-run polls while waiting on a merge",
    ),
    "ci_registration_timeout": (
        "120",
        "seconds to wait for CI check-runs to register on a head commit",
    ),
    "ci_timeout": (
        "1800",
        "seconds to wait for CI to conclude before the merge gives up",
    ),
    "standalone_post_push_ci_discovery_timeout": (
        "90",
        "seconds to discover checks after a queue-less standalone push",
    ),
    "standalone_post_push_ci_timeout": (
        "900",
        "seconds to wait for queue-less standalone push checks to conclude",
    ),
    "merge_lock_ttl_minutes": (
        "30",
        "minutes before a held merge lock is treated as abandoned",
    ),
    "lock_retries": (
        "50",
        "acquisition attempts for a file lock before giving up",
    ),
    "lock_sleep_ms": (
        "100",
        "milliseconds between file-lock acquisition attempts",
    ),
    "lock_stale_seconds": (
        "60",
        "age at which a held file lock is treated as abandoned",
    ),
    "worktree_dep_install_timeout_seconds": (
        "600",
        "seconds a new worktree's dependency install may run",
    ),
    "universe_export_timeout_seconds": (
        "600",
        "seconds a universe export subprocess may run",
    ),
    "doctor_resync_recursive_timeout_seconds": (
        "120",
        "seconds the doctor's recursive resync probe may run",
    ),
    "migration_rehearsal_command_timeout_seconds": (
        "600",
        "seconds one governed-migration rehearsal command may run",
    ),
    "backup_subprocess_timeout_seconds": (
        "600",
        "seconds the pre-apply migration backup subprocess may run",
    ),
    "strategize_carry_horizon_days": (
        "60",
        "days of prior strategy carry entries a refresh reconsiders",
    ),
    "strategize_carry_limit": (
        "200",
        "carry entries a single strategy refresh may surface",
    ),
    "sim_preflight_task_threshold": (
        "8",
        "epic task count above which simulation runs its preflight pass",
    ),
    "sim_preflight_size_kb": (
        "20",
        "epic context size in KB above which simulation preflights",
    ),
    "sim_force_standard_integration": (
        "false",
        "force standard integration simulation over compressed two-phase",
    ),
}

# Key families recognized by prefix, where the suffix names one runtime
# target rather than a distinct tunable.
MACHINE_SETTING_PREFIXES: Dict[str, str] = {
    "hc_": "per-check doctor cutoff bounding one health check's scan window",
}

# Prefix families whose authority is a DB capability row. The machine copy is
# never consulted once a project id is known, which is every live call path.
_DB_OWNED_PREFIXES: Dict[str, str] = {
    "executor_default_lane_": SESSION_ROUTING_CAPABILITY,
    "lane_paths_": SESSION_ROUTING_CAPABILITY,
    "do_process_offer_": SESSION_ROUTING_CAPABILITY,
}


def machine_setting_default(key: str) -> str:
    """Return one machine-owned key's source default."""
    if key in LOCAL_PROJECT_KEYS:
        return RECOGNIZED_PROJECT_KEYS[key][0]
    return MACHINE_SETTING_KEYS[key][0]


def db_owned_capability_for(key: str) -> str | None:
    """Return the capability that actually owns ``key``, or ``None``.

    A non-``None`` result means the machine settings entry is a dead twin of
    DB authority: readers resolve the value from the named capability row.
    """
    if key in DB_PROJECT_POLICY_KEYS:
        return PROJECT_POLICY_CAPABILITY
    for prefix, capability in _DB_OWNED_PREFIXES.items():
        if key.startswith(prefix):
            return capability
    return None


def is_recognized(key: str) -> bool:
    """Return whether ``key`` is a machine-owned setting with a live reader."""
    if key in MACHINE_SETTING_KEYS or key in LOCAL_PROJECT_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in MACHINE_SETTING_PREFIXES)


def db_owned_settings(settings: Mapping[str, object]) -> Tuple[Tuple[str, str], ...]:
    """Return ``(key, owning capability)`` for each DB-owned twin present."""
    found: list[Tuple[str, str]] = []
    for key in _sorted_keys(settings):
        capability = db_owned_capability_for(key)
        if capability is not None:
            found.append((key, capability))
    return tuple(found)


def unrecognized_settings(settings: Mapping[str, object]) -> Tuple[str, ...]:
    """Return present keys that are neither machine-owned nor DB-owned.

    DB-owned twins are excluded so a caller can report them under their own
    remediation — pointing at the owning capability rather than at deletion.
    """
    return tuple(
        key
        for key in _sorted_keys(settings)
        if not is_recognized(key) and db_owned_capability_for(key) is None
    )


def _sorted_keys(settings: Mapping[str, object]) -> Iterable[str]:
    return sorted(str(key) for key in settings)


__all__ = [
    "MACHINE_SETTING_KEYS",
    "MACHINE_SETTING_PREFIXES",
    "SESSION_STALE_TTL_WITH_HOLDINGS_KEY",
    "db_owned_capability_for",
    "db_owned_settings",
    "is_recognized",
    "machine_setting_default",
    "unrecognized_settings",
]
