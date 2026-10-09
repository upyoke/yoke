"""Source role credential rotation and cutoff proof."""

from __future__ import annotations
from pathlib import Path
import psycopg
import pytest
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import source_authority_cutover_support as support
from yoke_core.domain import source_authority_role_credentials as role_credentials
from runtime.api.domain.test_source_authority_credential_cutoff import _bundle


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
        bundle.admin_role,
        cutover_password,
        True,
    )


def test_rotation_proof_uses_cutover_reconnect_without_password_catalog(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)

    class Result:
        @staticmethod
        def fetchone():
            return (bundle.admin_role,)

    class Connection:
        @staticmethod
        def execute(statement, params=None):
            assert statement == "SELECT current_user"
            assert params is None
            return Result()

    assert (
        role_credentials.prove_role_password_rotation(
            Connection(),
            bundle,
        )
        == "postgres-single-verifier-cutover-reconnect"
    )


@pytest.mark.parametrize(
    "error_type",
    (
        psycopg.errors.InvalidPassword,
        psycopg.errors.InvalidAuthorizationSpecification,
    ),
)
def test_explicit_login_refusal_is_accepted_as_cutoff_proof(
    monkeypatch,
    error_type,
):
    monkeypatch.setattr(
        support,
        "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(error_type("login refused")),
    )

    assert support.connection_or_none("password-bearing-dsn") is None


def test_unreachable_authority_is_not_accepted_as_cutoff_proof():
    with pytest.raises(psycopg.OperationalError):
        support.connection_or_none(
            "host=127.0.0.1 port=1 dbname=unreachable user=nobody "
            "password=unused connect_timeout=1"
        )


def test_availability_error_is_never_reclassified_as_login_refusal(monkeypatch):
    failure = psycopg.OperationalError("TLS negotiation failed")
    monkeypatch.setattr(
        support,
        "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(psycopg.OperationalError, match="TLS negotiation"):
        support.assert_connection_rejected(
            "source-dsn",
            message="credential still authenticates",
        )


@pytest.mark.parametrize(
    "message",
    (
        'FATAL: password authentication failed for user "source_admin"',
        "connection failed: TLS negotiation failed",
        'connection to server at "one" failed\n'
        'connection to server at "two" failed: '
        'FATAL: role "source_admin" is not permitted to log in',
    ),
)
def test_text_only_connection_failures_are_not_general_cutoff_proof(
    monkeypatch,
    message,
):
    monkeypatch.setattr(
        support,
        "admin_connection",
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
        support,
        "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(psycopg.OperationalError(refusal)),
    )

    assert (
        support.retirement_connection_or_none(
            "host=source.example dbname=yoke user=source_admin password=unused",
            role="source_admin",
        )
        is None
    )
    with pytest.raises(psycopg.OperationalError):
        support.retirement_connection_or_none(
            "host=one,two dbname=yoke user=source_admin password=unused",
            role="source_admin",
        )


@pytest.mark.parametrize(
    "message",
    (
        'connection failed: connection to server at "source.example", '
        "port 5432 failed: FATAL: password authentication failed for user "
        '"source_admin"',
        "connection failed: TLS negotiation failed",
        "connection failed: connection timed out",
        "connection failed: TLS negotiation failed: FATAL: role "
        '"source_admin" is not permitted to log in',
    ),
)
def test_retirement_fallback_rejects_unstructured_failures(
    monkeypatch,
    message,
):
    failure = psycopg.OperationalError(message)
    assert failure.sqlstate is None
    monkeypatch.setattr(
        support,
        "admin_connection",
        lambda _dsn: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(psycopg.OperationalError) as caught:
        support.retirement_connection_or_none(
            "host=source.example dbname=yoke user=source_admin password=unused",
            role="source_admin",
        )
    assert caught.value is failure


@pytest.mark.parametrize(
    "role_state",
    (
        (True, None),
        (False, "SCRAM-SHA-256$redacted"),
    ),
)
def test_live_retirement_proof_requires_disabled_login_and_cleared_password(
    tmp_path: Path,
    role_state,
):
    bundle = _bundle(tmp_path)

    class Result:
        def fetchone(self):
            return role_state

    class Connection:
        def execute(self, _statement, _params):
            return Result()

    with pytest.raises(
        credentials.SourceCredentialError,
        match="does not prove permanent credential retirement",
    ):
        role_credentials.prove_role_retired(Connection(), bundle)
