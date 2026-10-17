"""Recognized project setting keys and defaults.

One source of truth for each key's source default and one-line meaning.
``project-policy`` owns shared project behavior in the DB; local-only keys
describe machine checkout facts. Machine-local runtime tunables are the
separate registry in
``yoke_contracts.machine_config.settings_keys``.

The authored-file line limit is deliberately not a key here: it must be
enforceable by an offline git hook in a fresh clone, so it is checked-in
project-file policy owned by
``yoke_contracts.project_contract.file_line_policy``.
"""

from __future__ import annotations

from typing import Dict

from yoke_contracts.setting_spec import SettingSpec
from yoke_contracts.project_contract.disposable_generated_paths_policy import (
    DISPOSABLE_GENERATED_PATHS_DEFAULT,
)


from yoke_contracts.title_policy import (
    DEFAULT_TITLE_MAX_LENGTH,
    TITLE_MAX_LENGTH_MINIMUM,
)

# The two capability rows that carry DB-owned project configuration. Named
# here so the machine-settings registry can point at the real authority
# without importing upward into the core package.
PROJECT_POLICY_CAPABILITY = "project-policy"
SESSION_ROUTING_CAPABILITY = "session-routing"

RECOGNIZED_PROJECT_KEYS: Dict[str, SettingSpec] = {
    "title_max_length": SettingSpec(
        DEFAULT_TITLE_MAX_LENGTH,
        int,
        "title character limit enforced on item/epic-task creation and "
        f"title edits (minimum {TITLE_MAX_LENGTH_MINIMUM})",
        minimum=TITLE_MAX_LENGTH_MINIMUM,
    ),
    "base_branch": SettingSpec(
        "main", str, "trunk branch worktrees branch from and merges land on"
    ),
    "wip_cap": SettingSpec(
        30, int, "scheduler WIP cap for conduct-eligible items", minimum=0
    ),
    "default_priority": SettingSpec(
        "medium",
        str,
        "priority assigned to new backlog items when none is given",
        allowed_values=("low", "medium", "high", "critical"),
    ),
    "merge_conflict_threshold": SettingSpec(
        2,
        int,
        "rebase auto-resolve passes allowed before falling back to merge",
        minimum=0,
    ),
    "max_attempts": SettingSpec(
        5, int, "dispatch attempts per epic task before the chain halts", minimum=0
    ),
    "steering_report_staffing_minutes": SettingSpec(
        5,
        int,
        "how long runnable unclaimed work may sit before the steering report "
        "marks it overdue rather than merely available",
        minimum=0,
    ),
    "steering_report_idle_minutes": SettingSpec(
        20,
        int,
        "how long a claim holder stays quiet before the steering report "
        "presumes it stuck",
        minimum=0,
    ),
    "steering_report_interval_minutes": SettingSpec(
        2,
        int,
        "shortest gap between fleet reports appended to one steering "
        "session's messages",
        minimum=0,
    ),
}


RECOGNIZED_PROJECT_KEYS["disposable_generated_paths"] = SettingSpec(
    list(DISPOSABLE_GENERATED_PATHS_DEFAULT),
    list,
    "generated paths safe to retire with a landed worktree",
)

#: Keys this contract used to recognize, and the reason each one went. The
#: stored capability documents are converged against this set so a retired
#: key does not outlive the code that read it: nothing prunes settings
#: documents on its own, and a key nobody reads still reads to an operator
#: as configuration that does something.
RETIRED_PROJECT_KEYS: Dict[str, str] = {
    "steering_backstop_unpicked_minutes": (
        "the steering seat staffs work itself; the fleet report names it"
    ),
    "steering_report_stale_minutes": (
        "one number answered two unrelated questions; staffing and idle "
        "thresholds are now separate keys"
    ),
    "steering_backstop_worker_budget": (
        "no automatic staffing means no concurrent-worker budget to cap"
    ),
}

# Typed int form of the ``wip_cap`` source default — import this instead of
# restating the numeric literal at call sites and response-model defaults.
DEFAULT_WIP_CAP = int(RECOGNIZED_PROJECT_KEYS["wip_cap"].default)

# Typed int forms of the steering-report defaults, for the same reason.
DEFAULT_STEERING_REPORT_STAFFING_MINUTES = int(
    RECOGNIZED_PROJECT_KEYS["steering_report_staffing_minutes"].default
)
DEFAULT_STEERING_REPORT_IDLE_MINUTES = int(
    RECOGNIZED_PROJECT_KEYS["steering_report_idle_minutes"].default
)
DEFAULT_STEERING_REPORT_INTERVAL_MINUTES = int(
    RECOGNIZED_PROJECT_KEYS["steering_report_interval_minutes"].default
)

LOCAL_PROJECT_KEYS = frozenset({"worktrees_dir"})
DB_PROJECT_POLICY_KEYS = tuple(
    key for key in RECOGNIZED_PROJECT_KEYS if key not in LOCAL_PROJECT_KEYS
)
