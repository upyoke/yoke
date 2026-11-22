"""Build the import schema privately and publish it atomically."""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager

import psycopg
from psycopg import conninfo, sql

from yoke_core.domain.universe_portability_common import (
    UniversePortabilityError,
    remaining_timeout,
)
from yoke_core.domain.universe_portability_restore_contract import (
    restore_error_description,
)

IMPORT_SCHEMA = "yoke_import_staging"
_log = logging.getLogger("yoke.universe.portability")


def bounded_dsn(dsn: str, timeout_s: float, schema: str) -> str:
    options = conninfo.conninfo_to_dict(dsn)
    timeout_ms = max(1, int(timeout_s * 1000))
    options["options"] = " ".join(filter(None, (
        options.get("options"),
        f"-c statement_timeout={timeout_ms} -c lock_timeout={timeout_ms}"
        f" -c search_path={schema},pg_catalog",
    )))
    options["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    return conninfo.make_conninfo(**options)


def _drop_staging(conn: psycopg.Connection) -> None:
    conn.execute(
        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(IMPORT_SCHEMA))
    )


def _schema_acl(conn: psycopg.Connection, schema: str):
    return conn.execute(
        "SELECT CASE WHEN acl.grantee = 0 THEN NULL ELSE pg_get_userbyid(acl.grantee) END,"
        " acl.privilege_type, acl.is_grantable, pg_get_userbyid(acl.grantor)"
        " FROM pg_namespace, LATERAL aclexplode(nspacl) WITH ORDINALITY"
        " AS acl(grantor, grantee, privilege_type, is_grantable, position)"
        " WHERE nspname = %s ORDER BY acl.position",
        (schema,),
    ).fetchall()


def _acl_grantee(role: str | None) -> sql.Composable:
    return sql.SQL("PUBLIC") if role is None else sql.Identifier(role)


def _revoke_schema_grants(conn: psycopg.Connection, schema: str, grantees) -> None:
    for grantee in dict.fromkeys(grantees):
        conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {} CASCADE").format(
            sql.Identifier(schema), _acl_grantee(grantee),
        ))


@contextmanager
def staged_restore_schema(dsn: str, deadline: float):
    """Hold a session lock through bootstrap, load, publication and cleanup."""
    from yoke_contracts.schema_authority import serving_build_authority
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
    from yoke_core.domain.migration_content_restore_guards import (
        truncate_trusted_schema_bootstrap_rows,
    )

    phase = "staging setup"
    try:
        with psycopg.connect(
            bounded_dsn(dsn, remaining_timeout(deadline, phase), IMPORT_SCHEMA),
            autocommit=True,
        ) as conn:
            acquired, = conn.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s), 0)", (IMPORT_SCHEMA,),
            ).fetchone()
            if not acquired:
                raise UniversePortabilityError(
                    "universe import already in progress; wait for it to finish and retry"
                )
            try:
                with conn.transaction():
                    _drop_staging(conn)
                    row = conn.execute(
                        "SELECT pg_get_userbyid(nspowner), obj_description(oid, 'pg_namespace') "
                        "FROM pg_namespace "
                        "WHERE nspname = 'public'"
                    ).fetchone()
                    if row is None:
                        raise UniversePortabilityError(
                            "restore destination has no public schema; initialize the database and retry"
                        )
                    conn.execute(
                        sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                            sql.Identifier(IMPORT_SCHEMA), sql.Identifier(row[0]),
                        )
                    )
                    # Per-role default privileges can grant access to new schemas.
                    _revoke_schema_grants(
                        conn, IMPORT_SCHEMA,
                        (grantee for grantee, *_ in _schema_acl(conn, IMPORT_SCHEMA)
                         if grantee != row[0]),
                    )
                    if row[1] is not None:
                        conn.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                            sql.Identifier(IMPORT_SCHEMA), sql.Literal(row[1]),
                        ))
                phase = "trusted schema initialization"
                with serving_build_authority(private_schema=True):
                    run_init_chain_at_dsn(
                        bounded_dsn(dsn, remaining_timeout(deadline, phase), IMPORT_SCHEMA),
                        emit=lambda line: _log.debug("trusted schema init: %s", line),
                    )
                phase = "bootstrap row cleanup"
                with conn.transaction():
                    truncate_trusted_schema_bootstrap_rows(conn)
                phase = "data load and publication"
                yield
            except BaseException:
                try:
                    _drop_staging(conn)
                except psycopg.Error as exc:
                    _log.error("restore staging cleanup failed: %s", restore_error_description(exc))
                    raise UniversePortabilityError(
                        "universe restore staging cleanup failed: "
                        f"{restore_error_description(exc)}; retry after restoring database access"
                    ) from exc
                raise
    except UniversePortabilityError:
        raise
    except psycopg.Error as exc:
        raise UniversePortabilityError(
            f"universe restore {phase} failed: {restore_error_description(exc)}; "
            "correct the database error and retry"
        ) from exc
    except Exception as exc:
        if phase == "trusted schema initialization":
            raise UniversePortabilityError(
                f"universe restore {phase} failed: {restore_error_description(exc)}; "
                "correct the initialization error and retry"
            ) from exc
        raise


def publish_restore_schema(conn: psycopg.Connection, schema: str) -> None:
    """Preserve public's grants and replace its contents in the load transaction."""
    target = sql.Identifier(schema)
    owner, explicit_acl = conn.execute(
        "SELECT pg_get_userbyid(nspowner), nspacl IS NOT NULL "
        "FROM pg_namespace WHERE nspname = 'public'"
    ).fetchone()
    if explicit_acl:
        grants = _schema_acl(conn, "public")
        # A fresh schema starts with owner privileges. Restore any explicit
        # revocation as well as grants from public's catalog.
        _revoke_schema_grants(conn, schema, [owner])
        for grantee, privilege, grantable, grantor in grants:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(grantor)))
            conn.execute(
                sql.SQL("GRANT {} ON SCHEMA {} TO {}{}").format(
                    sql.SQL(privilege), target,
                    _acl_grantee(grantee),
                    sql.SQL(" WITH GRANT OPTION" if grantable else ""),
                )
            )
        conn.execute("RESET ROLE")
        if set(_schema_acl(conn, schema)) != set(grants):
            raise UniversePortabilityError(
                "universe restore cannot reproduce public's schema grants; "
                "retry with a database role authorized to reproduce those grants"
            )
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute(sql.SQL("ALTER SCHEMA {} RENAME TO public").format(target))
