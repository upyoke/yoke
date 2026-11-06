"""Parallel runner setup retains prerequisite, database and failure contracts."""

import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from yoke_core.tools import ci_runner_prepare as runner
from yoke_core.tools._source_pythonpath import source_entries


@pytest.mark.parametrize(
    ("host", "installed", "curl_fails", "reason"),
    [("self-hosted", False, False, "ci_runner_prerequisites_missing"),
     ("self-hosted", True, False, None),
     ("github-hosted", False, False, None),
     ("github-hosted", True, False, None),
     ("github-hosted", False, True, "ci_runner_pgdg_key_download_failed")],
)
def test_runner_prerequisites_install_only_on_hosted_hosts(
    monkeypatch, host, installed, curl_fails, reason,
):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "dpkg-query":
            return subprocess.CompletedProcess(
                args, 0 if installed else 1,
                "install ok installed" if installed else "not installed",
            )
        if args[:2] == ["sudo", "curl"] and curl_fails:
            raise subprocess.CalledProcessError(55, args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner.platform, "freedesktop_os_release",
                        lambda: {"VERSION_CODENAME": "resolute"})
    monkeypatch.setenv("RUNNER_ENVIRONMENT", host)
    if reason:
        with pytest.raises(runner.PreparationError, match=reason) as refusal:
            runner.prepare_prerequisites()
        assert "Recovery:" in str(refusal.value)
    else:
        runner.prepare_prerequisites()
    commands = [args for args, _ in calls]
    if installed or host == "self-hosted":
        assert len(commands) == 1, "prepared and self-hosted hosts stay unchanged"
        return
    curl = next(args for args in commands if args[:2] == ["sudo", "curl"])
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in curl
    for option, value in (("--retry", "5"), ("--connect-timeout", "10"),
                          ("--max-time", "60"), ("--retry-max-time", "300")):
        assert curl[curl.index(option) + 1] == value
    assert "--retry-all-errors" in curl
    apt = [args for args in commands if args[:2] == ["sudo", "apt-get"]]
    if curl_fails:
        assert not apt
        assert "Check PostgreSQL key endpoint connectivity" in str(refusal.value)
    else:
        assert apt == [
            ["sudo", "apt-get", "-o", "Acquire::Retries=3", "update"],
            ["sudo", "apt-get", "-o", "Acquire::Retries=3", "install", "--yes",
             "--no-install-recommends", "postgresql-client-16"],
        ]
        source = next(kwargs["input"] for args, kwargs in calls
                      if args[:2] == ["sudo", "tee"])
        assert "resolute-pgdg main" in source
        assert "signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc" in source


@pytest.fixture
def postgres(monkeypatch, tmp_path):
    monkeypatch.setenv("PG_CONTAINER", "isolated-test-pg")
    monkeypatch.setenv("POSTGRES_IMAGE", "example.test/postgres:16")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github-env"))
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(tmp_path / "socket"))
    return tmp_path / "github-env"


@pytest.mark.parametrize("mapping", ["0.0.0.0:32768\n[::]:32768\n", "", "invalid"])
def test_postgres_settings_and_cleanup_publish_before_admission(monkeypatch, postgres, mapping):
    calls = []

    def run(args, **kwargs):
        assert "YOKE_PG_SOCKET_DIR=" in postgres.read_text()
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, mapping)

    monkeypatch.setattr(runner, "_run", run)
    if mapping.startswith("0."):
        runner.start_postgres()
        assert "port=32768" in postgres.read_text()
    else:
        with pytest.raises(runner.PreparationError, match="ci_runner_postgres_port_missing"):
            runner.start_postgres()
        assert "YOKE_PG_DSN=" not in postgres.read_text()
    docker = next(args for args in calls if args[:2] == ["docker", "run"])
    assert calls[0] == ["docker", "pull", "example.test/postgres:16"]
    assert calls.index(docker) == 1, "pull must succeed before consuming the image"
    assert docker[docker.index("--name") + 1] == "isolated-test-pg"
    assert "timezone=" + dict(runner.DISPOSABLE_SERVER_SETTINGS)["timezone"] in docker
    for value in ("fsync=off", "synchronous_commit=off", "full_page_writes=off",
                  "wal_level=minimal", "max_wal_senders=0"):
        assert value in docker


def test_postgres_pull_retries_are_bounded_and_keep_cleanup(monkeypatch, postgres):
    attempts, delays = [], []

    def fail(args, **kwargs):
        attempts.append(args)
        raise runner.PreparationError("transport failed")

    monkeypatch.setattr(runner, "_run", fail)
    monkeypatch.setattr(runner.time, "sleep", delays.append)
    with pytest.raises(runner.PreparationError, match="ci_runner_postgres_pull_failed"):
        runner.start_postgres()
    assert len(attempts) == 5 and len(delays) == 4
    assert all(args[:2] == ["docker", "pull"] for args in attempts)
    assert all(5 <= seconds <= 30 for seconds in delays)
    assert "YOKE_PG_SOCKET_DIR=" in postgres.read_text()


