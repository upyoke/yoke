"""Actual PostgreSQL source role rotation and retirement custody."""

from __future__ import annotations
import os
from pathlib import Path
import uuid
import psycopg
import pytest
from psycopg import conninfo, sql
from runtime.api.fixtures import pg_testdb
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import source_authority_role_credentials as role_credentials


def test_real_role_rotation_and_nologin_rejection(
    tmp_path: Path,
    cluster_role_authority,
):
    with pg_testdb.test_database() as conn:
        database, database_oid = conn.execute(
            "SELECT current_database(), oid FROM pg_database "
            "WHERE datname=current_database()"
        ).fetchone()
        role = f"source_cutover_{uuid.uuid4().hex[:12]}"
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN SUPERUSER PASSWORD 'initial-server-secret'"
            ).format(sql.Identifier(role))
        )
        conn.commit()
        base = conninfo.conninfo_to_dict(os.environ["YOKE_PG_DSN"])
        # The strict retirement proof deliberately refuses psycopg's
        # no-SQLSTATE aggregate from several resolved addresses. Pin this
        # real-authentication test to one loopback target so it exercises the
        # server's explicit 28P01 rejection instead of an aggregate wrapper.
        if base.get("host") == "localhost":
            base["hostaddr"] = "127.0.0.1"
        original_dsn = conninfo.make_conninfo(
            **{**base, "user": role, "password": "original-secret"}
        )
        bundle = credentials.prepare_or_load(
            tmp_path / "real-cutover.json",
            original_dsn=original_dsn,
            database=str(database),
            database_oid=int(database_oid),
            admin_role=role,
            service_stop_receipt="service-stopped",
            original_rolcanlogin=True,
        )
        try:
            before = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s",
                (role,),
            ).fetchone()[0]
            role_credentials.rotate_role_password(conn, bundle)
            conn.commit()
            rotated = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s",
                (role,),
            ).fetchone()[0]
            assert rotated and rotated != before
            live = psycopg.connect(bundle.cutover_dsn)
            try:
                assert (
                    role_credentials.prove_role_password_rotation(
                        live,
                        bundle,
                    )
                    == "postgres-single-verifier-cutover-reconnect"
                )
            finally:
                live.close()

            role_credentials.restore_role_credential(conn, bundle)
            conn.commit()
            restored = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s",
                (role,),
            ).fetchone()[0]
            assert restored and restored != rotated

            role_credentials.retire_role_credential(conn, bundle)
            conn.commit()
            assert conn.execute(
                "SELECT rolcanlogin, rolpassword FROM pg_authid WHERE rolname=%s",
                (role,),
            ).fetchone() == (False, None)
            assert role_credentials.prove_role_retired(conn, bundle) == {
                "method": "live-role-catalog-state",
                "login_disabled": True,
                "password_cleared": True,
            }
            # The failed login is a behavior check, not retirement evidence:
            # some libpq builds expose the server rejection only through an
            # OperationalError with no SQLSTATE.
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(bundle.cutover_dsn)
        finally:
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            conn.commit()
