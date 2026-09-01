"""Diagnosis coverage for the guided self-host Docker preflight."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.config import onboard_docker_prerequisites as subject


def _completed(
    argv: tuple[str, ...],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_missing_docker_names_the_install_recovery(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: None)

    with pytest.raises(subject.DockerPrerequisiteError) as raised:
        subject.check_docker_prerequisites(engine_wait_seconds=0)

    assert raised.value.code == "docker-missing"
    assert "not installed" in str(raised.value)
    assert "docs.docker.com" in " ".join(raised.value.detail_lines)


def test_missing_compose_plugin_is_a_distinct_refusal(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: "/opt/docker")
    monkeypatch.setattr(
        subject,
        "_RUN",
        lambda argv, **_kwargs: _completed(
            tuple(argv), returncode=1, stderr="compose is not a docker command"
        ),
    )

    with pytest.raises(subject.DockerPrerequisiteError) as raised:
        subject.check_docker_prerequisites(engine_wait_seconds=0)

    assert raised.value.code == "compose-missing"
    assert "Compose plugin" in str(raised.value)
    assert "compose is not a docker command" in " ".join(raised.value.detail_lines)


def test_stopped_macos_engine_teaches_docker_desktop_first_run(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: "/opt/docker")
    monkeypatch.setattr(subject, "_SYSTEM", lambda: "Darwin")

    def run(argv, **_kwargs):
        if tuple(argv[1:]) == ("compose", "version"):
            return _completed(tuple(argv))
        return _completed(
            tuple(argv),
            returncode=1,
            stderr="Cannot connect to the Docker daemon. Is it running?",
        )

    monkeypatch.setattr(subject, "_RUN", run)

    with pytest.raises(subject.DockerPrerequisiteError) as raised:
        subject.check_docker_prerequisites(engine_wait_seconds=0)

    details = " ".join(raised.value.detail_lines)
    assert raised.value.code == "docker-engine-not-running"
    assert "Open Docker Desktop" in details
    assert "Subscription Service Agreement" in details
    assert "administrator password" in details
    assert "Cannot connect to the Docker daemon" in details


def test_slow_engine_has_a_bounded_wait_refusal(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: "/opt/docker")
    monkeypatch.setattr(subject, "_SYSTEM", lambda: "Linux")

    def run(argv, **kwargs):
        if tuple(argv[1:]) == ("compose", "version"):
            return _completed(tuple(argv))
        raise subprocess.TimeoutExpired(
            tuple(argv), kwargs["timeout"], stderr="engine startup timed out"
        )

    monkeypatch.setattr(subject, "_RUN", run)

    with pytest.raises(subject.DockerPrerequisiteError) as raised:
        subject.check_docker_prerequisites(engine_wait_seconds=0)

    assert raised.value.code == "docker-engine-timeout"
    assert "safety wait" in str(raised.value)
    assert "docker info" in " ".join(raised.value.detail_lines)


def test_engine_can_become_ready_during_the_bounded_wait(monkeypatch) -> None:
    monkeypatch.setattr(subject, "_WHICH", lambda _name: "/opt/docker")
    clock = [0.0]
    info_attempts = [1, 0]

    def run(argv, **_kwargs):
        if tuple(argv[1:]) == ("compose", "version"):
            return _completed(tuple(argv))
        return _completed(
            tuple(argv),
            returncode=info_attempts.pop(0),
            stderr="engine is starting",
        )

    monkeypatch.setattr(subject, "_RUN", run)
    monkeypatch.setattr(subject, "_MONOTONIC", lambda: clock[0])
    monkeypatch.setattr(
        subject, "_SLEEP", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    receipt = subject.check_docker_prerequisites(engine_wait_seconds=2)

    assert receipt == subject.DockerPrerequisites("/opt/docker")
    assert info_attempts == []