@pytest.mark.parametrize("failures", [0, 1, 2])
@pytest.mark.parametrize("failure_kind", ["timeout", "error"])
def test_postgres_start_budget_retry_and_diagnostics(
    monkeypatch, postgres, capsys, failures, failure_kind,
):
    calls = []
    starts = 0

    def run(args, **kwargs):
        nonlocal starts
        calls.append((args, kwargs))
        if args[:2] == ["docker", "run"]:
            starts += 1
            assert kwargs["timeout"] == 120
            if starts <= failures:
                if failure_kind == "timeout":
                    raise subprocess.TimeoutExpired(args, 120)
                raise subprocess.CalledProcessError(1, args)
        if args[:2] == ["docker", "port"]:
            return subprocess.CompletedProcess(args, 0, "0.0.0.0:32768\n", "")
        return subprocess.CompletedProcess(args, 0, "diagnostic stdout", "diagnostic stderr")

    monkeypatch.setattr(runner.subprocess, "run", run)
    if failures == 2:
        with pytest.raises(runner.PreparationError, match="ci_runner_setup_command_failed"):
            runner.start_postgres()
        assert "YOKE_PG_DSN=" not in postgres.read_text()
    else:
        runner.start_postgres()
        assert "port=32768" in postgres.read_text()
    assert starts == min(failures + 1, 2)
    commands = [args for args, _ in calls]
    cleanup = ["docker", "rm", "-f", "isolated-test-pg"]
    assert commands.count(cleanup) == bool(failures)
    if failures:
        assert commands[1][:2] == ["docker", "run"]
        assert commands[2] == cleanup
        assert commands[3] == commands[1]
    diagnostics = [
        ["docker", "ps", "-a", "--filter", "name=isolated-test-pg"],
        ["docker", "logs", "--tail", "50", "isolated-test-pg"],
        ["docker", "info"],
    ]
    output = capsys.readouterr().err
    if failures == 2:
        assert commands[-3:] == diagnostics
        assert all(kwargs["timeout"] == 10 and kwargs["capture_output"]
                   for _, kwargs in calls[-3:])
        assert output.count("diagnostic stdout") == 3
        assert output.count("diagnostic stderr") == 3
        assert all(" ".join(command) in output for command in diagnostics)
    else:
        assert not output
        assert not any(command in commands for command in diagnostics)


def test_start_failure_survives_cleanup_and_diagnostic_failures(monkeypatch, capsys):
    calls = []

    def fail(args, **kwargs):
        calls.append(args)
        raise runner.PreparationError("ci_runner_setup_command_failed: " + args[1])

    monkeypatch.setattr(runner, "_run", fail)
    with pytest.raises(runner.PreparationError, match="ci_runner_setup_command_failed: run"):
        runner._start_container(["docker", "run"], "test-pg")
    assert [args[1] for args in calls] == ["run", "rm", "run", "ps", "logs", "info"]
    assert "ci_runner_setup_command_failed: rm" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [False, True])
def test_all_independent_tasks_start_and_join_even_when_one_fails(monkeypatch, failure):
    barrier = threading.Barrier(3, timeout=5)
    finished = set()

    def task(name):
        def run():
            barrier.wait()
            finished.add(name)
            if failure and name == "dependencies":
                raise runner.PreparationError("lock invalid; regenerate the lock")
        return run

    for name in ("prepare_prerequisites", "install_dependencies", "start_postgres"):
        monkeypatch.setattr(runner, name, task(name.split("_")[-1]))
    if failure:
        with pytest.raises(runner.PreparationError, match="ci_runner_setup_failed") as refusal:
            runner.prepare()
        assert "lock invalid" in str(refusal.value)
        assert "tests did not start" in str(refusal.value)
    else:
        runner.prepare()
    assert finished == {"prerequisites", "dependencies", "postgres"}


def test_locked_dependency_command_is_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_run", lambda args: calls.append(args))
    runner.install_dependencies()
    assert calls == [["uv", "sync", "--all-packages", "--locked"]]


@pytest.mark.parametrize("error", [OSError("missing binary"), subprocess.TimeoutExpired("uv", 180),
                                  subprocess.CalledProcessError(1, ["docker", "port"])])
def test_command_failures_teach_recovery(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(runner.subprocess, "run", fail)
    with pytest.raises(runner.PreparationError, match="ci_runner_setup_command_failed") as refusal:
        runner.install_dependencies()
    assert "Recovery:" in str(refusal.value)


def test_setup_imports_before_dependencies_are_installed():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import yoke_core.tools.ci_runner_prepare"],
        env={"PYTHONPATH": os.pathsep.join(source_entries(root))},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
