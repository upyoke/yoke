"""Per-worker pool of reusable blank PostgreSQL test databases.

The fixture surfaces that share one schema can reuse a single database
per worker and restore a captured baseline between tests (see
:mod:`pg_reusable_db`). The per-module helper fixtures cannot: each one
creates a blank database and then applies its own small inline DDL, so
there is no shared baseline to restore and no shared schema to fingerprint.

They can still share the expensive part. ``CREATE DATABASE`` copies an
entire template directory and ``DROP DATABASE`` unlinks it again; issued
thousands of times per gate, that file churn is what saturates the disk
once several suites share the cluster. A blank database, by contrast, is
cheap to *empty*: dropping a handful of small tables costs far less than
recreating the database that holds them.

So this module pools blank databases. A caller checks one out, applies
whatever schema it wants, and on release the database is wiped and handed
to the next caller:

- Wipe drops every schema the test created and every object it left in
  ``public``. It deliberately does NOT drop and recreate ``public``
  itself, because a recreated schema carries the recreating role's
  ownership and privileges rather than the ones a freshly created
  database would have.
- Verification then proves the result is indistinguishable from a fresh
  database: expected owner, default (``NULL``) database ACL, no schemas
  beyond the system set plus ``public``, and nothing left inside it.
- Anything short of that — a failed wipe, a changed owner, a lingering
  grant, an object the wipe did not know how to drop — retires the
  database instead of pooling it, so the caller falls back to a real
  drop. Tests that mutate database-level state (ownership, ``CONNECT``
  grants, authorized schemas) therefore keep exactly today's behavior;
  they simply stop being the common case.

The pool grows on demand, so two databases checked out at once are never
the same database, and every pooled name carries the invocation's run tag
so the orphan sweep still recognizes ownership.
"""

from __future__ import annotations

import atexit
import os

import psycopg

#: Databases PostgreSQL ships or manages itself; a test may not create
#: schemas with these names, so their presence never signals leftover state.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "public")

_DROP_TEST_SCHEMAS_SQL = """
DO $$
DECLARE ns text;
BEGIN
    FOR ns IN
        SELECT nspname FROM pg_namespace
         WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public')
           AND nspname NOT LIKE 'pg\\_%'
    LOOP
        EXECUTE format('DROP SCHEMA %I CASCADE', ns);
    END LOOP;
END
$$
"""

# Base tables first with CASCADE, which takes their indexes, sequences,
# constraints and dependent views with them; then whatever independent
# objects remain.
_DROP_PUBLIC_OBJECTS_SQL = """
DO $$
DECLARE obj record;
BEGIN
    FOR obj IN
        SELECT c.oid::regclass AS ident
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'f')
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %s CASCADE', obj.ident);
    END LOOP;
    FOR obj IN
        SELECT c.oid::regclass AS ident, c.relkind
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm', 'S')
    LOOP
        EXECUTE format(
            CASE obj.relkind
                WHEN 'v' THEN 'DROP VIEW IF EXISTS %s CASCADE'
                WHEN 'm' THEN 'DROP MATERIALIZED VIEW IF EXISTS %s CASCADE'
                ELSE 'DROP SEQUENCE IF EXISTS %s CASCADE'
            END, obj.ident);
    END LOOP;
END
$$
"""

#: One round trip returning every way a database can fail to look fresh.
#: ``datacl IS NULL`` is the default state: any explicit GRANT or REVOKE
#: on the database itself materializes the ACL and makes it non-null.
_PRISTINE_CHECK_SQL = """
    SELECT
        (SELECT pg_get_userbyid(datdba) = current_user FROM pg_database
          WHERE datname = current_database()) AS owned_by_creator,
        (SELECT datacl IS NULL FROM pg_database
          WHERE datname = current_database()) AS default_acl,
        (SELECT count(*) FROM pg_namespace
          WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public')
            AND nspname NOT LIKE 'pg\\_%') AS extra_schemas,
        (SELECT count(*) FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
          WHERE n.nspname = 'public'
            AND c.relkind IN ('r', 'p', 'f', 'v', 'm', 'S')) AS relations,
        (SELECT count(*) FROM pg_type t
           JOIN pg_namespace n ON n.oid = t.typnamespace
          WHERE n.nspname = 'public' AND t.typtype IN ('c', 'e', 'd')
            AND NOT EXISTS (
                SELECT 1 FROM pg_class c WHERE c.reltype = t.oid
            )) AS types,
        (SELECT count(*) FROM pg_proc p
           JOIN pg_namespace n ON n.oid = p.pronamespace
          WHERE n.nspname = 'public') AS routines
"""

