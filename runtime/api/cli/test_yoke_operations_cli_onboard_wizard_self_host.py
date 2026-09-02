"""Pilot coverage for guided self-host first boot inside ``yoke onboard``."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_docker_prerequisites as docker  # noqa: E402
from yoke_cli.config import onboard_self_host_server as server  # noqa: E402
from yoke_cli.config import yoke_token_verify  # noqa: E402
from yoke_cli.config.onboard_destinations import DESTINATION_SERVER  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config import onboard_wizard_self_host as flow  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_connect as connect_flow  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_GITHUB,
    SelectionList,
    Stepper,
)
from yoke_cli.self_host import first_boot_token  # noqa: E402
from yoke_contracts.self_host_bootstrap_output import (  # noqa: E402
    TOKEN_BODY_LENGTH,
    TOKEN_PREFIX,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


RAW_TOKEN = TOKEN_PREFIX + ("B" * TOKEN_BODY_LENGTH)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


async def _wait_for_text(app, pilot, expected: str) -> str:
    for _ in range(20):
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = _body_text(app)
        if expected in text:
            return text
    return _body_text(app)


def _app(tmp_path):
    return make_app(WizardDefaults(config_path=str(tmp_path / "config.json")))


async def _open_preview(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down", "down")
    await pilot.press("enter")


def _stub_success(monkeypatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        docker,
        "check_docker_prerequisites",
        lambda: docker.DockerPrerequisites("/usr/bin/docker"),
    )

    def provision(setup, prerequisites):
        calls.append("provision")
        setup.bundle_created = True
        setup.raw_token = RAW_TOKEN
        setup.connection = {
            "ok": True,
            "env": setup.env_name,
            "api_url": setup.url,
        }
        return setup

    monkeypatch.setattr(server, "provision", provision)


def test_picker_preview_is_exact_and_does_not_mutate_before_start(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []
    _stub_success(monkeypatch, calls)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            text = _body_text(app)
            assert "Set up this machine as a self-hosting server?" in text
            assert str(tmp_path.parent) not in text  # no synthetic test path copy
            assert "yoke-server" in text
            assert server.LOCAL_SERVER_URL in text
            assert "Port: 8765 (loopback only)" in text
            assert "Requires Docker and the Docker Compose plugin" in text
            assert "docker compose up -d" in text
            assert "VPN/tailnet, LAN, or port-forwarding" in text
            assert calls == []
            await pilot.press("down", "enter")
            await pilot.pause()
            assert "Where should this Yoke live?" in _body_text(app)

    asyncio.run(scenario())


def test_success_shows_handoff_and_continue_rejoins_project_setup(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []
    _stub_success(monkeypatch, calls)
    monkeypatch.setattr(flow, "machine_may_sleep", lambda: True)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            await pilot.press("enter")
            text = await _wait_for_text(
                app, pilot, "Your self-hosting Yoke server is ready."
            )
            assert RAW_TOKEN not in text
            token_file = str(
                first_boot_token.token_drop_path(app._self_host_setup.directory)
            )
            assert f"Admin token file: {token_file}" in text
            assert "reusable administrator identity" in text
            assert "never printed here" in text
            assert "self-host is active on this machine" in text
            assert "Mint a separate token for each teammate" in text
            assert "Share only a server URL your teammates can actually reach" in text
            assert flow.SLEEP_WARNING in text
            assert app.result.destination == DESTINATION_SERVER
            assert app.result.api_url == server.LOCAL_SERVER_URL
            assert app.result.token is None
            assert app.result.token_file.endswith("self-host.token")
            assert RAW_TOKEN not in repr(app.result)
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_GITHUB

    asyncio.run(scenario())
    assert calls == ["provision"]


def test_finish_with_handoff_exits_successfully_without_a_project(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []
    _stub_success(monkeypatch, calls)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            await pilot.press("enter")
            await _wait_for_text(app, pilot, "Finish with server handoff")
            await pilot.press("down", "enter")

    asyncio.run(scenario())
    assert app.exit_code == 0
    assert app.cancelled is False
    assert app.result.project_slug is None
    assert app.result.api_url == server.LOCAL_SERVER_URL


def test_prerequisite_refusal_names_docker_and_allows_back(
    tmp_path, monkeypatch
) -> None:
    def refuse():
        raise docker.DockerPrerequisiteError(
            "docker-engine-not-running",
            "Docker is installed, but its engine is not running.",
            ("Open Docker Desktop, complete its first run, then retry.",),
        )

    monkeypatch.setattr(docker, "check_docker_prerequisites", refuse)
    app, _spy = _app(tmp_path)
    bundle_directory = tmp_path / "server"
    app._self_host_setup = server.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(bundle_directory),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            await pilot.press("enter")
            text = await _wait_for_text(app, pilot, "engine is not running")
            assert "Open Docker Desktop" in text
            assert app.query_one(SelectionList).rows[0].label == "Try again"
            assert not bundle_directory.exists()
            await pilot.press("down", "enter")
            await pilot.pause()
            assert "Where should this Yoke live?" in _body_text(app)

    asyncio.run(scenario())


def test_connect_recovery_names_the_token_file_and_retries_it_in_memory(
    tmp_path, monkeypatch
) -> None:
    retries: list[str] = []
    monkeypatch.setattr(
        docker,
        "check_docker_prerequisites",
        lambda: docker.DockerPrerequisites("/usr/bin/docker"),
    )

    def fail_connect(setup, prerequisites):
        setup.bundle_created = True
        setup.raw_token = RAW_TOKEN
        raise server.SelfHostSetupError("connect", "Connection failed.", ("Retry it.",))

    def retry(setup):
        retries.append(setup.raw_token or "")
        setup.connection = {"ok": True, "api_url": setup.url}
        return setup

    monkeypatch.setattr(server, "provision", fail_connect)
    monkeypatch.setattr(server, "retry_connection", retry)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            await pilot.press("enter")
            text = await _wait_for_text(app, pilot, "Retry connection")
            assert RAW_TOKEN not in text
            token_file = str(
                first_boot_token.token_drop_path(app._self_host_setup.directory)
            )
            assert f"Admin token file: {token_file}" in text
            assert "reusable administrator identity" in text
            assert "never printed here" in text
            assert server.LOCAL_SERVER_URL in text
            await pilot.press("enter")
            await _wait_for_text(app, pilot, "Your self-hosting Yoke server is ready.")

    asyncio.run(scenario())
    assert retries == [RAW_TOKEN]


def test_existing_server_url_and_token_failure_both_teach_the_new_route(
    tmp_path, monkeypatch
) -> None:
    app, _spy = _app(tmp_path)

    def reject(*_args, **_kwargs):
        raise yoke_token_verify.YokeTokenVerificationError("credential rejected")

    monkeypatch.setattr(connect_flow, "verify_yoke_token", reject)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down", "enter")
            assert flow.NO_SERVER_GUIDANCE in _body_text(app)
            await type_text(pilot, "https://yoke.acme.test")
            await pilot.press("enter")
            await pilot.press("enter")
            await type_text(pilot, RAW_TOKEN)
            await pilot.press("enter")
            text = await _wait_for_text(app, pilot, "could not be verified")
            assert flow.NO_SERVER_GUIDANCE in text

    asyncio.run(scenario())


def test_sleep_warning_is_conditional(tmp_path) -> None:
    assert flow.machine_may_sleep(system_name="Darwin") is True
    assert (
        flow.machine_may_sleep(
            system_name="Linux", power_supply_root=tmp_path / "missing"
        )
        is False
    )


def test_wizard_screen_helpers_never_emit_the_raw_token(tmp_path) -> None:
    setup = server.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "yoke-server"),
    )
    setup.raw_token = RAW_TOKEN
    rendered = "\n".join(
        [
            *flow._preview_lines(setup),
            *flow._admin_token_file_lines(setup),
            *flow._complete_lines(setup),
        ]
    )
    assert RAW_TOKEN not in rendered
    assert TOKEN_PREFIX not in rendered
    token_file = str(first_boot_token.token_drop_path(setup.directory))
    assert f"Admin token file: {token_file}" in rendered


def test_quit_is_blocked_only_during_bundle_and_compose_provisioning(tmp_path) -> None:
    calls: list[dict[str, object]] = []

    class Probe:
        def _run_checking(self, **kwargs) -> None:
            calls.append(kwargs)

    probe = Probe()
    setup = server.new_setup(
        config_path=str(tmp_path / "config.json"),
        directory=str(tmp_path / "server"),
    )
    receipt = docker.DockerPrerequisites("/usr/bin/docker")

    flow._run_preflight(probe, setup)
    flow._run_provision(probe, setup, receipt)
    flow._run_connect_retry(probe, setup)

    assert [call["blocks_quit"] for call in calls] == [False, True, False]
    assert "bounded safety wait" in calls[0]["message"]
    assert "20 seconds" in calls[0]["detail_lines"][0]
