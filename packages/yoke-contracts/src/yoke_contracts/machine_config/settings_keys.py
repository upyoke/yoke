"""Recognized machine-local setting keys and defaults.

``~/.yoke/config.json`` under ``settings`` owns machine-local runtime
tunables: timeouts, retry budgets, guardrail modes, and per-machine
thresholds. This module is one source of truth for each key's source
default and one-line meaning — the machine-local sibling of
:mod:`yoke_contracts.project_contract.project_keys`.

Shared project behavior is owned by the DB ``project-policy`` capability, and
execution levels by the universe ``levels`` setting with an optional project
``session-routing`` override. A machine settings key naming a ``project-policy``
concern is a dead twin: every live reader resolves it from the DB, so editing
the machine copy silently changes nothing. :func:`db_owned_capability_for` names the real authority so callers
can point an operator at the surface that decides.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Tuple

from yoke_contracts.setting_spec import SettingSpec

from yoke_contracts.project_contract.project_keys import (
    DB_PROJECT_POLICY_KEYS,
    LOCAL_PROJECT_KEYS,
    PROJECT_POLICY_CAPABILITY,
)

SESSION_STALE_TTL_WITH_HOLDINGS_KEY = "session_stale_ttl_with_holdings_minutes"

# Machine-owned keys: (source default, one-line meaning). The default is the
# value the reader falls back to when the key is absent, so an unset key and a
# key set to its default behave identically.
MACHINE_SETTING_KEYS: Dict[str, SettingSpec] = {
    "max_active_worktrees": SettingSpec(
        5,
        int,
        "linked worktrees doing work (landed lanes excluded) allowed before "
        "creation preflight refuses",
        minimum=0,
    ),
    "max_worker_lanes": SettingSpec(
        0,
        int,
        "Yoke-launched workers this machine accepts before launch preview refuses; "
        "zero derives (total memory - 12 GB reserved) / 0.5 GB per worker; "
        "minimum one worker, interactive MAIN excluded",
        minimum=0,
    ),
    "max_chain_steps": SettingSpec(
        3, int, "autonomous chain steps allowed before a session checkpoints", minimum=0
    ),
    "session_stale_ttl_minutes": SettingSpec(
        20,
        int,
        "idle minutes before the stale-session sweep reclaims a session "
        "with no active holdings",
        minimum=0,
    ),
    SESSION_STALE_TTL_WITH_HOLDINGS_KEY: SettingSpec(
        1440,
        int,
        "idle minutes before the stale-session sweep reclaims a session "
        "with active holdings",
        minimum=0,
    ),
    "session_reactivation_reacquire_window_s": SettingSpec(
        300,
        int,
        "seconds a released claim stays auto-reacquirable on reactivation",
        minimum=0,
    ),
    "session_timing_enabled": SettingSpec(
        False, bool, "record per-session timing samples"
    ),
    "session_timing_retain_days": SettingSpec(
        30, int, "days of session timing samples retained before pruning", minimum=0
    ),
    "path_claim_activation_db_lock_retry_initial_ms": SettingSpec(
        100,
        int,
        "first backoff before retrying a lock-contended claim activation",
        minimum=0,
    ),
    "path_claim_activation_db_lock_retry_max_attempts": SettingSpec(
        3, int, "attempts allowed for a lock-contended claim activation", minimum=0
    ),
    "coordination_context_spec_truncation_bytes": SettingSpec(
        4096,
        int,
        "spec bytes carried into a coordination decision before truncation",
        minimum=0,
    ),
    "hook_runner_module_timeout_ms": SettingSpec(
        10000, int, "per-module budget inside one hook evaluation", minimum=0
    ),
    "hook_runner_total_timeout_ms": SettingSpec(
        10000, int, "total harness-wait budget for one hook evaluation", minimum=0
    ),
    "hook_session_end_cleanup_timeout_ms": SettingSpec(
        2500,
        int,
        "DB busy-wait budget for session-end cleanup during the hook",
        minimum=0,
    ),
    "monitor_relay_hint_text": SettingSpec(
        "", str, "override text for the relay-only reminder; empty uses the built-in"
    ),
    "watcher_progress_percent_step": SettingSpec(
        5,
        int,
        "percent delta a watcher requires before carrying a progress tick",
        minimum=0,
    ),
    "test_timeout": SettingSpec(
        1200, int, "seconds one project test command may run during merge", minimum=1
    ),
    "git_command_timeout": SettingSpec(
        120,
        int,
        "seconds one engine git command may run (merge, install publication)",
        minimum=0,
    ),
    "post_merge_rebase_timeout": SettingSpec(
        120, int, "seconds the post-merge local-sync rebase may run", minimum=0
    ),
    "ci_poll_interval": SettingSpec(
        30,
        int,
        "seconds between CI check-run polls while waiting on a merge",
        minimum=0,
    ),
    "ci_registration_timeout": SettingSpec(
        120,
        int,
        "seconds to wait for CI check-runs to register on a head commit",
        minimum=0,
    ),
    "ci_timeout": SettingSpec(
        1800,
        int,
        "seconds to wait for CI to conclude before the merge gives up",
        minimum=0,
    ),
    "standalone_post_push_ci_discovery_timeout": SettingSpec(
        90,
        int,
        "seconds to discover checks after a queue-less standalone push",
        minimum=0,
    ),
    "standalone_post_push_ci_timeout": SettingSpec(
        900,
        int,
        "seconds to wait for queue-less standalone push checks to conclude",
        minimum=0,
    ),
    "merge_lock_ttl_minutes": SettingSpec(
        30, int, "minutes before a held merge lock is treated as abandoned", minimum=0
    ),
    "lock_retries": SettingSpec(
        50, int, "acquisition attempts for a file lock before giving up", minimum=0
    ),
    "lock_sleep_ms": SettingSpec(
        100, int, "milliseconds between file-lock acquisition attempts", minimum=0
    ),
    "lock_stale_seconds": SettingSpec(
        60, int, "age at which a held file lock is treated as abandoned", minimum=0
    ),
    "worktree_dep_install_timeout_seconds": SettingSpec(
        600, int, "seconds a new worktree's dependency install may run", minimum=0
    ),
    "universe_export_timeout_seconds": SettingSpec(
        600, int, "seconds a universe export subprocess may run", minimum=0
    ),
    "doctor_resync_recursive_timeout_seconds": SettingSpec(
        120, int, "seconds the doctor's recursive resync probe may run", minimum=0
    ),
    "migration_rehearsal_command_timeout_seconds": SettingSpec(
        600, int, "seconds one governed-migration rehearsal command may run", minimum=0
    ),
    "backup_subprocess_timeout_seconds": SettingSpec(
        600, int, "seconds the pre-apply migration backup subprocess may run", minimum=0
    ),
    "strategize_carry_horizon_days": SettingSpec(
        60, int, "days of prior strategy carry entries a refresh reconsiders", minimum=0
    ),
    "strategize_carry_limit": SettingSpec(
        200, int, "carry entries a single strategy refresh may surface", minimum=0
    ),
    "sim_preflight_task_threshold": SettingSpec(
        8,
        int,
        "epic task count above which simulation runs its preflight pass",
        minimum=0,
    ),
    "sim_preflight_size_kb": SettingSpec(
        20, int, "epic context size in KB above which simulation preflights", minimum=0
    ),
    "sim_force_standard_integration": SettingSpec(
        False, bool, "force standard integration simulation over compressed two-phase"
    ),
}

MACHINE_SETTING_KEYS.update(
    {
        "browser_executable_path": SettingSpec(
            "", str, "browser executable used for local browser automation"
        ),
        "server_image_repository": SettingSpec(
            "", str, "container repository used by the local server installer"
        ),
        "distribution": SettingSpec(
            {"origin": "", "channel": ""},
            dict,
            "credential-free install origin and release channel; empty means unconfigured",
            fields=("origin", "channel"),
        ),
        "worktrees_dir": SettingSpec(
            ".worktrees", str, "checkout-relative directory holding linked worktrees"
        ),
    }
)

# Key families recognized by prefix, where the suffix names one runtime
# target rather than a distinct tunable.
MACHINE_SETTING_PREFIXES: Dict[str, str] = {
    "hc_": "per-check doctor cutoff bounding one health check's scan window",
}


def machine_setting_default(key: str) -> str:
    """Return one machine-owned key's source default."""
    value = MACHINE_SETTING_KEYS[key].default
    return str(value).lower() if isinstance(value, bool) else str(value)


def db_owned_capability_for(key: str) -> str | None:
    """Return the capability that actually owns ``key``, or ``None``.

    A non-``None`` result means the machine settings entry is a dead twin of
    DB authority: readers resolve the value from the named capability row.
    """
    if key in DB_PROJECT_POLICY_KEYS:
        return PROJECT_POLICY_CAPABILITY
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
