"""Fleet copy must retry a dropped dump and keep the tunnel alive."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import migration_fleet_preflight_transfer as transfer


@pytest.fixture(autouse=True)
def _no_real_forward_recovery(monkeypatch):
    """Retries must never reach the machine's real connected env in tests."""
    monkeypatch.setattr(transfer, "restore_source_path", lambda: None)


def test_ssl_eof_is_transient() -> None:
    assert transfer.is_transient_dump_error(
        'pg_dump failed (1): SSL SYSCALL error: EOF detected'
    )
    assert not transfer.is_transient_dump_error("pg_dump failed (1): permission denied")


def test_a_dropped_forward_is_transient() -> None:
    """The forward dying mid-copy refuses the next connection like a dead one."""
    assert transfer.is_transient_dump_error(
        "pg_dump failed (1): connection to server at \"127.0.0.1\", port 6547 "
        "failed: Connection refused"
    )


def test_dump_env_sets_libpq_keepalives() -> None:
    env = transfer.dump_env({"PATH": "/bin"})
    assert env["PGKEEPALIVES"] == "1"
    assert env["PGKEEPALIVES_IDLE"] == "30"
    assert env["PATH"] == "/bin"


def test_run_transfer_redacts_dsn(monkeypatch) -> None:
    class _Result:
        returncode = 1
        stderr = "failed host=db password=secret"

    monkeypatch.setattr(
        transfer.subprocess, "run", lambda *_args, **_kwargs: _Result()
    )
    with pytest.raises(RuntimeError) as excinfo:
        transfer.run_transfer(
            ["/bin/pg_dump"],
            redact="host=db password=secret",
            timeout=1,
        )
    assert "password=secret" not in str(excinfo.value)
    assert "<dsn>" in str(excinfo.value)


def test_run_transfer_names_timeout(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="pg_dump", timeout=9)

    monkeypatch.setattr(transfer.subprocess, "run", _boom)
    with pytest.raises(RuntimeError, match="timed out after 9s"):
        transfer.run_transfer(["/opt/pg_dump"], timeout=9)


def test_dump_retries_ssl_eof_then_succeeds(monkeypatch, tmp_path) -> None:
    calls: list[tuple] = []

    def _fake_run(argv, *, redact, timeout, env):
        calls.append((list(argv), redact, timeout, env))
        if len(calls) == 1:
            raise RuntimeError(
                "pg_dump failed (1): SSL SYSCALL error: EOF detected"
            )

    monkeypatch.setattr(transfer, "run_transfer", _fake_run)
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )
    dump = tmp_path / "tenant.dump"
    transfer.dump_database(SimpleNamespace(), "host=db password=secret", dump)

    assert len(calls) == 2
    assert "--compress=1" in calls[0][0]
    assert calls[0][1] == "host=db password=secret"
    assert calls[0][2] == transfer.DUMP_TIMEOUT_SECONDS
    assert calls[0][3]["PGKEEPALIVES"] == "1"


def test_dump_does_not_retry_non_transient(monkeypatch, tmp_path) -> None:
    def _fake_run(*_args, **_kwargs):
        raise RuntimeError("pg_dump failed (1): permission denied")

    monkeypatch.setattr(transfer, "run_transfer", _fake_run)
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )
    with pytest.raises(RuntimeError, match="permission denied"):
        transfer.dump_database(
            SimpleNamespace(), "host=db", tmp_path / "tenant.dump"
        )


def test_dump_restores_the_forward_before_copying_again(monkeypatch, tmp_path) -> None:
    """A retry through a dead forward is another failure; heal it first."""
    events: list[str] = []

    def _fake_run(argv, *, redact, timeout, env):
        del argv, redact, timeout, env
        events.append("copy")
        if events.count("copy") == 1:
            raise RuntimeError("pg_dump failed (1): Connection refused")

    monkeypatch.setattr(transfer, "run_transfer", _fake_run)
    monkeypatch.setattr(
        transfer, "restore_source_path", lambda: events.append("restore")
    )
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )
    notices: list[str] = []

    transfer.dump_database(
        SimpleNamespace(),
        "host=127.0.0.1",
        tmp_path / "tenant.dump",
        emit=notices.append,
    )

    assert events == ["copy", "restore", "copy"]
    assert notices and "restoring it and copying again" in notices[0]


def test_dump_names_both_failures_when_the_forward_stays_down(
        monkeypatch, tmp_path) -> None:
    def _fake_run(*_args, **_kwargs):
        raise RuntimeError("pg_dump failed (1): Connection refused")

    def _cannot_heal():
        raise RuntimeError("ssh tunnel start failed (rc=255)")

    monkeypatch.setattr(transfer, "run_transfer", _fake_run)
    monkeypatch.setattr(transfer, "restore_source_path", _cannot_heal)
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )

    with pytest.raises(RuntimeError) as excinfo:
        transfer.dump_database(
            SimpleNamespace(), "host=127.0.0.1", tmp_path / "tenant.dump"
        )

    message = str(excinfo.value)
    assert "Connection refused" in message
    assert "could not be restored" in message
    assert "rc=255" in message
