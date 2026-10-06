"""Collector identity and rate admission survive process-local state loss."""

from runtime.api.domain.test_sign_in_resolution import conn as actor_database
from yoke_core.domain.frontend_events_storage import (
    RATE_REQUESTS,
    admit_client,
    collector_identity,
)

conn = actor_database


def test_collector_signing_key_is_durable_and_publishable_key_is_not_secret(conn):
    org, public, secret = collector_identity(conn)
    assert len(secret) >= 32
    assert public != secret
    assert collector_identity(conn) == (org, public, secret)
    conn.rollback()
    assert collector_identity(conn) == (org, public, secret)


def test_rate_admission_is_shared_and_windows_expire(conn):
    org, _, _ = collector_identity(conn)
    for _ in range(RATE_REQUESTS):
        assert admit_client(conn, org_id=org, client="transport-client", now=120) == 0
    assert admit_client(conn, org_id=org, client="transport-client", now=121) == 59
    assert admit_client(conn, org_id=org, client="another-client", now=121) == 0
    assert admit_client(conn, org_id=org, client="transport-client", now=180) == 0