_TERMINATE_BACKENDS_SQL = """
    SELECT pg_terminate_backend(pid)
      FROM pg_stat_activity
     WHERE datname = %s AND pid <> pg_backend_pid()
"""

#: Databases this process owns and nobody is currently using.
_free: list[str] = []
#: Databases handed out and not yet returned. Kept apart from ``_free`` so a
#: release can tell "this is checked out, empty it" from "this was already
#: returned" — a database that landed in ``_free`` twice would be handed to
#: two callers at once, and the first of them to retire it would pull the
#: database out from under the second.
_in_use: set[str] = set()
_atexit_registered = False

#: Set to any non-empty value to force every caller onto real
#: ``CREATE DATABASE`` / ``DROP DATABASE``. An escape hatch for bisecting
#: a suspected pooling interaction, not a supported runtime mode.
DISABLE_ENV = "YOKE_TEST_DISABLE_BLANK_DB_POOL"


def pooling_disabled() -> bool:
    return bool(os.environ.get(DISABLE_ENV))


def _create_blank_database() -> str:
    from runtime.api.fixtures import pg_testdb

    return pg_testdb.create_test_database(pooled=False)


def _connect(name: str):
    from runtime.api.fixtures import pg_testdb

    return psycopg.connect(
        pg_testdb.dsn_for_test_database(name), autocommit=True
    )


def _maintenance_connection():
    from runtime.api.fixtures import pg_testdb

    return psycopg.connect(pg_testdb.maintenance_dsn(), autocommit=True)


def _terminate_backends(name: str) -> None:
    with _maintenance_connection() as admin:
        admin.execute(_TERMINATE_BACKENDS_SQL, (name,))


def _wipe_and_verify(name: str) -> bool:
    """Empty *name* and return whether it now looks freshly created."""
    _terminate_backends(name)
    conn = _connect(name)
    try:
        conn.execute(_DROP_TEST_SCHEMAS_SQL)
        conn.execute(_DROP_PUBLIC_OBJECTS_SQL)
        (
            owned_by_creator,
            default_acl,
            extra_schemas,
            relations,
            types,
            routines,
        ) = conn.execute(_PRISTINE_CHECK_SQL).fetchone()
        return (
            bool(owned_by_creator)
            and bool(default_acl)
            and extra_schemas == 0
            and relations == 0
            and types == 0
            and routines == 0
        )
    finally:
        conn.close()


def _drop_for_real(name: str) -> None:
    from runtime.api.fixtures import pg_testdb

    try:
        pg_testdb.drop_test_database(name, pooled=False)
    except Exception:
        pass  # the cluster's orphan sweep reclaims stragglers


def _drain_at_exit() -> None:
    for name in [*_free, *_in_use]:
        _drop_for_real(name)
    _in_use.clear()
    _free.clear()


def checkout() -> str:
    """Return a blank database name, reusing a pooled one when available."""
    global _atexit_registered
    name = _free.pop() if _free else _create_blank_database()
    _in_use.add(name)
    if not _atexit_registered:
        atexit.register(_drain_at_exit)
        _atexit_registered = True
    return name


def release(name: str) -> bool:
    """Try to return *name* to the pool.

    Returns ``True`` when the caller must NOT drop the database: either it
    was checked out and is now empty and reusable, or it had already been
    returned and is sitting idle. Returns ``False`` for a name this pool
    does not own and for a checked-out database that could not be proven
    pristine; in both cases the caller performs a real drop, and a database
    retired that way is forgotten here first so it is dropped exactly once.

    Releasing twice is safe and is not merely defensive: a disposable
    database can be returned both by an explicit close and by the
    garbage-collected connection that owned it.
    """
    if name not in _in_use:
        return name in _free
    try:
        pristine = _wipe_and_verify(name)
    except Exception:
        pristine = False
    _in_use.discard(name)
    if pristine:
        _free.append(name)
        return True
    return False


def owns(name: str) -> bool:
    """Whether this pool is responsible for *name*."""
    return name in _in_use or name in _free


def pool_size() -> int:
    """Databases this process currently owns, checked out or free."""
    return len(_free) + len(_in_use)


def free_size() -> int:
    return len(_free)


def forget_all_for_test() -> None:
    """Drop and forget every pooled database (test-support only)."""
    _drain_at_exit()


__all__ = [
    "DISABLE_ENV",
    "SYSTEM_SCHEMAS",
    "checkout",
    "forget_all_for_test",
    "free_size",
    "owns",
    "pool_size",
    "pooling_disabled",
    "release",
]
