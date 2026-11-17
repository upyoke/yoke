"""Guided hosting preserves the shared Docker prerequisite contract."""

import pytest

from yoke_cli.config import onboard_docker_prerequisites as docker
from yoke_cli.config import onboard_self_host_server as subject


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
