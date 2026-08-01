"""Shared constants for :mod:`yoke_core.domain.lint_subagent_background`.

Sibling-leaf module mirroring the
``lint_long_command_polling_constants`` pattern: hosting constants here
keeps the entry-point module under the file-line cap and avoids any
``-m`` re-entry import cycle when the hook runs as a subprocess.
"""

from __future__ import annotations

from yoke_contracts.session_identity import ACTOR_ROLE_ENV_VAR
from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form


CHECK_ID = "subagent_background"
HOOK_NAME = "lint-subagent-background"
DEFAULT_MODE = "warn"
VALID_MODES = ("warn", "deny")
SUPPRESSION_TOKEN = "# lint:no-subagent-background-check"
AGENT_TYPE_ENV_VAR = ACTOR_ROLE_ENV_VAR

# Tools whose wake delivery semantics break under the atomic-turn shape
# of a Yoke subagent dispatched turn.
WAKE_LOSS_TOOLS = frozenset({"Monitor", "ScheduleWakeup", "TaskOutput"})

# Watcher invocations. Foreground invocation is the canonical subagent
# shape; backgrounded invocation is the structural deadlock. Both the
# `yoke watch <kind>` command and the module fallback are matched, so
# neither spelling routes around the guard.
WATCHER_MODULE_NAMES: tuple[str, ...] = (
    "yoke_core.tools.watch_pytest",
    "yoke_core.tools.watch_merge",
    "yoke_core.tools.watch_doctor",
    "yoke_core.tools.watch_tail",
    *(cli_form(module) for module in WATCH_CLI_TOKENS),
)
