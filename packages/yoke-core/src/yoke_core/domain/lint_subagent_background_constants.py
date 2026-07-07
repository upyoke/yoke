"""Shared constants for :mod:`yoke_core.domain.lint_subagent_background`.

Sibling-leaf module mirroring the
``lint_long_command_polling_constants`` pattern: hosting constants here
keeps the entry-point module under the file-line cap and avoids any
``-m`` re-entry import cycle when the hook runs as a subprocess.
"""

from __future__ import annotations


CHECK_ID = "subagent_background"
HOOK_NAME = "lint-subagent-background"
CONFIG_KEY_MODE = "lint_subagent_background_mode"
DEFAULT_MODE = "warn"
VALID_MODES = ("warn", "deny")
SUPPRESSION_TOKEN = "# lint:no-subagent-background-check"
AGENT_TYPE_ENV_VAR = "YOKE_HOOK_AGENT_TYPE"

# Tools whose wake delivery semantics break under the atomic-turn shape
# of a Yoke subagent dispatched turn.
WAKE_LOSS_TOOLS = frozenset({"Monitor", "ScheduleWakeup", "TaskOutput"})

# Watcher wrapper module ids. Foreground invocation is the canonical
# subagent shape; backgrounded invocation is the structural deadlock.
WATCHER_MODULE_NAMES: tuple[str, ...] = (
    "yoke_core.tools.watch_pytest",
    "yoke_core.tools.watch_merge",
    "yoke_core.tools.watch_doctor",
    "yoke_core.tools.watch_tail",
)
