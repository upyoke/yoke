"""Clear the onboarding activation latch a bare run row once satisfied.

The Overview's ``/yoke onboard`` module latched on "an onboarding run row
exists". A run row appears with the checklist's first write, so a run
blocked at its first hosting step latched the module activated, and the
card printed its execution-ready sentence over a universe with no scaffold
installed and no environments registered. The signal now requires a run
whose checklist has no open rows.

The latch is monotone and never re-derives, which is correct for a signal
that can legitimately disappear and wrong for one that was never true. The
rows written under the old signal would therefore keep that sentence on
screen forever. This entry removes exactly those — the ``run_onboard`` fact
in a universe holding no complete run — and leaves every fact an honest
signal produced, including a ``run_onboard`` row in a universe that did
finish a checklist.

Terminal statuses are written out here rather than read from the running
build's checklist vocabulary. A history entry must produce the same result
whenever it runs, and a later release that renames or adds a status would
otherwise reach backwards and change what this entry deleted.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _table_exists


FACTS_TABLE = "overview_activation_facts"
RUNS_TABLE = "project_onboarding_runs"
ROWS_TABLE = "project_onboarding_checklist_rows"
MODULE_KEY = "run_onboard"

#: Checklist statuses that close a row. Anything else leaves the run open,
#: so a checklist carrying one is not a finished onboarding.
TERMINAL_ROW_STATUSES = ("not-needed", "deferred", "verified")

_TERMINAL_VALUES = ", ".join(f"'{status}'" for status in TERMINAL_ROW_STATUSES)

#: A run counts as complete when it has checklist rows and none of them is
#: open. The row requirement matters: a run row whose checklist never
#: materialized would otherwise read complete by vacuum.
_COMPLETE_RUN_EXISTS = f"""
SELECT 1 FROM {RUNS_TABLE} r
WHERE EXISTS (
    SELECT 1 FROM {ROWS_TABLE} c WHERE c.run_id = r.run_id
)
AND NOT EXISTS (
    SELECT 1 FROM {ROWS_TABLE} c
    WHERE c.run_id = r.run_id AND c.status NOT IN ({_TERMINAL_VALUES})
)
"""


def _complete_run_exists(conn: Any) -> bool:
    if not (_table_exists(conn, RUNS_TABLE) and _table_exists(conn, ROWS_TABLE)):
        return False
    row = conn.execute(f"SELECT EXISTS({_COMPLETE_RUN_EXISTS})").fetchone()
    return bool(row[0]) if row is not None else False


def _latched(conn: Any) -> bool:
    row = conn.execute(
        f"SELECT EXISTS(SELECT 1 FROM {FACTS_TABLE} "
        f"WHERE module_key = '{MODULE_KEY}')"
    ).fetchone()
    return bool(row[0]) if row is not None else False


def apply(conn: Any) -> None:
    """Drop the onboarding latch wherever no complete run backs it."""
    if not _table_exists(conn, FACTS_TABLE) or _complete_run_exists(conn):
        return
    conn.execute(
        f"DELETE FROM {FACTS_TABLE} WHERE module_key = '{MODULE_KEY}'"
    )


def invariants(conn: Any) -> None:
    """Prove no onboarding latch survives without a complete run behind it."""
    if not _table_exists(conn, FACTS_TABLE):
        return
    assert _complete_run_exists(conn) or not _latched(conn), (
        f"{FACTS_TABLE} must carry no {MODULE_KEY} row while the universe "
        "holds no onboarding run with a fully closed checklist"
    )


__all__ = [
    "FACTS_TABLE",
    "MODULE_KEY",
    "ROWS_TABLE",
    "RUNS_TABLE",
    "TERMINAL_ROW_STATUSES",
    "apply",
    "invariants",
]
