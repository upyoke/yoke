"""PostgreSQL admission fence and its private frozen export database."""

import re
import time
import uuid

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from yoke_core.domain import db_backend


def _copy_name(state):
    name = state["copy"]
    if name == state["name"] or not re.fullmatch(r"yoke_pause_[0-9a-f]{32}", name):
        raise RuntimeError(
            "universe_pause_copy_invalid: restore the private pause record before retrying; no database was removed"
        )
    return name


def maintenance_dsn(dsn):
    database = conninfo_to_dict(dsn).get("dbname")
    if not database or database in {"postgres", "template0", "template1"}:
        raise RuntimeError(
            "universe_pause_database_invalid: use a dedicated universe database, then retry"
        )
    return make_conninfo(dsn, dbname="postgres")


def connect(dsn):
    return db_backend.connect_psycopg(maintenance_dsn(dsn), autocommit=True)


def plan(dsn):
    name = conninfo_to_dict(dsn)["dbname"]
    with connect(dsn) as conn:
        row = conn.execute(
            "SELECT d.oid, d.datallowconn, r.rolsuper, r.rolcreatedb, "
            "d.datdba=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
            "FROM pg_database d JOIN pg_roles r ON r.rolname=current_user WHERE d.datname=%s",
            (name,),
        ).fetchone()
        if not row or not row[1] or not (row[2] or (row[3] and row[4])):
            raise RuntimeError(
                "universe_pause_authority_required: use the source database owner with CREATE DATABASE and session termination permission, then retry"
            )
        return {
            "name": name,
            "oid": int(row[0]),
            "copy": "yoke_pause_" + uuid.uuid4().hex,
            "ready": False,
        }


def _identity(conn, state):
    row = conn.execute(
        "SELECT oid FROM pg_database WHERE datname=%s", (state["name"],)
    ).fetchone()
    if not row or int(row[0]) != state["oid"]:
        raise RuntimeError(
            "universe_pause_identity_changed: restore the recorded source database before resuming"
        )


def allow(conn, state, enabled):
    _identity(conn, state)
    conn.execute(
        sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS {}").format(
            sql.Identifier(state["name"]), sql.Literal(enabled)
        )
    )


def drain(conn, name, *, timeout_s=30):
    deadline = time.monotonic() + timeout_s
    while True:
        rows = conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE datname=%s", (name,)
        ).fetchall()
        if not rows:
            return
        for row in rows:
            conn.execute("SELECT pg_terminate_backend(%s)", (row[0],))
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "universe_pause_drain_timeout: check session termination permission and retry export or Resume"
            )
        time.sleep(0.05)


def freeze(dsn, state, *, timeout_s=30):
    with connect(dsn) as conn:
        allow(conn, state, False)
        drain(conn, state["name"], timeout_s=timeout_s)
        if not state["ready"]:
            # The random copy name is durably recorded before any creation.
            # A retry removes only this operation's incomplete copy.
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(_copy_name(state))
                )
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {} ALLOW_CONNECTIONS true").format(
                    sql.Identifier(_copy_name(state)), sql.Identifier(state["name"])
                )
            )
            conn.execute(
                sql.SQL(
                    "ALTER DATABASE {} SET default_transaction_read_only=on"
                ).format(sql.Identifier(_copy_name(state)))
            )
    state["ready"] = True


def confirm(dsn, state):
    with connect(dsn) as conn:
        _identity(conn, state)
        row = conn.execute(
            "SELECT datallowconn, (SELECT count(*) FROM pg_stat_activity WHERE datname=%s) "
            "FROM pg_database WHERE oid=%s",
            (state["name"], state["oid"]),
        ).fetchone()
        if not row or row[0] or row[1] != 0 or not state["ready"]:
            raise RuntimeError(
                "universe_pause_unconfirmed: retry paused export after stopping database clients"
            )


def read_dsn(dsn, state):
    if not state["ready"]:
        raise RuntimeError(
            "universe_pause_copy_unavailable: retry paused export from the source terminal, or run `yoke universe resume`"
        )
    options = conninfo_to_dict(dsn).get("options", "")
    return make_conninfo(
        dsn,
        dbname=_copy_name(state),
        options=f"{options} -c default_transaction_read_only=on",
    )


def reopen(dsn, state):
    with connect(dsn) as conn:
        allow(conn, state, True)


def cleanup(dsn, state):
    with connect(dsn) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(_copy_name(state))
            )
        )
