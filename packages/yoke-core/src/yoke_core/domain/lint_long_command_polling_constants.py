"""Shared constants for the long-command polling lint.

This leaf module exists to break what would otherwise be an import cycle
when the hook is invoked via ``python -m
yoke_core.domain.lint_long_command_polling``. Under ``-m``, the entry
point is loaded as ``__main__`` first, and a sibling that imports a
constant from the entry-point's regular path triggers a second load of
the entry-point module — which then re-enters its own sibling imports
before the sibling has finished initializing.

Hosting the shared constants here, with no back-reference to any
sibling, eliminates the cycle. The entry-point re-exports each constant
(``DEFAULT_MODE``, ``VALID_MODES``,
``CHECK_ID``, ``SUPPRESSION_TOKEN``,
``MONITOR_DUPLICATE_SUPPRESSION_TOKEN``, ``BG_WAITER_SUPPRESSION_TOKEN``,
and the cadence thresholds) so callers continue to import them from
``yoke_core.domain.lint_long_command_polling``.
"""

from __future__ import annotations


RECENT_EVENT_LOOKBACK_SECONDS = 600  # 10 minutes — bounds the DB scan
SLEEP_CADENCE_FLOOR_SECONDS = 60
SUPPRESSION_TOKEN = "# lint:no-polling-check"
MONITOR_DUPLICATE_SUPPRESSION_TOKEN = "# lint:no-monitor-duplicate-check"
BG_WAITER_SUPPRESSION_TOKEN = "# lint:no-bg-waiter-check"
CHECK_ID = "long_command_polling"
DEFAULT_MODE = "warn"
VALID_MODES = ("warn", "deny")
