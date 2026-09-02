"""Which failures the readiness layer owns, and which it must pass through.

Split from ``test_connected_env_readiness`` so both files stay under the
authored-line cap. The subject here is classification: a server that
answered and refused proves the forward works, while a forward that never
answered is the only failure this layer heals.
"""

from __future__ import annotations

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_readiness_tunnel as cer_t
from yoke_core.domain import yoke_connected_env


# --- error classifiers -----------------------------------------------------
def test_is_local_tunnel_connection_error_false_when_explicit_dsn(monkeypatch):
    import psycopg

    monkeypatch.setenv(cer_c.PG_DSN_ENV, "host=127.0.0.1 dbname=x")
    refused = psycopg.OperationalError("Connection refused")
    assert cer.is_local_tunnel_connection_error(refused) is False


def test_is_connection_unavailable_error_is_broad(monkeypatch):
    import psycopg

    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    assert cer.is_connection_unavailable_error(cer.ConnectedEnvUnavailable("x")) is True
    assert cer.is_connection_unavailable_error(
        yoke_connected_env.ConnectedEnvError("bad binding")) is True
    assert cer.is_connection_unavailable_error(
        psycopg.OperationalError("Connection refused")) is True
    assert cer.is_connection_unavailable_error(ValueError("template bug")) is False


# --- probe classification ----------------------------------------------------
def test_probe_counts_server_answered_refusal_as_reachable(monkeypatch):
    """An auth/database refusal proves the forward works; reachability is the
    only concern of this layer. Credential freshness (rotation windows)
    belongs to connection acquisition."""
    monkeypatch.setattr(
        cer_t, "_port_is_listening", lambda host, port, timeout=1.0: True)

    def raise_auth(dsn, **kwargs):
        raise RuntimeError(
            'connection failed: FATAL: password authentication failed '
            'for user "u"'
        )

    monkeypatch.setattr(cer_t, "_probe_postgres", raise_auth)
    assert cer_t._probe_failure("host=127.0.0.1 port=6547 dbname=d") is None


def test_probe_counts_sqlstate_auth_refusal_as_reachable(monkeypatch):
    monkeypatch.setattr(
        cer_t, "_port_is_listening", lambda host, port, timeout=1.0: True)

    class _AuthRefused(Exception):
        sqlstate = "28P01"

    def raise_auth(dsn, **kwargs):
        raise _AuthRefused("server said no")

    monkeypatch.setattr(cer_t, "_probe_postgres", raise_auth)
    assert cer_t._probe_failure("host=127.0.0.1 port=6547 dbname=d") is None


def test_probe_reports_refused_connection_as_down(monkeypatch):
    monkeypatch.setattr(
        cer_t, "_port_is_listening", lambda host, port, timeout=1.0: True)

    def raise_refused(dsn, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(cer_t, "_probe_postgres", raise_refused)
    failure = cer_t._probe_failure("host=127.0.0.1 port=6547 dbname=d")
    assert failure is not None
    assert "OSError" in failure


def test_server_answered_refusal_is_not_a_tunnel_error(monkeypatch):
    """An auth refusal propagates to credential recovery instead of
    triggering a pointless tunnel restart + 'unreachable' rewrap."""
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    class _AuthRefused(Exception):
        pass

    exc = _AuthRefused(
        'connection failed: FATAL: password authentication failed for '
        'user "u"'
    )
    assert cer.is_local_tunnel_connection_error(exc) is False
