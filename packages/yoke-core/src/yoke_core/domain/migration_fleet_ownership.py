"""Whether a database's tables can still be converged by the role serving it.

A boot converge adds columns to its own tables. Postgres only permits that for
tables the connecting role owns, so a table created by some *other* role — an
operator running a repair through an admin connection, say — becomes
permanently un-convergeable. Nothing notices until a release adds a column to
it; then the tenant fails its health gate at boot, and the error reads like a
missing column because Postgres resolves identifiers before it checks
privileges.

**This cannot be rehearsed on a copy.** ``pg_restore --no-owner`` assigns every
object to whoever restores it, which is precisely the ownership in question, so
a restored copy always looks uniform no matter what the source looked like.
Ownership has to be read from the live database, and that is cheap: one query,
no dump, no restore.

The expected owner is inferred from the majority rather than configured. The
answer is already written in the database, and a wrong configured guess would
hand every table to the wrong role.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

#: How many drifted tables a summary names before it starts counting.
SUMMARY_NAME_LIMIT = 6

OWNERSHIP_SQL = """
SELECT c.relname, pg_get_userbyid(c.relowner)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname
"""


@dataclass(frozen=True)
class OwnershipReport:
    """Who owns what, and which tables disagree with the majority."""

    expected_owner: str
    table_count: int
    drifted: Tuple[Tuple[str, str], ...] = ()

    @property
    def uniform(self) -> bool:
        return not self.drifted

    @property
    def summary(self) -> str:
        if self.uniform:
            return f"{self.table_count} tables, all owned by {self.expected_owner}"
        # Name a handful and count the rest. The realistic finding is one or
        # two stray tables and the operator needs those nouns; a whole-database
        # mismatch says the expected owner is wrong, and printing a hundred
        # rows to say so buries the sentence that explains it.
        shown = [f"{t} owned by {o}" for t, o in self.drifted[:SUMMARY_NAME_LIMIT]]
        rest = len(self.drifted) - len(shown)
        if rest:
            shown.append(f"and {rest} more")
        return (
            f"{len(self.drifted)} of {self.table_count} tables cannot be "
            f"converged by {self.expected_owner}: {', '.join(shown)}"
        )


def read_table_owners(conn: Any) -> List[Tuple[str, str]]:
    """Every public table and its owner, from the live database."""
    rows = conn.execute(OWNERSHIP_SQL).fetchall()
    return [(str(name), str(owner)) for name, owner in rows]


def majority_owner(rows: Sequence[Tuple[str, str]]) -> str:
    counts: Dict[str, int] = {}
    for _table, owner in rows:
        counts[owner] = counts.get(owner, 0) + 1
    # Ties break on the owner name so the answer is stable across runs; a tie
    # is already a report of drift either way.
    return max(sorted(counts), key=lambda owner: (counts[owner], owner))


def inspect(conn: Any, *, expected_owner: str | None = None) -> OwnershipReport:
    """Report ownership drift for a live database."""
    rows = read_table_owners(conn)
    if not rows:
        return OwnershipReport(expected_owner=expected_owner or "", table_count=0)
    expected = expected_owner or majority_owner(rows)
    drifted = tuple((t, o) for t, o in rows if o != expected)
    return OwnershipReport(
        expected_owner=expected, table_count=len(rows), drifted=drifted
    )


def realign(conn: Any, *, tables: Sequence[str], owner: str) -> List[str]:
    """Hand named tables to *owner*; returns the tables actually altered.

    Named tables only, never the whole drift set: a differently-owned table is
    not automatically wrong — a separately provisioned surface may legitimately
    own its own — so a repair states what it is fixing.
    """
    existing = {table for table, _owner in read_table_owners(conn)}
    altered: List[str] = []
    for table in tables:
        if table not in existing:
            continue
        # Identifiers cannot be parameterized. Both sides originate in
        # pg_class and pg_get_userbyid, never in caller-supplied text.
        conn.execute(f'ALTER TABLE public."{table}" OWNER TO "{owner}"')
        altered.append(table)
    return altered


__all__ = [
    "OWNERSHIP_SQL",
    "OwnershipReport",
    "inspect",
    "majority_owner",
    "read_table_owners",
    "realign",
]
