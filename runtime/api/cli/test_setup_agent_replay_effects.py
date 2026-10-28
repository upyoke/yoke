"""Setup steps with real effects run once; replay after each answer takes the same path.

Machine approval, a self-host first boot, a backup restore, GitHub sign-in and
the git installer each change this machine before Review. Every answer below
is followed by a bare call that rebuilds the run from the store, and each
effect is counted so a replay that repeats one fails here.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_cli.config import (
    github_device_flow,
    github_machine,
    hosted_machine_authorization,
    local_universe_setup,
    machine_config,
    onboard_backup,
    onboard_docker_prerequisites,
    onboard_self_host_server,
    project_git_prerequisite,
    writer,
    yoke_token_verify,
)

pytest.importorskip("textual")

TOKEN = "token-never-shown"
VERIFIED = {
    "ok": True,
    "actor": {"label": "Test Person"},
    "orgs": [{"name": "Acme"}],
    "projects": [],
}
TO_PROJECT = ("connect.admin_name=Test Person", "github.machine=skip")


@pytest.fixture
def drive(tmp_path: Path, monkeypatch, capsys) -> AgentDriver:
    isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(yoke_token_verify, "verify", lambda *_a, **_k: VERIFIED)
    return AgentDriver(capsys)


@pytest.fixture
def approvals(monkeypatch) -> list[str]:
    from yoke_contracts.machine_authorization import (
        HostedMachineCredential,
        PendingMachineAuthorization,
    )

    started: list[str] = []

    def start(*_a, **_k):
        started.append(f"CODE-{len(started) + 1}")
        return PendingMachineAuthorization(
            platform_url="https://app.upyoke.com",
            device_code=f"device-{started[-1]}",
            user_code=started[-1],
            verification_uri="https://app.upyoke.com/machine",
            verification_uri_complete="https://app.upyoke.com/machine?code=x",
            expires_in=600,
            interval=5,
        )

    credential = HostedMachineCredential(
        api_url="https://app.upyoke.com/api/orgs/acme", org="acme", token=TOKEN
    )
    monkeypatch.setattr(hosted_machine_authorization, "start", start)
    monkeypatch.setattr(
        hosted_machine_authorization, "poll_once", lambda *_a, **_k: credential
    )
    return started


def _through_approval(drive: AgentDriver, answer: str) -> None:
    assert drive.replayed(answer)["state"] == "browser"
    assert drive.replayed()["key"] == "github.machine"
    for step in ("github.machine=skip",):
        drive.replayed(step)


def test_a_fresh_approval_is_reused_on_every_later_call(drive, approvals):
    assert drive.replayed("project.mode=machine-only")["key"] == "connect.destination"

    _through_approval(drive, "connect.destination=hosted")

    assert approvals == ["CODE-1"]


def test_an_approval_that_replaced_a_saved_connection_is_not_asked_again(
    drive, approvals
):
    writer.set_connection(
        "old",
        transport="https",
        api_url="https://app.upyoke.com/api/orgs/old",
        token=TOKEN,
        activate=True,
        path=str(machine_config.config_path(None)),
    )
    assert drive.replayed("project.mode=machine-only")["key"] == "connect.saved_destination"

    _through_approval(drive, "connect.saved_destination=hosted")

    assert approvals == ["CODE-1"]


def test_github_sign_in_replays_to_the_connected_question(drive, monkeypatch):
    saved = {"authorized": False}
    device = github_device_flow.DeviceAuthorization(
        device_code="gh-device",
        user_code="ABCD-0001",
        verification_uri="https://github.com/login/device",
        expires_in=900,
        interval=5,
    )
    starts: list[str] = []
    monkeypatch.setattr(
        github_device_flow, "start", lambda **_k: starts.append("x") or device
    )
    monkeypatch.setattr(github_device_flow, "poll_once", lambda *_a, **_k: "gh-token")

    def connect(*, device_authorize, **_kw):
        device_authorize(client_id="client", web_url="https://github.com", opener=None)
        saved["authorized"] = True  # the real connect saves it in machine config
        return {"ok": True, "ready": True, "configured": True}

    monkeypatch.setattr(github_machine, "connect", connect)
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda *_a, **_k: (
            {"authorization": {"status": "authorized"}} if saved["authorized"] else {}
        ),
    )
    monkeypatch.setattr(
        github_machine,
        "status",
        lambda **_k: {"ok": True, "ready": True, "configured": True},
    )
    drive.replay_each(("project.mode=machine-only", "connect.destination=local", "connect.local_universe=fresh"))
    drive.replayed("connect.admin_name=Test Person")

    assert drive.replayed("github.machine=connect")["state"] == "browser"
    connected = drive.replayed()

    assert connected["key"] == "github.connected"
    assert drive.replayed(f"github.connected={connected['answers'][0]['value']}")
    assert starts == ["x"]


def test_the_git_installer_opens_once(drive, monkeypatch):
    installs: list[str] = []
    advice = project_git_prerequisite.install_advice()
    monkeypatch.setattr(
        project_git_prerequisite,
        "require_git_available",
        lambda *_a, **_k: (_ for _ in ()).throw(
            project_git_prerequisite.MissingGitError("git is missing")
        ),
    )
    handoff_advice = dataclasses.replace(advice, requires_user_completion=True)
    monkeypatch.setattr(
        project_git_prerequisite,
        "install_git",
        lambda **_k: installs.append("open") or handoff_advice,
    )
    drive.replay_each(("project.mode=local-checkout", "connect.destination=local", "connect.local_universe=fresh"))
    assert drive.replay_each(TO_PROJECT)["key"] == (
        "project.project_git_missing"
    )

    handoff = drive.replayed("project.project_git_missing=install")

    assert handoff["key"] == "project.project_git_install_handoff"
    assert installs == ["open"]
    drive.replayed("project.project_git_install_handoff=install")
    assert installs == ["open", "open"]


def test_a_local_backup_restores_once(drive, monkeypatch, tmp_path: Path):
    archive = tmp_path / "backup.tar"
    archive.write_text("backup")
    imports: list[tuple] = []
    report = {"archive": str(archive), "receipt": {"org": "Acme"}, "sha256": "abc"}
    restored = {"done": False}
    real_inspect = local_universe_setup.inspect_local_state

    def command(_config, *args, **_kwargs):
        if "import" in args:
            imports.append(args)
            restored["done"] = True
        return {"ok": True, "actor_id": 19}

    monkeypatch.setattr(onboard_backup, "validate", lambda *_a: report)
    monkeypatch.setattr(onboard_backup, "command", command)
    monkeypatch.setattr(
        onboard_backup, "projects", lambda _shell: [{"id": 12, "slug": "demo"}]
    )
    monkeypatch.setattr(
        local_universe_setup,
        "inspect_local_state",
        lambda path=None: (
            {"state": local_universe_setup.LOCAL_UNIVERSE_VERIFY, "active": True}
            if restored["done"]
            else real_inspect(path)
        ),
    )

    line = drive.replay_each(
        (
            "project.mode=machine-only",
            "connect.destination=local",
            "connect.local_universe=backup",
            f"connect.backup_path={archive}",
            "connect.backup_confirm=apply",
        )
    )

    assert line["key"] == "github.machine"
    assert drive.replayed("github.machine=skip")["key"] == "project.restored"
    assert len(imports) == 1


def test_a_self_host_server_starts_once(drive, monkeypatch, tmp_path: Path):
    provisions: list[str] = []

    def provision(setup, _prerequisites):
        provisions.append(str(setup.directory))
        setup.directory.mkdir(parents=True, exist_ok=True)
        setup.connection = {"ok": True, "env": setup.env_name, "api_url": setup.url}
        writer.set_connection(
            setup.env_name,
            transport="https",
            api_url=setup.url,
            token=TOKEN,
            activate=True,
            path=setup.config_path,
        )
        return setup

    monkeypatch.setattr(
        onboard_docker_prerequisites,
        "check_docker_prerequisites",
        lambda: SimpleNamespace(executable="docker"),
    )
    monkeypatch.setattr(onboard_self_host_server, "provision", provision)

    complete = drive.replay_each(
        (
            "project.mode=machine-only",
            "connect.destination=self-host-server",
            "connect.self_host_server=start",
            "connect.server_start=fresh",
            "connect.admin_name=Test Person",
        )
    )

    assert complete["key"] == "connect.complete"
    assert drive.replayed("connect.complete=continue-setup")["key"] == (
        "github.machine"
    )
    assert len(provisions) == 1
