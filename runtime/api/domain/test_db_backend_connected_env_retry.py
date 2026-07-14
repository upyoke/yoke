"""db_backend connect-retry path through the connected-env readiness layer.

Verifies that a failed connect is self-healed and retried exactly once (no
infinite loop), that a heal failure surfaces loudly, and that non-tunnel
failures propagate unchanged. All probe/heal seams are mocked.
"""

from __future__ import annotations

import psycopg
import pytest
import threading

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import cloud_db_secret_dsn
from yoke_core.domain import db_backend


@pytest.fixture(autouse=True)
def _reset_readiness_cache():
    cer.reset_cache()
    yield
    cer.reset_cache()


def _refused() -> psycopg.OperationalError:
    return psycopg.OperationalError(
        'connection to server at "127.0.0.1", port 6547 failed: Connection refused'
    )


# --- connect_with_readiness orchestration ----------------------------------
def test_retries_once_after_successful_heal(monkeypatch):
    calls = {"open": 0, "ensure": []}

    def opener():
        calls["open"] += 1
        if calls["open"] == 1:
            raise _refused()
        return "CONN"

    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: True)
    monkeypatch.setattr(
        cer,
        "ensure_ready",
        lambda *, force=False: (
            calls["ensure"].append(force)
            or cer.ReadinessResult(
                ok=True,
                environment="t",
                connector_kind=cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
                action="x",
                message="x",
            )
        ),
    )

    conn = cer.connect_with_readiness(opener)

    assert conn == "CONN"
    assert calls["open"] == 2  # initial + single retry
    assert calls["ensure"] == [False, True]  # proactive then forced heal


def test_retry_still_failing_raises_loud_no_infinite_loop(monkeypatch):
    calls = {"open": 0}

    def opener():
        calls["open"] += 1
        raise _refused()

    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: True)
    monkeypatch.setattr(
        cer,
        "ensure_ready",
        lambda *, force=False: cer.ReadinessResult(
            ok=True,
            environment="t",
            connector_kind=cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            action="x",
            message="x",
        ),
    )

    with pytest.raises(cer.ConnectedEnvUnavailable):
        cer.connect_with_readiness(opener)
    assert calls["open"] == 2  # exactly one retry, then give up


def test_heal_failure_propagates_before_retry(monkeypatch):
    calls = {"open": 0}

    def opener():
        calls["open"] += 1
        raise _refused()

    def ensure(*, force=False):
        if force:
            raise cer.ConnectedEnvUnavailable("tunnel restart failed")
        return cer.ReadinessResult(
            ok=True,
            environment="t",
            connector_kind=cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            action="x",
            message="x",
        )

    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: True)
    monkeypatch.setattr(cer, "ensure_ready", ensure)

    with pytest.raises(cer.ConnectedEnvUnavailable):
        cer.connect_with_readiness(opener)
    assert calls["open"] == 1  # heal failed -> no retry attempted


def test_non_tunnel_error_propagates_unchanged(monkeypatch):
    class Other(Exception):
        pass

    monkeypatch.setattr(
        cer,
        "ensure_ready",
        lambda *, force=False: cer.ReadinessResult(
            ok=True,
            environment=None,
            connector_kind=cer.CONNECTOR_UNMANAGED,
            action="noop",
            message="x",
        ),
    )
    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: False)

    def opener():
        raise Other("boom")

    with pytest.raises(Other):
        cer.connect_with_readiness(opener)


def test_proactive_unavailable_fails_loud_without_opening(monkeypatch):
    opened = {"n": 0}

    def opener():
        opened["n"] += 1
        return "CONN"

    def ensure(*, force=False):
        raise cer.ConnectedEnvUnavailable("tunnel down at acquisition")

    monkeypatch.setattr(cer, "ensure_ready", ensure)

    with pytest.raises(cer.ConnectedEnvUnavailable):
        cer.connect_with_readiness(opener)
    assert opened["n"] == 0  # never opened when acquisition-time readiness fails


# --- db_backend.connect / connect_psycopg wiring ---------------------------
def test_db_backend_connect_self_heals_and_retries(monkeypatch):
    calls = {"open": 0}

    def fake_native_connect(dsn, *, autocommit=False):
        calls["open"] += 1
        if calls["open"] == 1:
            raise _refused()
        return "NATIVE"

    monkeypatch.setattr(db_backend, "_open_native_postgres", fake_native_connect)
    monkeypatch.setattr(
        db_backend,
        "resolve_pg_dsn",
        lambda *a, **k: "host=127.0.0.1 port=6547 dbname=x",
    )
    monkeypatch.setattr(
        cer,
        "ensure_ready",
        lambda *, force=False: cer.ReadinessResult(
            ok=True,
            environment="t",
            connector_kind=cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            action="x",
            message="x",
        ),
    )
    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: True)

    conn = db_backend.connect()

    assert conn == "NATIVE"
    assert calls["open"] == 2


def test_db_backend_connect_routes_opener_through_readiness(monkeypatch):
    captured = {}

    def fake_cwr(opener):
        captured["opener"] = opener
        return "WRAPPED"

    monkeypatch.setattr(cer, "connect_with_readiness", fake_cwr)
    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda *a, **k: "host=127.0.0.1 dbname=x"
    )

    assert db_backend.connect() == "WRAPPED"
    assert callable(captured["opener"])


