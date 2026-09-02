"""Unit coverage for the wizard's safe self-host server operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import onboard_docker_prerequisites as docker
from yoke_cli.config import onboard_self_host_server as subject
from yoke_cli.config import server_connect
from yoke_cli.self_host import bundle, first_boot_token
from yoke_contracts.self_host_bootstrap_output import (
    FIRST_BOOT_TOKEN_MARKER,
    TOKEN_BODY_LENGTH,
    TOKEN_PREFIX,
    connect_url_from_publish_spec,
    first_boot_admin_token_notice,
)


RAW_TOKEN = TOKEN_PREFIX + ("A" * TOKEN_BODY_LENGTH)


def _completed(
    argv: tuple[str, ...],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _prerequisites() -> subject.DockerPrerequisites:
    return docker.DockerPrerequisites("/usr/bin/docker")


def _deliver_token(directory: Path) -> None:
    """Stand in for the server writing its one-time token at first boot."""
    target = first_boot_token.token_drop_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(RAW_TOKEN + "\n", encoding="utf-8")


def test_boot_notice_names_the_token_file_and_never_the_token() -> None:
    notice = first_boot_admin_token_notice(
        host_path="./secrets/first-boot-admin-token",
        connect_url="http://127.0.0.1:8765",
    )

    assert FIRST_BOOT_TOKEN_MARKER in notice
    assert RAW_TOKEN not in notice
    assert "./secrets/first-boot-admin-token" in notice
    assert (
        "yoke connect http://127.0.0.1:8765 --token-stdin "
        "< ./secrets/first-boot-admin-token"
    ) in notice


def test_docker_preflight_export_delegates_to_shared_probe(monkeypatch) -> None:
    receipt = docker.DockerPrerequisites("/usr/bin/docker")
    monkeypatch.setattr(subject, "_check_docker_prerequisites", lambda: receipt)

    assert subject.check_docker_prerequisites() is receipt


def test_docker_preflight_export_preserves_setup_error_contract(monkeypatch) -> None:
    refusal = docker.DockerPrerequisiteError(
        "docker-engine-not-running",
        "Docker is installed, but its engine is not running.",
        ("Open Docker Desktop, then retry.",),
    )

    def refuse() -> docker.DockerPrerequisites:
        raise refusal

    monkeypatch.setattr(subject, "_check_docker_prerequisites", refuse)

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.check_docker_prerequisites()

    assert raised.value.code == refusal.code
    assert str(raised.value) == str(refusal)
    assert raised.value.detail_lines == refusal.detail_lines


@pytest.mark.parametrize(
    ("publish_spec", "expected"),
    [
        ("127.0.0.1:8765", "http://127.0.0.1:8765"),
        ("0.0.0.0:8765", "http://127.0.0.1:8765"),
        ("192.168.1.10:9000", "http://192.168.1.10:9000"),
        ("[::]:8765", "http://127.0.0.1:8765"),
        ("", "http://127.0.0.1:8765"),
    ],
)
def test_publish_spec_becomes_a_pasteable_connect_url(
    publish_spec: str,
    expected: str,
) -> None:
    assert connect_url_from_publish_spec(publish_spec) == expected


def test_existing_bundle_collision_is_left_untouched(tmp_path, monkeypatch) -> None:
    target = tmp_path / "yoke-server"
    target.mkdir()
    compose = target / bundle.COMPOSE_FILE_NAME
    compose.write_text("operator-owned\n", encoding="utf-8")
    wrote: list[bool] = []
    monkeypatch.setattr(bundle, "write_bundle", lambda **_: wrote.append(True))
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"), directory=str(target)
    )

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.provision(setup, _prerequisites())

    assert raised.value.code == "bundle-collision"
    assert compose.read_text(encoding="utf-8") == "operator-owned\n"
    assert wrote == []
    assert setup.bundle_created is False


def test_success_uses_safe_compose_argv_and_connects_loopback(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []
    connected: list[dict[str, object]] = []

    def run(argv, **kwargs):
        calls.append((tuple(argv), kwargs["cwd"]))
        if "up" in argv:
            _deliver_token(kwargs["cwd"])
        return _completed(tuple(argv))

    def connect(url, **kwargs):
        connected.append({"url": url, **kwargs})
        return {"ok": True, "env": kwargs["env"], "api_url": url}

    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(server_connect, "connect_server", connect)
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "server"),
    )

    result = subject.provision(
        setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=0
    )

    assert result.raw_token == RAW_TOKEN
    assert repr(result).find(RAW_TOKEN) == -1
    assert calls[0] == (
        ("/usr/bin/docker", "compose", "up", "-d"),
        setup.directory,
    )
    # The token came from the bundle file, so the wizard never had to read
    # a log that would have been carrying the credential.
    assert not any("logs" in argv for argv, _cwd in calls)
    assert connected[0]["url"] == subject.LOCAL_SERVER_URL
    assert connected[0]["token"] == RAW_TOKEN
    assert connected[0]["env"] == server_connect.DEFAULT_ENV_NAME
    assert connected[0]["activate"] is True
    assert connected[0]["config_path"] == str(tmp_path / "config.json")


def test_compose_failure_preserves_bundle_and_redacts_diagnostics(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        subject,
        "_RUN",
        lambda argv, **kwargs: _completed(
            tuple(argv), returncode=1, stderr=f"daemon refused {RAW_TOKEN}"
        ),
    )
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "server"),
    )

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.provision(setup, _prerequisites())

    evidence = f"{raised.value} {' '.join(raised.value.detail_lines)}"
    assert raised.value.code == "compose-start"
    assert setup.bundle_created is True
    assert (setup.directory / bundle.COMPOSE_FILE_NAME).is_file()
    assert "docker compose up -d" in evidence
    assert RAW_TOKEN not in evidence


def test_token_timeout_retry_reuses_only_this_wizards_bundle(
    tmp_path, monkeypatch
) -> None:
    booted: list[bool] = []
    writes: list[Path] = []
    real_write = bundle.write_bundle

    def write(**kwargs):
        writes.append(Path(kwargs["directory"]))
        return real_write(**kwargs)

    def run(argv, **kwargs):
        if "up" in argv:
            # The first boot is still coming up; the second has written it.
            if booted:
                _deliver_token(kwargs["cwd"])
            booted.append(True)
        return _completed(tuple(argv))

    monkeypatch.setattr(bundle, "write_bundle", write)
    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(
        server_connect,
        "connect_server",
        lambda url, **kwargs: {"ok": True, "api_url": url},
    )
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "server"),
    )

    with pytest.raises(subject.SelfHostSetupError, match="did not write") as raised:
        subject.provision(
            setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=0
        )
    assert raised.value.code == "token-timeout"

    ready = subject.provision(
        setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=0
    )

    assert ready.raw_token == RAW_TOKEN
    assert len(writes) == 1


def test_connect_failure_retains_token_for_in_memory_retry(
    tmp_path, monkeypatch
) -> None:
    attempts: list[str] = []

    def run(argv, **kwargs):
        if "up" in argv:
            _deliver_token(kwargs["cwd"])
        return _completed(tuple(argv))

    def connect(url, **kwargs):
        attempts.append(kwargs["token"])
        if len(attempts) == 1:
            raise server_connect.ServerConnectError(f"not ready {RAW_TOKEN}")
        return {"ok": True, "api_url": url}

    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(server_connect, "connect_server", connect)
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "server"),
    )

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.provision(
            setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=0
        )

    assert raised.value.code == "connect"
    assert setup.raw_token == RAW_TOKEN
    assert RAW_TOKEN not in f"{raised.value} {raised.value.detail_lines}"
    assert raised.value.__cause__ is None
    assert subject.retry_connection(setup, health_wait_seconds=0).connection == {
        "ok": True,
        "api_url": subject.LOCAL_SERVER_URL,
    }
    assert attempts == [RAW_TOKEN, RAW_TOKEN]


def test_post_start_health_wait_retries_until_the_server_answers(
    tmp_path, monkeypatch
) -> None:
    clock, probes, connected = [0.0], [False, True], []

    def run(argv, **kwargs):
        if "up" in argv:
            _deliver_token(kwargs["cwd"])
        return _completed(tuple(argv))

    def health(_url, *, timeout_s=0):
        if not probes.pop(0):
            raise server_connect.ServerConnectError("unreachable")
        return {"status": "ok"}

    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(subject, "_MONOTONIC", lambda: clock[0])
    monkeypatch.setattr(subject, "_SLEEP", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(server_connect, "verify_server_health", health)
    monkeypatch.setattr(
        server_connect,
        "connect_server",
        lambda url, **kwargs: connected.append(url) or {"ok": True, "api_url": url},
    )
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"), directory=str(tmp_path / "server")
    )
    result = subject.provision(
        setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=2
    )
    assert result.connection == {"ok": True, "api_url": subject.LOCAL_SERVER_URL}
    assert probes == []
    assert connected == [subject.LOCAL_SERVER_URL]


def test_post_start_health_wait_times_out_before_connect(tmp_path, monkeypatch) -> None:
    clock, connected = [0.0], []

    def run(argv, **kwargs):
        if "up" in argv:
            _deliver_token(kwargs["cwd"])
        return _completed(tuple(argv))

    def health(*_a, **_k):
        raise server_connect.ServerConnectError("JSON request endpoint is unreachable")

    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(subject, "_MONOTONIC", lambda: clock[0])
    monkeypatch.setattr(subject, "_SLEEP", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(server_connect, "verify_server_health", health)
    monkeypatch.setattr(
        server_connect, "connect_server", lambda url, **kwargs: connected.append(url)
    )
    setup = subject.new_setup(
        config_path=str(tmp_path / "config.json"), directory=str(tmp_path / "server")
    )
    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.provision(
            setup, _prerequisites(), token_wait_seconds=0, health_wait_seconds=2
        )
    evidence = f"{raised.value} {' '.join(raised.value.detail_lines)}"
    assert raised.value.code == "connect"
    assert "JSON request endpoint is unreachable" in evidence
    assert "2 seconds" in evidence
    assert setup.raw_token == RAW_TOKEN
    assert connected == []
