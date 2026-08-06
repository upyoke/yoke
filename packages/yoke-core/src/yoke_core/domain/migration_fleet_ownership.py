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

General drift reports infer the expected serving owner from the table majority,
rather than the database owner. Contract-specific handoffs instead use their
declared ledger table's owner. External databases may belong to a provisioner
while their tables belong to the runtime role; the answer is already written in
the managed tables, and the wrong topology assumption would hand objects to the
wrong role.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Sequence, Tuple

#: How many drifted tables a summary names before it starts counting.
SUMMARY_NAME_LIMIT = 6

OWNERSHIP_SQL = """
SELECT c.relname, pg_get_userbyid(c.relowner)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema() AND c.relkind = 'r'
ORDER BY c.relname
"""

FUNCTION_OWNERSHIP_SQL = """
SELECT procedure.proname, pg_get_userbyid(procedure.proowner)
FROM pg_proc AS procedure
JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = current_schema()
  AND procedure.prokind = 'f'
  AND procedure.pronargs = 0
  AND pg_catalog.pg_get_function_result(procedure.oid) = 'trigger'
ORDER BY procedure.proname
"""

_OWNER_TRANSFER_SAVEPOINT = "migration_owner_transfer"


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
    """Every current-schema table and its owner, from the live database."""
    rows = conn.execute(OWNERSHIP_SQL).fetchall()
    return [(str(name), str(owner)) for name, owner in rows]


def read_trigger_function_owners(conn: Any) -> List[Tuple[str, str]]:
    """Every current-schema zero-argument trigger function and its owner."""
    rows = conn.execute(FUNCTION_OWNERSHIP_SQL).fetchall()
    return [(str(name), str(owner)) for name, owner in rows]


def current_schema(conn: Any) -> str:
    """Return the first schema selected by the connection's search path."""
    row = conn.execute("SELECT current_schema()").fetchone()
    if row is None or not str(row[0]).strip():
        raise RuntimeError("connected database has no current schema")
    return str(row[0])


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@contextmanager
def owner_transfer_authority(conn: Any, *, owner: str) -> Iterator[None]:
    """Temporarily borrow *owner* when object handoff requires membership.

    RDS admin roles can grant ordinary roles but are not necessarily members
    of each tenant owner. The grant and revoke share the caller's transaction;
    a savepoint rolls the grant back if handoff or revocation fails.
    """
    membership = conn.execute(
        "SELECT pg_has_role(current_user, %s, 'SET')",
        (owner,),
    ).fetchone()
    if membership is not None and bool(membership[0]):
        yield
        return

    conn.execute(f"SAVEPOINT {_OWNER_TRANSFER_SAVEPOINT}")
    try:
        quoted_owner = _quoted_identifier(owner)
        conn.execute(f"GRANT {quoted_owner} TO CURRENT_USER")
        yield
        conn.execute(f"REVOKE {quoted_owner} FROM CURRENT_USER")
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_OWNER_TRANSFER_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_OWNER_TRANSFER_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_OWNER_TRANSFER_SAVEPOINT}")


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


def table_owner(conn: Any, table: str) -> str:
    """Return the owner of one declared current-schema table."""
    owners = dict(read_table_owners(conn))
    if table not in owners:
        raise RuntimeError(f"declared ownership table {table!r} does not exist")
    return owners[table]


def schema_objects_owned_by(
    conn: Any,
    *,
    tables: Sequence[str],
    trigger_functions: Sequence[str],
    owner: str,
) -> bool:
    """Return whether every exact managed table and function has *owner*."""
    table_owners = dict(read_table_owners(conn))
    function_owners = dict(read_trigger_function_owners(conn))
    return all(table_owners.get(table) == owner for table in tables) and all(
        function_owners.get(function) == owner for function in trigger_functions
    )


def realign(conn: Any, *, tables: Sequence[str], owner: str) -> List[str]:
    """Hand named tables to *owner*; returns the tables actually altered.

    Named tables only, never the whole drift set: a differently-owned table is
    not automatically wrong — a separately provisioned surface may legitimately
    own its own — so a repair states what it is fixing.
    """
    existing = {table for table, _owner in read_table_owners(conn)}
    schema = _quoted_identifier(current_schema(conn))
    altered: List[str] = []
    for table in tables:
        if table not in existing:
            continue
        # Identifiers cannot be parameterized. Both sides originate in
        # pg_class and pg_get_userbyid, never in caller-supplied text.
        conn.execute(
            f"ALTER TABLE {schema}."
            f"{_quoted_identifier(table)} OWNER TO {_quoted_identifier(owner)}"
        )
        altered.append(table)
    return altered


def realign_trigger_functions(
    conn: Any,
    *,
    functions: Sequence[str],
    owner: str,
) -> List[str]:
    """Hand named zero-argument trigger functions to *owner*."""
    existing = {name for name, _owner in read_trigger_function_owners(conn)}
    schema = _quoted_identifier(current_schema(conn))
    altered: List[str] = []
    for function in functions:
        if function not in existing:
            continue
        # Both identifiers come from database catalog rows. Function names
        # are selected from the catalog before interpolation, as tables are.
        conn.execute(
            f"ALTER FUNCTION {schema}."
            f"{_quoted_identifier(function)}() OWNER TO "
            f"{_quoted_identifier(owner)}"
        )
        altered.append(function)
    return altered


__all__ = [
    "FUNCTION_OWNERSHIP_SQL",
    "OWNERSHIP_SQL",
    "OwnershipReport",
    "current_schema",
    "inspect",
    "majority_owner",
    "owner_transfer_authority",
    "read_table_owners",
    "read_trigger_function_owners",
    "realign",
    "realign_trigger_functions",
    "schema_objects_owned_by",
    "table_owner",
]
