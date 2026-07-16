from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_readiness_tunnel as cer_t
from yoke_core.domain import machine_config
from yoke_core.domain import yoke_connected_env


@pytest.fixture(autouse=True)
def _reset_readiness_cache():
    """The readiness cache is process-global; reset around every test."""
    cer.reset_cache()
    yield
    cer.reset_cache()


def _write_binding(tmp_path: Path, *, with_tunnel: bool = True,
                   host: str = "127.0.0.1", port: int = 6547,
                   backend: str = "postgres") -> Path:
    dsn_file = tmp_path / "test.dsn"
    dsn_file.write_text(f"host={host} port={port} user=u dbname=test_db\n",
                        encoding="utf-8")
    connection: dict = {"host": host, "port": port}
    if with_tunnel:
        connection["tunnel"] = {
            "kind": "ssh",
            "bastion": "ubuntu@10.0.0.1",
            "identity_file": str(tmp_path / "key.pem"),
            "remote_host": "aurora.example.internal",
            "remote_port": 5432,
        }
    binding = {
        "schema_version": 1,
        "active_env": "cloud-test",
        "connections": {
            "cloud-test": {
                "transport": "local-postgres" if backend == "postgres" else backend,
                "credential_source": {"kind": "dsn_file", "path": str(dsn_file)},
                "postgres": connection,
            },
        },
        "projects": {
            str(tmp_path.resolve()): {
                "project_id": 1,
            },
        },
    }
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding), encoding="utf-8")
    return path


@pytest.fixture
def managed_env(tmp_path, monkeypatch):
    """Bind a managed local-SSH-tunnel connector with explicit DSN cleared."""
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(cer_c.PG_DSN_FILE_ENV, raising=False)
    binding = _write_binding(tmp_path)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    return binding


# --- 1. explicit DSN -> noop, no SSH --------------------------------------
def test_explicit_dsn_noops_and_never_starts_ssh(monkeypatch):
    monkeypatch.setenv(cer_c.PG_DSN_ENV, "host=127.0.0.1 port=6547 dbname=x")
    probes: list = []
    restarts: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: probes.append(dsn))
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: restarts.append(spec))

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.connector_kind == cer.CONNECTOR_UNMANAGED
    assert result.action == cer_c.ACTION_NOOP_EXPLICIT_DSN
    assert probes == [] and restarts == []


def test_explicit_dsn_file_also_noops(monkeypatch, tmp_path):
    dsn_file = tmp_path / "x.dsn"
    dsn_file.write_text("host=127.0.0.1 dbname=x\n", encoding="utf-8")
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.setenv(cer_c.PG_DSN_FILE_ENV, str(dsn_file))
    result = cer.ensure_ready(force=True)
    assert result.action == cer_c.ACTION_NOOP_EXPLICIT_DSN


# --- 2. healthy probe -> ok, no restart -----------------------------------
def test_healthy_probe_returns_ok_without_restart(managed_env, monkeypatch):
    probes: list = []
    restarts: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: probes.append(dsn))
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: restarts.append(spec))

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.connector_kind == cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG
    assert result.action == cer_c.ACTION_PROBE_OK
    assert len(probes) == 1
    assert restarts == []


# --- 3. probe fails then restart succeeds ----------------------------------
def test_probe_fail_then_restart_succeeds(managed_env, monkeypatch):
    results = iter(["down (test)", "down (test)", "down (test)", "down (test)", None])
    probes: list = []
    restarts: list = []

    def fake_probe(dsn):
        probes.append(dsn)
        return next(results)

    monkeypatch.setattr(cer_t, "_probe_failure", fake_probe)
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: restarts.append(spec))
    monkeypatch.setattr(cer_t.time, "sleep", lambda delay: None)

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.action == cer_c.ACTION_RESTARTED
    assert len(restarts) == 1
    assert len(probes) == 5  # initial, confirm-down window, post-restart


# --- 4. restart fails -> raises ConnectedEnvUnavailable, redacted ----------
def test_restart_then_still_down_raises_redacted(managed_env, monkeypatch):
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: "down (test)")
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: None)  # "started" but still down

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        cer.ensure_ready(force=True)

    msg = str(excinfo.value)
    assert "unreachable" in msg.lower()
    # The final verdict names the last probe cause.
    assert "cause=down (test)" in msg
    # Redaction: the DSN body must never leak into the loud error.
    assert "dbname=test_db" not in msg
    assert "password" not in msg.lower()


def test_restart_process_failure_propagates(managed_env, monkeypatch):
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: "down (test)")

    def boom(spec):
        raise cer.ConnectedEnvUnavailable(
            "ssh tunnel start failed (rc=255) [local=127.0.0.1:6547 "
            "bastion=ubuntu@10.0.0.1 remote=aurora.example.internal:5432]: "
            "Permission denied (publickey)"
        )

    monkeypatch.setattr(cer_t, "_restart_tunnel", boom)

    with pytest.raises(cer.ConnectedEnvUnavailable):
        cer.ensure_ready(force=True)


def test_redact_masks_password_and_credentials():
    masked = cer.redact("host=127.0.0.1 password=hunter2 dbname=x")
    assert "hunter2" not in masked
    assert "password=***" in masked
    url = cer.redact("postgresql://user:s3cret@host:5432/db")
    assert "s3cret" not in url


