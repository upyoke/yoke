"""Unit coverage for the wizard's safe self-host server operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import onboard_self_host_server as subject
from yoke_cli.config import server_connect
from yoke_cli.self_host import bundle
from yoke_contracts.self_host_bootstrap_output import (
    FIRST_BOOT_TOKEN_MARKER,
    TOKEN_BODY_LENGTH,
    TOKEN_PREFIX,
    extract_first_boot_admin_token,
    first_boot_admin_token_block,
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
    return subject.DockerPrerequisites("/usr/bin/docker", "2.30.0")


def _compose_output() -> str:
    return "\n".join(
        f"core-1  | {line}"
        for line in first_boot_admin_token_block(RAW_TOKEN).splitlines()
    )


def test_shared_contract_extracts_plain_and_compose_prefixed_boot_output() -> None:
    block = first_boot_admin_token_block(RAW_TOKEN)

    assert FIRST_BOOT_TOKEN_MARKER in block
    assert extract_first_boot_admin_token(block) == RAW_TOKEN
    assert extract_first_boot_admin_token(_compose_output()) == RAW_TOKEN
    assert extract_first_boot_admin_token(f"unrelated {RAW_TOKEN}") is None


def test_missing_docker_refuses_before_any_bundle_write(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: None)

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.check_docker_prerequisites()

    assert raised.value.code == "docker-missing"
    assert "Docker is required" in str(raised.value)
    assert "docs.docker.com" in " ".join(raised.value.detail_lines)


def test_missing_compose_plugin_is_a_named_prerequisite_refusal(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: "/opt/docker")
    monkeypatch.setattr(
        subject,
        "_RUN",
        lambda *args, **kwargs: _completed(args[0], returncode=1, stderr="no plugin"),
    )

    with pytest.raises(subject.SelfHostSetupError) as raised:
        subject.check_docker_prerequisites()

    assert raised.value.code == "compose-missing"
    assert "Compose plugin" in str(raised.value)
    assert "no plugin" in " ".join(raised.value.detail_lines)


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
        if "logs" in argv:
            return _completed(tuple(argv), stdout=_compose_output())
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

    result = subject.provision(setup, _prerequisites(), token_wait_seconds=0)

    assert result.raw_token == RAW_TOKEN
    assert repr(result).find(RAW_TOKEN) == -1
    assert calls[0] == (
        ("/usr/bin/docker", "compose", "up", "-d"),
        setup.directory,
    )
    assert calls[1][0] == (
        "/usr/bin/docker",
        "compose",
        "logs",
        "--no-color",
        "--tail",
        str(subject.COMPOSE_LOG_TAIL),
        "core",
    )
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
    log_output = ["server is booting", _compose_output()]
    writes: list[Path] = []
    real_write = bundle.write_bundle

    def write(**kwargs):
        writes.append(Path(kwargs["directory"]))
        return real_write(**kwargs)

    def run(argv, **kwargs):
        if "logs" in argv:
            return _completed(tuple(argv), stdout=log_output.pop(0))
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

    with pytest.raises(subject.SelfHostSetupError, match="did not print") as raised:
        subject.provision(setup, _prerequisites(), token_wait_seconds=0)
    assert raised.value.code == "token-timeout"

    ready = subject.provision(setup, _prerequisites(), token_wait_seconds=0)

    assert ready.raw_token == RAW_TOKEN
    assert len(writes) == 1


def test_connect_failure_retains_token_for_in_memory_retry(
    tmp_path, monkeypatch
) -> None:
    attempts: list[str] = []

    def run(argv, **kwargs):
        output = _compose_output() if "logs" in argv else ""
        return _completed(tuple(argv), stdout=output)

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
        subject.provision(setup, _prerequisites(), token_wait_seconds=0)

    assert raised.value.code == "connect"
    assert setup.raw_token == RAW_TOKEN
    assert RAW_TOKEN not in f"{raised.value} {raised.value.detail_lines}"
    assert raised.value.__cause__ is None
    assert subject.retry_connection(setup).connection == {
        "ok": True,
        "api_url": subject.LOCAL_SERVER_URL,
    }
    assert attempts == [RAW_TOKEN, RAW_TOKEN]