def test_db_backend_connect_psycopg_routes_through_readiness(monkeypatch):
    captured = {}

    def fake_cwr(opener):
        captured["opener"] = opener
        return "RAW"

    monkeypatch.setattr(cer, "connect_with_readiness", fake_cwr)
    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda *a, **k: "host=127.0.0.1 dbname=x"
    )

    assert db_backend.connect_psycopg() == "RAW"
    assert callable(captured["opener"])


def test_bound_pg_dsn_is_nested_context_local_and_resets(monkeypatch):
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "dbname=ambient")
    assert db_backend.resolve_pg_dsn() == "dbname=ambient"
    with db_backend.bound_pg_dsn("dbname=outer"):
        assert db_backend.resolve_pg_dsn() == "dbname=outer"
        with db_backend.bound_pg_dsn("dbname=inner"):
            assert db_backend.resolve_pg_dsn() == "dbname=inner"
        assert db_backend.resolve_pg_dsn() == "dbname=outer"
    assert db_backend.resolve_pg_dsn() == "dbname=ambient"

    barrier = threading.Barrier(2)
    observed = {}

    def resolve(label):
        with db_backend.bound_pg_dsn(f"dbname={label}"):
            barrier.wait()
            observed[label] = db_backend.resolve_pg_dsn()

    workers = [threading.Thread(target=resolve, args=(label,)) for label in ("a", "b")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert observed == {"a": "dbname=a", "b": "dbname=b"}


def test_explicit_connect_psycopg_bypasses_unrelated_readiness(monkeypatch):
    monkeypatch.setattr(
        cer,
        "connect_with_readiness",
        lambda _opener: (_ for _ in ()).throw(AssertionError("must not probe")),
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: "DIRECT")
    assert db_backend.connect_psycopg("dbname=staging") == "DIRECT"


def test_explicit_connect_psycopg_never_uses_managed_secret_fallback(monkeypatch):
    monkeypatch.setenv(cloud_db_secret_dsn.DB_SECRET_ARN_ENV, "arn")
    monkeypatch.setattr(
        cloud_db_secret_dsn,
        "resolve_previous_dsn_from_env",
        lambda: (_ for _ in ()).throw(AssertionError("must not load previous")),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            psycopg.errors.InvalidPassword("password rejected")
        ),
    )

    with pytest.raises(psycopg.errors.InvalidPassword):
        db_backend.connect_psycopg("dbname=explicit")


def test_managed_secret_invalid_password_refreshes_then_uses_previous(monkeypatch):
    attempts = []
    resolved = iter(("dbname=current-cached", "dbname=current-refreshed"))

    monkeypatch.delenv(db_backend.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.setenv(cloud_db_secret_dsn.DB_SECRET_ARN_ENV, "arn")
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: next(resolved))
    monkeypatch.setattr(cloud_db_secret_dsn, "clear_cache", lambda: None)
    monkeypatch.setattr(
        cloud_db_secret_dsn,
        "resolve_previous_dsn_from_env",
        lambda: "dbname=previous",
    )

    def fake_native_connect(dsn, *, autocommit=False):  # noqa: ARG001
        attempts.append(dsn)
        if dsn != "dbname=previous":
            raise psycopg.errors.InvalidPassword("password rejected")
        return "PREVIOUS-CONN"

    monkeypatch.setattr(db_backend, "_open_native_postgres", fake_native_connect)

    assert db_backend.connect() == "PREVIOUS-CONN"
    assert attempts == [
        "dbname=current-cached",
        "dbname=current-refreshed",
        "dbname=previous",
    ]


def test_connected_managed_secret_refreshes_then_uses_previous(monkeypatch):
    attempts = []
    monkeypatch.delenv(db_backend.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.delenv(cloud_db_secret_dsn.DB_SECRET_ARN_ENV, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.managed_secret_selected",
        lambda: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.resolve_previous_postgres_dsn",
        lambda: "dbname=connected-previous",
    )
    monkeypatch.setattr(
        db_backend,
        "resolve_pg_dsn",
        lambda: "dbname=connected-refreshed",
    )
    monkeypatch.setattr(cloud_db_secret_dsn, "clear_cache", lambda: None)

    def opener(dsn):
        attempts.append(dsn)
        if dsn != "dbname=connected-previous":
            raise psycopg.errors.InvalidPassword("password rejected")
        return "CONNECTED-PREVIOUS"

    assert (
        db_backend._open_with_managed_rotation_recovery(
            opener, "dbname=connected-cached"
        )
        == "CONNECTED-PREVIOUS"
    )
    assert attempts == [
        "dbname=connected-cached",
        "dbname=connected-refreshed",
        "dbname=connected-previous",
    ]


def test_managed_secret_does_not_fallback_for_other_connection_errors(monkeypatch):
    monkeypatch.delenv(db_backend.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.setenv(cloud_db_secret_dsn.DB_SECRET_ARN_ENV, "arn")
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: "dbname=current")
    monkeypatch.setattr(
        cloud_db_secret_dsn,
        "resolve_previous_dsn_from_env",
        lambda: (_ for _ in ()).throw(AssertionError("must not load previous")),
    )
    monkeypatch.setattr(
        db_backend,
        "_open_native_postgres",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_refused()),
    )
    monkeypatch.setattr(cer, "is_local_tunnel_connection_error", lambda exc: False)

    with pytest.raises(psycopg.OperationalError):
        db_backend.connect()
