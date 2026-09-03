"""Installed Yoke project bindings for tenant-fleet database selection.

The generic migration rehearsal domain accepts a caller-supplied fleet.  This
adapter owns Yoke's Platform catalog name and tenant naming convention so tools
shipped in the ``yoke-core`` wheel can select that fleet without importing the
source-checkout-only ``runtime`` package.
"""

from __future__ import annotations

from typing import Callable, List, Sequence, Set, Tuple

from yoke_core.domain.migration_validation_binding import (
    DERIVED_DATABASE_SUFFIX,
    RecordedBinding,
    recorded_bindings,
)
from yoke_core.domain.pg_test_db_namespace import SCRATCH_DATABASE_PREFIX


PLATFORM_DATABASE = "yoke_platform"
TENANT_DATABASE_PATTERN = "yoke_%"

#: Why a candidate database is, or is not, one the release must keep serving.
TENANT_REASON = "tenant"
CONTROL_PLANE_REASON = "control plane"
VALIDATION_EXCLUSION_REASON = "excluded: validation surface"
SCRATCH_EXCLUSION_REASON = "excluded: scratch"


def database_dsn(authority_dsn: str, database: str) -> str:
    """Retarget an explicit admin authority to one database in its cluster."""
    from psycopg import conninfo

    parameters = conninfo.conninfo_to_dict(authority_dsn)
    return conninfo.make_conninfo(
        **{**parameters, "dbname": database, "connect_timeout": "20"}
    )


def classify_database(name: str, *, validation_databases: Set[str]) -> Tuple[bool, str]:
    """Return whether *name* is a fleet member, and the reason either way.

    The fleet is the set of databases a release must keep serving, which is
    narrower than the set of databases carrying Yoke's schema. Three kinds of
    neighbour sit on the same cluster and are owned by something other than a
    tenant: the Platform catalog, scratch databases a test run abandoned, and
    the validation database governed migration rehearsal applies history into
    and leaves behind. Converging any of them proves nothing about a tenant,
    and the latter two have each failed a release by being counted as one.
    """
    if name == PLATFORM_DATABASE:
        return False, CONTROL_PLANE_REASON
    if name.startswith(SCRATCH_DATABASE_PREFIX):
        return False, SCRATCH_EXCLUSION_REASON
    if name in validation_databases or name.endswith(DERIVED_DATABASE_SUFFIX):
        return False, VALIDATION_EXCLUSION_REASON
    return True, TENANT_REASON


def tenant_databases(
    dsn_for: Callable[[str], str],
    *,
    emit: Callable[[str], None] = print,
) -> List[str]:
    """Return the Yoke databases on this cluster a release must keep serving.

    Every candidate is classified out loud before any of them is copied, so
    the roster in a preflight capture answers "which databases did this
    rehearse, and why those?" without a reader having to reconstruct the rule.
    A cluster quietly accumulating scratch or rehearsal databases is a leak
    somebody still has to clean up; dropping those in silence is how one of
    them ends up gating a release again.
    """
    import psycopg

    with psycopg.connect(dsn_for(PLATFORM_DATABASE), connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname LIKE %s "
                "ORDER BY datname",
                (TENANT_DATABASE_PATTERN,),
            )
            candidates = [str(row[0]) for row in cur.fetchall()]

    bindings = recorded_bindings()
    _report_unreadable_bindings(bindings, emit)
    validation_databases = {b.database for b in bindings if b.database}
    roster = [
        (name, *classify_database(name, validation_databases=validation_databases))
        for name in candidates
    ]
    members = [name for name, member, _reason in roster if member]
    _report_roster(roster, len(members), emit)
    _report_scratch_leak(roster, emit)
    return members


def _report_roster(
    roster: Sequence[Tuple[str, bool, str]],
    member_count: int,
    emit: Callable[[str], None],
) -> None:
    emit(
        f"fleet roster: {len(roster)} candidate database(s), "
        f"{member_count} fleet member(s)"
    )
    width = max((len(name) for name, _member, _reason in roster), default=0)
    for name, member, reason in roster:
        status = "member" if member else "not a member"
        emit(f"  {status:<12}  {name:<{width}}  {reason}")


def _report_scratch_leak(
    roster: Sequence[Tuple[str, bool, str]],
    emit: Callable[[str], None],
) -> None:
    leaked = sum(1 for _n, _m, reason in roster if reason == SCRATCH_EXCLUSION_REASON)
    if leaked:
        emit(
            f"scratch databases skipped: {leaked} name(s) carrying the "
            f"reserved {SCRATCH_DATABASE_PREFIX!r} prefix are not fleet "
            "members; remove them with `python3 -m "
            "runtime.api.tools.drop_leftover_test_databases`"
        )


def _report_unreadable_bindings(
    bindings: Sequence[RecordedBinding],
    emit: Callable[[str], None],
) -> None:
    """Say when a binding cannot name the database it protects from the fleet.

    An unreadable binding is not a missing one: it still points at a live
    rehearsal database, which now falls through to the name rule alone and is
    rehearsed as a tenant if it does not happen to carry the derived suffix.
    """
    for binding in bindings:
        if binding.database:
            continue
        emit(
            f"could not read a database name from validation binding "
            f"{binding.env_var} ({binding.source}); the database it names "
            "will be rehearsed as a fleet member unless its name carries "
            f"{DERIVED_DATABASE_SUFFIX!r}. Re-provision it with `python3 -m "
            "runtime.api.tools.authority_validation_copy`."
        )


__all__ = [
    "CONTROL_PLANE_REASON",
    "PLATFORM_DATABASE",
    "SCRATCH_DATABASE_PREFIX",
    "SCRATCH_EXCLUSION_REASON",
    "TENANT_DATABASE_PATTERN",
    "TENANT_REASON",
    "VALIDATION_EXCLUSION_REASON",
    "classify_database",
    "database_dsn",
    "tenant_databases",
]
