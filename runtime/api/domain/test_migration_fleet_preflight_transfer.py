"""Fleet copy must retry a dropped dump and keep the tunnel alive."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import migration_fleet_preflight_transfer as transfer


ADMIN_ENV = "prod-db-admin"

#: Captured before the autouse fixture stubs the module attribute, so the one
#: test that exercises the real healer can still reach it.
REAL_RESTORE_SOURCE_PATH = transfer.restore_source_path


@pytest.fixture(autouse=True)
def _no_real_forward_recovery(monkeypatch):
    """Retries must never reach the machine's real connected env in tests."""
    monkeypatch.setattr(transfer, "restore_source_path", lambda _env: None)


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
    transfer.dump_database(
        SimpleNamespace(),
        "host=db password=secret",
        dump,
        source_environment=ADMIN_ENV,
    )

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
            SimpleNamespace(),
            "host=db",
            tmp_path / "tenant.dump",
            source_environment=ADMIN_ENV,
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
        transfer,
        "restore_source_path",
        lambda env: events.append(f"restore:{env}"),
    )
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )
    notices: list[str] = []

    transfer.dump_database(
        SimpleNamespace(),
        "host=127.0.0.1",
        tmp_path / "tenant.dump",
        source_environment=ADMIN_ENV,
        emit=notices.append,
    )

    # The forward reopened is the one the copies run through -- the selected
    # admin connection, not whichever control plane is ambient.
    assert events == ["copy", f"restore:{ADMIN_ENV}", "copy"]
    assert notices and "restoring it and copying again" in notices[0]


def test_dump_names_both_failures_when_the_forward_stays_down(
        monkeypatch, tmp_path) -> None:
    def _fake_run(*_args, **_kwargs):
        raise RuntimeError("pg_dump failed (1): Connection refused")

    def _cannot_heal(_env):
        raise RuntimeError("ssh tunnel start failed (rc=255)")

    monkeypatch.setattr(transfer, "run_transfer", _fake_run)
    monkeypatch.setattr(transfer, "restore_source_path", _cannot_heal)
    monkeypatch.setattr(
        transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
    )

    with pytest.raises(RuntimeError) as excinfo:
        transfer.dump_database(
            SimpleNamespace(),
            "host=127.0.0.1",
            tmp_path / "tenant.dump",
            source_environment=ADMIN_ENV,
        )

    message = str(excinfo.value)
    assert "Connection refused" in message
    assert "could not be restored" in message
    assert "rc=255" in message


def test_restore_source_path_reopens_the_named_connection(monkeypatch) -> None:
    """Heal the connection the copies use, not whichever one is ambient.

    A rehearsal selects its admin connection explicitly; the session running
    it usually has a different control plane active. Healing that ambient one
    reports "nothing to do" and leaves the dead forward exactly as dead.
    """
    from yoke_core.domain import connected_env_selected_readiness

    reopened: list[str] = []
    monkeypatch.setattr(
        connected_env_selected_readiness,
        "activate_selected_postgres",
        lambda environment: reopened.append(environment),
    )

    REAL_RESTORE_SOURCE_PATH(ADMIN_ENV)

    assert reopened == [ADMIN_ENV]


#: A ``pg_restore -l`` listing of the fleet's shape, headers and all.
TOC_LISTING = """;
; Archive created at 2026-09-18 03:00:00 UTC
;     dbname: tenant_1
;
; Selected TOC Entries:
;
7; 2615 32866 SCHEMA - statement_statistics tenantowner
2; 3079 32867 EXTENSION - pg_stat_statements 
3838; 0 0 COMMENT - EXTENSION pg_stat_statements 
234; 1255 32892 FUNCTION statement_statistics reader() tenantowner
219; 1259 32893 VIEW statement_statistics current_database_statements tenantowner
"""

STAGED_SCHEMA = "statement_statistics"


class TestRestoreListOmittingSchemas:
    """A schema staged ahead of the restore must not be created twice."""

    @pytest.fixture(autouse=True)
    def _listing(self, monkeypatch) -> None:
        monkeypatch.setattr(
            transfer.postgres_cluster, "binary", lambda _spec, name: f"/bin/{name}"
        )
        monkeypatch.setattr(
            transfer,
            "run_transfer",
            lambda *_a, **_kw: SimpleNamespace(stdout=TOC_LISTING, stderr=""),
        )

    def _write(self, tmp_path, schemas) -> list:
        path = tmp_path / "nested" / "tenant.restore-list"
        transfer.restore_list_omitting_schemas(
            SimpleNamespace(), tmp_path / "tenant.dump", schemas, path
        )
        return path.read_text(encoding="utf-8").splitlines()

    def test_only_the_named_schema_entry_is_commented_out(self, tmp_path) -> None:
        lines = self._write(tmp_path, [STAGED_SCHEMA])

        assert f";7; 2615 32866 SCHEMA - {STAGED_SCHEMA} tenantowner" in lines
        # Everything else still restores, the extension's own IF NOT EXISTS
        # statement included — it finds the staged extension and no-ops.
        assert "2; 3079 32867 EXTENSION - pg_stat_statements " in lines
        assert (
            "219; 1259 32893 VIEW statement_statistics "
            "current_database_statements tenantowner"
        ) in lines

    def test_a_schema_with_no_entry_to_skip_refuses(self, tmp_path) -> None:
        # Proceeding would hand pg_restore a list that still creates the
        # staged schema, failing the restore on a duplicate instead.
        with pytest.raises(RuntimeError, match="cannot be told to skip"):
            self._write(tmp_path, [STAGED_SCHEMA, "absent_schema"])
