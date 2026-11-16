"""Parallel runner setup retains client-tool, database and failure contracts."""

import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from yoke_core.tools import ci_runner_prepare as runner
from yoke_core.domain.source_pythonpath import source_entries


class FakeHost:
    """Answers runner commands; the client tools work once installed."""

    def __init__(self, *, installed=False, loader_has_libpq=True, fail=None,
                 usable_after_install=True):
        self.installed = installed
        self.loader_has_libpq = loader_has_libpq
        self.fail = fail
        self.usable_after_install = usable_after_install
        self.calls = []

    def __call__(self, args, **kwargs):
        if args[-1] == "--version":
            ok = self.installed and (self.usable_after_install or args[0].endswith("x"))
            return subprocess.CompletedProcess(
                args, 0 if ok else 127,
                f"{Path(args[0]).name} (PostgreSQL) 16.13\n" if ok else "",
                "" if ok else "error while loading shared libraries: libldap.so.2",
            )
        self.calls.append((args, kwargs))
        assert kwargs.get("timeout"), f"unbounded command: {args}"
        if self.fail and args[:2] == self.fail:
            raise subprocess.CalledProcessError(1, args)
        if args == ["ldconfig", "-p"]:
            libpq = "\tlibpq.so.5 (libc6,x86-64) => /lib/x86_64-linux-gnu/libpq.so.5\n"
            return subprocess.CompletedProcess(
                args, 0, "3 libs found\n" + (libpq if self.loader_has_libpq else ""), "")
        if args[:4] == ["sudo", "install", "-m", "0755"]:
            self.installed = True
        return subprocess.CompletedProcess(args, 0, "", "")

    @property
    def commands(self):
        return [args for args, _ in self.calls]


@pytest.fixture
def host(monkeypatch, tmp_path):
    def make(runner_environment="github-hosted", **kwargs):
        fake = FakeHost(**kwargs)
        monkeypatch.setattr(runner.subprocess, "run", fake)
        monkeypatch.setattr(runner.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(tmp_path / "stage"))
        monkeypatch.setenv("RUNNER_ENVIRONMENT", runner_environment)
        return fake
    return make


@pytest.mark.parametrize("runner_environment", ["self-hosted", "github-hosted"])
def test_ready_client_tools_leave_the_host_unchanged(host, runner_environment):
    fake = host(runner_environment, installed=True)
    runner.install_pg_client("pg")
    assert fake.commands == []


def test_self_hosted_runner_without_client_tools_refuses(host):
    fake = host("self-hosted")
    with pytest.raises(runner.PreparationError, match="ci_runner_pg_client_missing") as refusal:
        runner.install_pg_client("pg")
    assert "Recovery:" in str(refusal.value)
    assert fake.commands == []


@pytest.mark.parametrize("loader_has_libpq", [True, False])
def test_hosted_runner_copies_client_tools_from_the_image_without_apt(
    host, tmp_path, loader_has_libpq,
):
    fake = host(loader_has_libpq=loader_has_libpq)
    runner.install_pg_client("pg")
    commands = fake.commands
    assert not any("apt-get" in args or "apt" in args for args in commands)
    assert not any(args[:2] in (["docker", "create"], ["docker", "rm"]) for args in commands)
    copies = [args[3] for args in commands if args[:2] == ["docker", "cp"]]
    tools = ["pg_dump", "pg_restore", "psql", "createdb", "dropdb", "pg_isready"]
    expected = [f"pg:/usr/lib/postgresql/16/bin/{tool}" for tool in tools]
    if not loader_has_libpq:
        expected.append("pg:/usr/lib/x86_64-linux-gnu/libpq.so.5")
    assert commands[0] == ["ldconfig", "-p"]
    assert copies == expected
    assert not any(name in " ".join(copies) for name in ("initdb", "/postgres "))
    assert not any(copy.endswith("/postgres") for copy in copies)
    installed = 1 + len(copies)
    assert commands[installed] == ["sudo", "install", "-d", "/usr/lib/postgresql/16/bin"]
    assert commands[installed + 1] == [
        "sudo", "install", "-m", "0755", *(str(tmp_path / "stage" / t) for t in tools),
        "/usr/lib/postgresql/16/bin",
    ]
    loader = [args for args in commands if "ldconfig" in args and args[0] == "sudo"]
    if loader_has_libpq:
        assert len(commands) == installed + 2 and not loader
    else:
        assert commands[installed + 2][-1] == "/usr/lib/postgresql/16/lib/libpq.so.5"
        conf = commands[installed + 3]
        assert conf[-2:] == ["/usr/lib/postgresql/16/lib", "/etc/ld.so.conf.d/yoke-ci-pg-client.conf"]
        assert loader == [["sudo", "flock", "/var/lock/yoke-ci-ldconfig.lock", "ldconfig"]]


