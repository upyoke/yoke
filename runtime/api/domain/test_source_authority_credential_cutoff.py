from __future__ import annotations

import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import psycopg
import pytest
from psycopg import conninfo, sql

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import source_authority_cutover_support as support
from yoke_core.domain import source_authority_role_credentials as role_credentials


def _bundle(tmp_path: Path) -> credentials.SourceCredentialBundle:
    original = (
        "host=source.example dbname=yoke user=source_admin "
        "password=original-secret"
    )
    return credentials.prepare_or_load(
        tmp_path / "cutover.json", original_dsn=original,
        database="yoke", database_oid=42, admin_role="source_admin",
        service_stop_receipt="service-stopped", original_rolcanlogin=True,
    )


def test_bundle_is_owner_only_bound_and_idempotent(tmp_path: Path):
    bundle = _bundle(tmp_path)
    repeated = credentials.prepare_or_load(
        bundle.path, original_dsn=bundle.original_dsn,
        database="yoke", database_oid=42, admin_role="source_admin",
        service_stop_receipt="service-stopped", original_rolcanlogin=True,
    )

    assert repeated.cutover_dsn == bundle.cutover_dsn
    assert repeated.original_dsn == bundle.original_dsn
    assert bundle.path.stat().st_mode & 0o777 == 0o600
    assert "original-secret" not in repr(bundle)


def test_simultaneous_bundle_creation_loads_one_atomic_winner(
    monkeypatch, tmp_path: Path,
):
    path = tmp_path / "cutover.json"
    barrier = threading.Barrier(2)
    publish = credentials.credential_file.write_atomic_owner_only

    def synchronized_publish(selected, payload):
        barrier.wait(timeout=5)
        return publish(selected, payload)

    monkeypatch.setattr(
        credentials.credential_file,
        "write_atomic_owner_only",
        synchronized_publish,
    )

    def prepare():
        return credentials.prepare_or_load(
            path,
            original_dsn=(
                "host=source.example dbname=yoke user=source_admin "
                "password=original-secret"
            ),
            database="yoke", database_oid=42, admin_role="source_admin",
            service_stop_receipt="service-stopped", original_rolcanlogin=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        bundles = list(executor.map(lambda _index: prepare(), range(2)))

    assert bundles[0].cutover_dsn == bundles[1].cutover_dsn
    assert credentials.load_bound(path).cutover_dsn == bundles[0].cutover_dsn
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".*.tmp"))


def test_losing_bundle_publisher_fsyncs_winner_directory(
    monkeypatch, tmp_path: Path,
):
    path = tmp_path / "cutover.json"
    assert credentials.credential_file.write_atomic_owner_only(
        path, {"winner": True},
    ) is True
    fsyncs = []
    monkeypatch.setattr(
        credentials.credential_file, "fsync_directory", fsyncs.append,
    )

    assert credentials.credential_file.write_atomic_owner_only(
        path, {"winner": False},
    ) is False
    assert fsyncs == [tmp_path, tmp_path]


def test_bundle_publish_write_error_removes_secret_temporary(
    monkeypatch, tmp_path: Path,
):
    write = credentials.credential_file.write_new_owner_only

    def fail_after_write(path, payload):
        write(path, payload)
        raise OSError("simulated credential storage failure")

    monkeypatch.setattr(
        credentials.credential_file, "write_new_owner_only", fail_after_write,
    )

    with pytest.raises(OSError, match="credential storage failure"):
        credentials.credential_file.write_atomic_owner_only(
            tmp_path / "cutover.json", {"secret": "redacted"},
        )
    assert list(tmp_path.iterdir()) == []


def test_retirement_intent_is_fsynced_and_reused_before_database_commit(
    tmp_path: Path,
):
    bundle = _bundle(tmp_path)
    prepared = credentials.prepare_retirement(
        bundle, retirement_receipt="retirement-gates-green",
        retired_at="2026-07-14T12:00:00Z",
    )
    repeated = credentials.prepare_retirement(
        prepared, retirement_receipt="retirement-gates-green",
        retired_at="2099-01-01T00:00:00Z",
    )

    assert repeated.retired_at == "2026-07-14T12:00:00Z"
    assert repeated.retirement_receipt == "retirement-gates-green"
    assert repeated.retirement_phase == "intent"
    with pytest.raises(credentials.SourceCredentialError, match="another"):
        credentials.prepare_retirement(
            repeated, retirement_receipt="different-gates",
            retired_at=repeated.retired_at,
        )


def test_bundle_rejects_symlink_and_non_owner_mode(tmp_path: Path):
    bundle = _bundle(tmp_path)
    bundle.path.chmod(0o640)
    with pytest.raises(credentials.SourceCredentialError, match="owner-only"):
        credentials.load_bound(bundle.path)

    bundle.path.chmod(0o600)
    link = tmp_path / "linked.json"
    link.symlink_to(bundle.path)
    with pytest.raises(credentials.SourceCredentialError, match="owner-only"):
        credentials.load_bound(link)


