"""Init refuses unavailable Docker prerequisites without touching the bundle."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from yoke_cli.commands import self_host
from yoke_cli.self_host import prerequisites


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("mode", [[], ["--start"], ["--force"], ["--protect-existing"]])
@pytest.mark.parametrize(
    "failure, reason, missing",
    [
        ("docker", "self_host_docker_missing", "Docker is missing"),
        ("compose", "self_host_compose_missing", "Docker Compose plugin"),
        ("os", "self_host_compose_unavailable", "could not be checked"),
        ("timeout", "self_host_compose_unavailable", "could not be checked"),
    ],
)
def test_missing_prerequisite_preserves_bundle(
    monkeypatch, tmp_path, capsys, failure, reason, missing, mode, json_mode
):
    target = tmp_path / "bundle"
    if mode == ["--protect-existing"]:
        target.mkdir()
        (target / ".env").write_text("operator configuration\n")
    before = {p.name: p.read_bytes() for p in target.glob("*")}
    monkeypatch.setattr(
        prerequisites.shutil, "which", lambda name: None if failure == "docker" else "/docker"
    )
    runner = Mock(return_value=subprocess.CompletedProcess([], 125, b"private", b"private"))
    if failure == "os":
        runner.side_effect = OSError("private")
    if failure == "timeout":
        runner.side_effect = subprocess.TimeoutExpired("docker", 10)
    monkeypatch.setattr(prerequisites.terminal_detached_process, "run", runner)
    write = Mock(side_effect=AssertionError("must not write before prerequisite checks"))
    monkeypatch.setattr(self_host.bundle, "write_bundle", write)
    monkeypatch.setattr(self_host.bundle, "protect_existing_bundle", write)
    monkeypatch.setattr(self_host.runtime, "start_bundle", write)
    args = ["--dir", str(target), *mode]
    if mode != ["--protect-existing"]:
        args.extend(["--admin-name", "Ada"])
    if json_mode:
        args.append("--json")

    assert self_host.self_host_init(args) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert reason in output.err
    assert missing in output.err
    assert "install Docker (with Compose) and run yoke self-host init again" in output.err
    assert prerequisites.INSTALL_URL in output.err
    assert "private" not in output.err
    write.assert_not_called()
    assert {p.name: p.read_bytes() for p in target.glob("*")} == before
    assert target.exists() == (mode == ["--protect-existing"])
    if failure == "docker":
        runner.assert_not_called()
    else:
        runner.assert_called_once_with(
            ("/docker", "compose", "version"), capture_output=True, timeout=10, check=False
        )


def test_available_compose_writes_bundle(monkeypatch, tmp_path, capsys):
    target = tmp_path / "bundle"
    monkeypatch.setattr(prerequisites.shutil, "which", lambda name: "/docker")
    original_run = prerequisites.terminal_detached_process.run

    def run(command, **kwargs):
        if command[0] != "/docker":
            return original_run(command, **kwargs)
        assert command == ("/docker", "compose", "version")
        assert not target.exists()
        return subprocess.CompletedProcess(command, 0, b"Docker Compose", b"")

    monkeypatch.setattr(prerequisites.terminal_detached_process, "run", run)
    assert self_host.self_host_init(
        ["--dir", str(target), "--admin-name", "Ada", "--image", "registry/server:1"]
    ) == 0
    assert (target / "docker-compose.yml").is_file()
    assert (target / ".env").is_file()
    assert (target / "secrets" / "db-password").is_file()
    assert capsys.readouterr().err == ""