@pytest.mark.parametrize(
    ("fail", "reason"),
    [(["ldconfig", "-p"], "ci_runner_pg_client_loader_failed"),
     (["docker", "cp"], "ci_runner_pg_client_copy_failed"),
     (["sudo", "install"], "ci_runner_pg_client_install_failed")],
)
def test_failed_copy_refuses_with_its_named_reason(host, fail, reason):
    fake = host(fail=fail)
    with pytest.raises(runner.PreparationError, match=reason) as refusal:
        runner.install_pg_client("pg")
    assert "Recovery:" in str(refusal.value)
    assert not fake.installed
    if fail == ["docker", "cp"]:
        assert fake.commands[-1][:2] == ["docker", "cp"]


def test_copied_tools_that_cannot_run_refuse_as_unusable(host):
    host(usable_after_install=False)
    with pytest.raises(runner.PreparationError, match="ci_runner_pg_client_unusable") as refusal:
        runner.install_pg_client("pg")
    assert "libldap.so.2" in str(refusal.value)
    assert "Recovery:" in str(refusal.value)


def test_unsupported_architecture_refuses_before_docker(host, monkeypatch):
    fake = host()
    monkeypatch.setattr(runner.platform, "machine", lambda: "riscv64")
    with pytest.raises(runner.PreparationError, match="ci_runner_pg_client_unsupported_arch"):
        runner.install_pg_client("pg")
    assert fake.commands == []


@pytest.fixture
def postgres(monkeypatch, tmp_path):
    monkeypatch.setenv("PG_CONTAINER", "isolated-test-pg")
    monkeypatch.setenv("POSTGRES_IMAGE", "example.test/postgres:16")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github-env"))
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(tmp_path / "socket"))
    monkeypatch.setattr(runner, "install_pg_client", lambda container: None)
    return tmp_path / "github-env"


@pytest.mark.parametrize("mapping", ["0.0.0.0:32768\n[::]:32768\n", "", "invalid"])
def test_postgres_settings_and_cleanup_publish_before_admission(monkeypatch, postgres, mapping):
    calls = []

    def run(args, **kwargs):
        assert "YOKE_PG_SOCKET_DIR=" in postgres.read_text()
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, mapping)

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "install_pg_client",
                        lambda container: calls.append(["install", container]))
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
    assert calls[2] == ["install", "isolated-test-pg"], "copy from the running server"
    assert not any(args[:2] == ["docker", "create"] for args in calls)
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
    assert len(delays) == 4
    assert all(args[:2] == ["docker", "pull"] for args in attempts[:5])
    assert attempts[5:] == list(map(list, runner.HOST_DIAGNOSTICS))
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
        *map(list, runner.HOST_DIAGNOSTICS),
    ]
    captured = capsys.readouterr()
    output = captured.err
    steps = [line for line in captured.out.splitlines() if line.startswith("CI Postgres step: ")]
    expected_steps = ["docker pull"] + ["docker run", "docker rm"] * min(failures, 1)
    expected_steps += ["docker run", "docker port"] if failures < 2 else ["docker run"]
    assert [line.split(";")[0].removeprefix("CI Postgres step: ") for line in steps] \
        == expected_steps
    assert all("elapsed=" in line for line in steps)
    if failures == 2:
        assert commands[-6:] == diagnostics
        assert all(kwargs["timeout"] == 10 and kwargs["capture_output"]
                   for _, kwargs in calls[-6:])
        assert ["journalctl", "-u", "docker", "--since", "-5min", "-n", "100",
                "--no-pager"] in diagnostics
        assert output.count("diagnostic stdout") == 6
        assert output.count("diagnostic stderr") == 6
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
    barrier = threading.Barrier(2, timeout=5)
    finished = set()

    def task(name):
        def run():
            barrier.wait()
            finished.add(name)
            if failure and name == "dependencies":
                raise runner.PreparationError("lock invalid; regenerate the lock")
        return run

    for name in ("install_dependencies", "start_postgres"):
        monkeypatch.setattr(runner, name, task(name.split("_")[-1]))
    if failure:
        with pytest.raises(runner.PreparationError, match="ci_runner_setup_failed") as refusal:
            runner.prepare()
        assert "lock invalid" in str(refusal.value)
        assert "tests did not start" in str(refusal.value)
    else:
        runner.prepare()
    assert finished == {"dependencies", "postgres"}


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