def test_password_update_uses_bound_argument_and_redacts_failures(tmp_path: Path):
    bundle = _bundle(tmp_path)
    original_password = credentials.password_from_dsn(bundle.original_dsn)
    cutover_password = credentials.password_from_dsn(bundle.cutover_dsn)

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append((str(statement), params))
            if params is not None:
                raise psycopg.OperationalError("bound credential update failed")

    conn = Connection()
    with pytest.raises(psycopg.OperationalError) as caught:
        role_credentials.rotate_role_password(conn, bundle)

    client_sql = "\n".join(statement for statement, _params in conn.calls)
    evidence = client_sql + str(caught.value) + repr(bundle)
    assert original_password not in evidence
    assert cutover_password not in evidence
    assert conn.calls[-1][1] == (
        bundle.admin_role, cutover_password, True,
    )


@pytest.mark.parametrize(
    "error_type", (
        psycopg.errors.InvalidPassword,
        psycopg.errors.InvalidAuthorizationSpecification,
    ),
)
def test_explicit_login_refusal_is_accepted_as_cutoff_proof(
    monkeypatch, error_type,
):
    monkeypatch.setattr(
        support, "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(error_type("login refused")),
    )

    assert support.connection_or_none("password-bearing-dsn") is None


def test_real_role_rotation_and_nologin_rejection(tmp_path: Path):
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
        original_dsn = conninfo.make_conninfo(
            **{**base, "user": role, "password": "original-secret"}
        )
        bundle = credentials.prepare_or_load(
            tmp_path / "real-cutover.json", original_dsn=original_dsn,
            database=str(database), database_oid=int(database_oid),
            admin_role=role, service_stop_receipt="service-stopped",
            original_rolcanlogin=True,
        )
        try:
            before = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,),
            ).fetchone()[0]
            role_credentials.rotate_role_password(conn, bundle)
            conn.commit()
            rotated = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,),
            ).fetchone()[0]
            assert rotated and rotated != before
            live = psycopg.connect(bundle.cutover_dsn)
            try:
                assert role_credentials.prove_role_password_rotation(
                    live, bundle,
                ) in {"SCRAM-SHA-256", "md5"}
            finally:
                live.close()

            role_credentials.restore_role_credential(conn, bundle)
            conn.commit()
            restored = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,),
            ).fetchone()[0]
            assert restored and restored != rotated

            role_credentials.retire_role_credential(conn, bundle)
            conn.commit()
            assert conn.execute(
                "SELECT rolcanlogin, rolpassword FROM pg_authid WHERE rolname=%s",
                (role,),
            ).fetchone() == (False, None)
            role_credentials.prove_role_retired(conn, bundle)
            assert support.retirement_connection_or_none(
                bundle.cutover_dsn, role=role,
            ) is None
        finally:
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            conn.commit()


def test_unreachable_authority_is_not_accepted_as_cutoff_proof():
    with pytest.raises(psycopg.OperationalError):
        support.connection_or_none(
            "host=127.0.0.1 port=1 dbname=unreachable user=nobody "
            "password=unused connect_timeout=1"
        )


def test_availability_error_is_never_reclassified_as_login_refusal(monkeypatch):
    failure = psycopg.OperationalError("TLS negotiation failed")
    monkeypatch.setattr(
        support, "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(psycopg.OperationalError, match="TLS negotiation"):
        support.assert_connection_rejected(
            "source-dsn", message="credential still authenticates",
        )


@pytest.mark.parametrize(
    "message",
    (
        'FATAL: password authentication failed for user "source_admin"',
        'connection failed: TLS negotiation failed',
        'connection to server at "one" failed\n'
        'connection to server at "two" failed: '
        'FATAL: role "source_admin" is not permitted to log in',
    ),
)
def test_text_only_connection_failures_are_not_general_cutoff_proof(
    monkeypatch, message,
):
    monkeypatch.setattr(
        support, "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(psycopg.OperationalError(message)),
    )

    with pytest.raises(psycopg.OperationalError):
        support.connection_or_none(
            "host=source.example dbname=yoke user=source_admin password=unused"
        )


def test_retirement_fallback_accepts_only_single_host_exact_nologin(
    monkeypatch,
):
    refusal = (
        'connection failed: connection to server at "source.example", '
        'port 5432 failed: FATAL: role "source_admin" is not permitted to log in'
    )
    monkeypatch.setattr(
        support, "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(psycopg.OperationalError(refusal)),
    )

    assert support.retirement_connection_or_none(
        "host=source.example dbname=yoke user=source_admin password=unused",
        role="source_admin",
    ) is None
    with pytest.raises(psycopg.OperationalError):
        support.retirement_connection_or_none(
            "host=one,two dbname=yoke user=source_admin password=unused",
            role="source_admin",
        )