# --- cache -----------------------------------------------------------------
def test_cache_serves_second_call_without_reprobe(managed_env, monkeypatch):
    probes: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: probes.append(dsn))
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: None)

    first = cer.ensure_ready(force=False)
    second = cer.ensure_ready(force=False)

    assert first.ok and second.ok
    assert len(probes) == 1  # second served from cache
    assert second.action == cer_c.ACTION_CACHED

    cer.ensure_ready(force=True)  # force bypasses cache
    assert len(probes) == 2


def test_reset_cache_forces_reprobe(managed_env, monkeypatch):
    probes: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: probes.append(dsn))
    cer.ensure_ready(force=False)
    cer.reset_cache()
    cer.ensure_ready(force=False)
    assert len(probes) == 2


# --- status ----------------------------------------------------------------
def test_status_reports_down_without_restarting(managed_env, monkeypatch):
    restarts: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: "down (test)")
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: restarts.append(spec))

    result = cer.status()

    assert result.ok is False
    assert result.action == cer_c.ACTION_PROBE_FAILED
    assert restarts == []  # status never restarts
    # A failed probe names its cause so an auth/TLS refusal is
    # distinguishable from a dead forward without a manual psycopg probe.
    assert "cause=down (test)" in (result.redacted_detail or "")


def test_status_ok_when_probe_healthy(managed_env, monkeypatch):
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: None)
    result = cer.status()
    assert result.ok
    assert result.action == cer_c.ACTION_PROBE_OK


# --- unsupported / unmanaged connectors ------------------------------------
def test_remote_postgres_is_unmanaged_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(cer_c.PG_DSN_FILE_ENV, raising=False)
    binding = _write_binding(tmp_path, host="10.20.30.40", with_tunnel=False)
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    probes: list = []
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: probes.append(dsn))

    result = cer.ensure_ready(force=True)

    assert result.ok
    assert result.connector_kind == cer.CONNECTOR_REMOTE_POSTGRES
    assert result.action == cer_c.ACTION_NOOP_UNSUPPORTED
    assert probes == []  # unmanaged -> never probes


def test_no_binding_is_unmanaged_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(cer_c.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.setenv(
        machine_config.CONFIG_FILE_ENV,
        str(tmp_path / "absent.json"),
    )
    result = cer.ensure_ready(force=True)
    assert result.ok
    assert result.connector_kind == cer.CONNECTOR_UNMANAGED


def test_managed_without_tunnel_block_raises_clear(tmp_path, monkeypatch):
    monkeypatch.delenv(cer_c.PG_DSN_ENV, raising=False)
    monkeypatch.delenv(cer_c.PG_DSN_FILE_ENV, raising=False)
    binding = _write_binding(tmp_path, with_tunnel=False)  # loopback, no tunnel
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: "down (test)")

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        cer.ensure_ready(force=True)
    assert "tunnel" in str(excinfo.value).lower()


# --- error classifiers -----------------------------------------------------
def test_is_local_tunnel_connection_error_classifies(managed_env):
    import psycopg

    refused = psycopg.OperationalError(
        'connection to server at "127.0.0.1", port 6547 failed: Connection refused'
    )
    assert cer.is_local_tunnel_connection_error(refused) is True
    # OperationalError without a connection marker -> not ours.
    assert cer.is_local_tunnel_connection_error(
        psycopg.OperationalError("disk full")) is False
    # Our own heal-failure must not loop.
    assert cer.is_local_tunnel_connection_error(
        cer.ConnectedEnvUnavailable("x")) is False


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


# --- ssh argv (pure) -------------------------------------------------------
def test_build_ssh_argv_matches_operator_shape():
    spec = cer.TunnelSpec(
        local_host="127.0.0.1", local_port=6547, bastion="ubuntu@1.2.3.4",
        identity_file="/keys/k.pem", remote_host="aurora.x", remote_port=5432,
    )
    argv = cer_t._build_ssh_argv(spec)

    assert argv[0] == "ssh"
    assert argv[1:3] == ["-i", "/keys/k.pem"]
    assert "-N" in argv and "-f" in argv
    assert argv[argv.index("-L") + 1] == "6547:aurora.x:5432"
    assert argv[-1] == "ubuntu@1.2.3.4"
    joined = " ".join(argv)
    assert "BatchMode=yes" in joined
    assert "ExitOnForwardFailure=yes" in joined


# --- registration remediation ----------------------------------------------
def test_registration_failure_remediation():
    assert cer.registration_failure_remediation("invalid token") is None
    assert cer.registration_failure_remediation("") is None
    hint = cer.registration_failure_remediation("could not connect to server")
    assert hint is not None
    assert "connected_env_readiness activate" in hint


# --- CLI -------------------------------------------------------------------
def test_cli_status_explicit_dsn_ok(monkeypatch, capsys):
    monkeypatch.setenv(cer_c.PG_DSN_ENV, "host=127.0.0.1 dbname=x")
    rc = cer.main(["status"])
    assert rc == 0
    assert "unmanaged" in capsys.readouterr().out


def test_cli_unknown_command_returns_usage_error(capsys):
    assert cer.main(["bogus"]) == 2


def test_cli_activate_unavailable_returns_nonzero_redacted(managed_env, monkeypatch, capsys):
    monkeypatch.setattr(cer_t, "_probe_failure", lambda dsn: "down (test)")
    monkeypatch.setattr(cer_t, "_restart_tunnel", lambda spec: None)
    rc = cer.main(["activate"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "UNAVAILABLE" in err
    assert "dbname=test_db" not in err


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
