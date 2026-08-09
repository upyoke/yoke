"""Reduce an execution instruction to the prose an agent actually reads.

Three columns described the instruction without being the instruction, and each
could disagree with it. ``title`` was a second summary to keep in step with the
content, shown in an editor and nowhere an agent reads. ``ordering`` was a
hand-maintained integer whose only observable effect was the tiebreak inside one
scope group, which the row id already gives deterministically. ``status`` was a
second way to say "this does not apply", competing with the scope that decides
it: a disabled instruction still bound to a workflow looked live in every
listing while reaching nothing, and an active instruction bound to nothing
looked live while doing the same.

Scope is now the only answer to "does this apply", and the content is the only
answer to "what does it say".

Nothing is copied forward. These columns fed no other surface: the title was
never rendered into the prose an agent receives, the ordering never survived
into a resolved instruction, and status has no successor field to carry a
disabled row into -- an operator who wants an instruction to stop applying
unscopes or deletes it.
"""

from __future__ import annotations

from typing import Any

#: The oldest artifact that may serve a database this entry has been applied
#: to. Derived rather than chosen: every build carrying this code is newer than
#: ``0.1.1+launch.197``, the published build at authoring time, because that
#: build predates these commits and still reads all three columns. Build
#: numbers only increase, so the shipping build is at least ``launch.198``,
#: which makes this floor low enough never to refuse a build that can serve and
#: high enough to refuse every build that cannot. Raising it later needs its own
#: evidence; lowering it re-admits a container that reads dropped columns.
MINIMUM_SERVING_VERSION = "0.1.1+launch.198"

INSTRUCTIONS_TABLE = "workflow_execution_instructions"

#: Columns to retire, and the surface that already answers what each claimed.
RETIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title", "the content is the instruction"),
    ("ordering", "scope breadth then id orders resolution"),
    ("status", "scope decides whether an instruction applies"),
)


def apply(conn: Any) -> None:
    """Drop each retired column that is still present.

    Guards with an explicit existence check rather than ``DROP COLUMN IF
    EXISTS``, which Postgres accepts and SQLite does not — the generic SQLite
    validation surface has to be able to run this too.
    """
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _table_exists(conn, INSTRUCTIONS_TABLE):
        return
    for column, _reason in RETIRED_COLUMNS:
        if not _column_exists(conn, INSTRUCTIONS_TABLE, column):
            continue
        conn.execute(
            f'ALTER TABLE "{INSTRUCTIONS_TABLE}" DROP COLUMN "{column}"'
        )


def invariants(conn: Any) -> None:
    """Prove no retired column survives, and that the prose does.

    The second half matters because this entry drops columns from the table
    whose remaining column is the whole product: an entry that left the table
    without ``content`` would have destroyed the instructions rather than
    trimmed them.
    """
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _table_exists(conn, INSTRUCTIONS_TABLE):
        return
    for column, reason in RETIRED_COLUMNS:
        if _column_exists(conn, INSTRUCTIONS_TABLE, column):
            raise AssertionError(
                f"{INSTRUCTIONS_TABLE}.{column} is retired but still present "
                f"({reason})"
            )
    for column in ("content", "applies_to_all_workflows",
                   "applies_to_all_projects"):
        if not _column_exists(conn, INSTRUCTIONS_TABLE, column):
            raise AssertionError(
                f"{INSTRUCTIONS_TABLE}.{column} is required but absent"
            )


__all__ = [
    "INSTRUCTIONS_TABLE",
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMNS",
    "apply",
    "invariants",
]
