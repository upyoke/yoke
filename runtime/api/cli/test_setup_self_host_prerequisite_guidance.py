"""Both setup modes teach manual runtime preparation before provisioning."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_self_host import (
    _app,
    _body_text,
    _open_preview,
    _start,
    _wait_for_text,
)
from yoke_cli.config import onboard_docker_prerequisites as docker
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.self_host import runtime


@pytest.fixture
def runtime_state(monkeypatch):
    state = {"failure": "", "provisions": 0}
    monkeypatch.setattr(docker, "_SYSTEM", lambda: "Darwin")
    monkeypatch.setattr(
        docker,
        "_WHICH",
        lambda _name: None if state["failure"] == "docker-missing" else "/bin/docker",
    )

    def run(argv, **_kwargs):
        compose = tuple(argv[1:]) == ("compose", "version")
        failed = state["failure"] == (
            "compose-missing" if compose else "docker-engine-not-running"
        )
        return subprocess.CompletedProcess(
            argv, int(failed), "", "runtime unavailable" if failed else ""
        )

    monkeypatch.setattr(docker, "_RUN", run)
    check = docker.check_docker_prerequisites
    monkeypatch.setattr(
        docker, "check_docker_prerequisites", lambda: check(engine_wait_seconds=0)
    )

    def provision(setup, prerequisites):
        state["provisions"] += 1
        assert prerequisites.executable == "/bin/docker"
        setup.connection = {"ok": True, "env": setup.env_name, "api_url": setup.url}
        return setup

    monkeypatch.setattr(server, "provision", provision)
    return state


def _guidance(text):
    assert "Compose v2" in text
    assert "docker info" in text
    assert "Docker Desktop" in text and "Colima" in text
    assert "network-host-addresses=true" in text
    assert "network-address=false" in text
    assert "0.0.0.0" in text
    assert docker.SELF_HOST_GUIDE in text


@pytest.mark.parametrize(
    "failure", ["docker-missing", "compose-missing", "docker-engine-not-running", ""]
)
def test_agent_receives_preparation_and_actionable_retry_before_any_bundle_write(
    tmp_path, monkeypatch, capsys, runtime_state, failure
):
    isolate_agent_setup(tmp_path, monkeypatch)
    drive = AgentDriver(capsys)
    runtime_state["failure"] = failure
    code, lines = drive("connect.destination=self-host-server")
    assert (code, lines[-1]["key"]) == (0, "connect.self_host_server")
    _guidance(json.dumps(lines[-1]))
    code, lines = drive.walk(
        (
            "connect.self_host_server=start",
            "connect.server_start=fresh",
            "connect.admin_name=Test Person",
        )
    )
    result = lines[-1]
    assert code == 0
    if not failure:
        assert result["key"] == "connect.complete"
        assert runtime_state["provisions"] == 1
        return
    assert result["key"] == "connect.failure"
    assert failure in " ".join(result["detail"])
    _guidance(json.dumps(result))
    assert {row["value"] for row in result["answers"]} == {"retry", "back"}
    assert "setup --agent --answer connect.failure=" in result["answer_command"]
    assert runtime_state["provisions"] == 0
    assert not (tmp_path / "home/yoke-server").exists()
    runtime_state["failure"] = ""
    _, retried = drive("connect.failure=retry")
    assert retried[-1]["key"] == "connect.complete"
    assert runtime_state["provisions"] == 1


@pytest.mark.parametrize(
    "failure", ["docker-missing", "compose-missing", "docker-engine-not-running", ""]
)
def test_interactive_receives_same_guidance_and_only_provisions_when_ready(
    tmp_path, monkeypatch, runtime_state, failure
):
    from runtime.api.cli.onboard_wizard_test_helpers import stub_path_doctor

    stub_path_doctor(monkeypatch)
    runtime_state["failure"] = failure
    app, _ = _app(tmp_path)
    directory = tmp_path / "server"
    app._self_host_setup = server.new_setup(
        config_path=str(tmp_path / "config.json"), directory=str(directory)
    )

    async def scenario():
        async with app.run_test(size=(120, 50)) as pilot:
            await _open_preview(pilot)
            _guidance(_body_text(app))
            # Return to destination so the existing helper opens/starts the preview.
            await pilot.press("down", "enter")
            await _start(pilot)
            expected = failure or "Your self-hosting Yoke server is ready."
            text = await _wait_for_text(app, pilot, expected)
            assert expected in text
            if failure:
                _guidance(text)
                assert runtime_state["provisions"] == 0
                assert not directory.exists()
                runtime_state["failure"] = ""
                await pilot.press("enter")
                assert (
                    "Your self-hosting Yoke server is ready."
                    in await _wait_for_text(
                        app, pilot, "Your self-hosting Yoke server is ready."
                    )
                )
            assert runtime_state["provisions"] == 1

    asyncio.run(scenario())


def test_start_failure_keeps_bind_diagnosis_and_manual_colima_recovery(
    tmp_path, monkeypatch
):
    setup = server.new_setup(
        config_path=str(tmp_path / "config.json"), directory=str(tmp_path / "server")
    )
    monkeypatch.setattr(server, "_ensure_wizard_bundle", lambda _setup: None)
    monkeypatch.setattr(docker, "_SYSTEM", lambda: "Darwin")

    def failed_start(**_kwargs):
        raise runtime.SelfHostRuntimeError("cannot assign requested address")

    monkeypatch.setattr(runtime, "start_bundle", failed_start)
    with pytest.raises(server.SelfHostSetupError) as raised:
        server.provision(setup, docker.DockerPrerequisites("/bin/docker"))
    assert raised.value.code == "self-host-handoff"
    assert "cannot assign requested address" in str(raised.value)
    _guidance(" ".join(raised.value.detail_lines))
    assert "--protect-existing --start" in " ".join(raised.value.detail_lines)
