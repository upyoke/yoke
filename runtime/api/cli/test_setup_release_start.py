"""Setup moves onto the served release before it asks any project question."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import onboard
from yoke_cli.config import onboard_apply_lock, setup_release_follow, setup_release_marker
from yoke_cli.config import setup_release_start
from yoke_cli.config import onboard_wizard_flow_machine_admission as admission

RUNNING = "0.2.0.202611211930"
SERVED = "0.2.0.202611212023"
API = "https://yoke.example/api/orgs/acme"


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(setup_release_marker.FOLLOWED_RELEASE_ENV, raising=False)
    state = {"served": SERVED, "installs": [], "health": []}

    def health(api_url, *, timeout_s):
        state["health"].append(api_url)
        if state["served"] is None:
            raise setup_release_start.server_connect.ServerConnectError("down")
        return {"status": "ok", "engine_version": state["served"]}

    def install_release(target, yoke_bin, **_kwargs):
        assert onboard_apply_lock.lock_path().is_file()  # the relay follow waits
        state["installs"].append(target.version)
        return target.version

    follow = setup_release_follow
    monkeypatch.setattr(setup_release_start, "local_handshake_version", lambda: RUNNING)
    monkeypatch.setattr(setup_release_start.server_connect, "verify_server_health", health)
    monkeypatch.setattr(follow.shutil, "which", lambda _name: "/bin/yoke")
    for module in (follow, setup_release_start):
        monkeypatch.setattr(
            module.install_binding, "require_packaged_install", lambda _c: {}
        )
    monkeypatch.setattr(
        follow.self_update, "resolve_target",
        lambda *, version: argparse.Namespace(version=version),
    )
    monkeypatch.setattr(follow.self_update, "install_release", install_release)
    return state


def _start(destination="hosted"):
    setup_release_start.check_at_start(argparse.Namespace(api_url=API), destination)


def test_known_server_on_another_release_installs_it_before_any_question(host):
    with pytest.raises(setup_release_follow.ReleaseFollowed) as exc:
        _start()

    assert host["health"] == [API]
    assert host["installs"] == [SERVED]
    assert exc.value.run_id == ""
    assert not onboard_apply_lock.lock_path().exists()


@pytest.mark.parametrize(
    "case", ["same", "unreadable", "not-a-release", "local", "already-followed"]
)
def test_start_goes_on_without_installing(host, monkeypatch, case):
    if case == "same":
        host["served"] = RUNNING
    elif case == "unreadable":
        host["served"] = None
    elif case == "not-a-release":
        host["served"] = "dev"
    elif case == "already-followed":
        monkeypatch.setenv(
            setup_release_marker.FOLLOWED_RELEASE_ENV,
            setup_release_marker.encode(RUNNING, SERVED),
        )
    _start("local" if case == "local" else "hosted")

    assert host["installs"] == []


def test_source_checkout_never_follows(host, monkeypatch):
    def source(_command):
        raise setup_release_start.install_binding.SourceCheckoutError("source")

    monkeypatch.setattr(
        setup_release_start.install_binding, "require_packaged_install", source
    )
    _start()

    assert host["installs"] == []


def test_failed_install_refuses_with_update_recovery(host, monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise setup_release_follow.self_update.SelfUpdateError("installer exit 1")

    monkeypatch.setattr(setup_release_follow.self_update, "install_release", fail)
    monkeypatch.setattr(
        onboard, "_onboard", lambda _parsed: setup_release_start.check_at_start(
            argparse.Namespace(api_url=API), "hosted"
        ),
    )

    assert onboard.onboard(["--connect", API]) == 1
    err = capsys.readouterr().err
    assert "setup_release_install_failed" in err and "installer exit 1" in err
    assert f"yoke update --version {SERVED}" in err


def test_setup_reruns_the_same_command_with_the_follow_marker(host, monkeypatch):
    calls = []
    monkeypatch.setattr(onboard, "_onboard", lambda _parsed: _start())
    monkeypatch.setattr(setup_release_follow.os, "name", "posix")
    monkeypatch.setattr(
        setup_release_follow.os, "execve",
        lambda path, argv, env: calls.append((path, argv, env)),
    )
    onboard.onboard(["--tui", "--connect", API, "--machine-github", "disabled"])

    path, argv, env = calls[0]
    assert argv == [
        "/bin/yoke", "setup", "--tui", "--connect", API, "--machine-github", "disabled",
    ]
    marker = json.loads(env[setup_release_marker.FOLLOWED_RELEASE_ENV])
    assert marker == {"from": RUNNING, "to": SERVED, "run_id": ""}


def test_agent_rerun_drops_the_answer_it_already_gave(monkeypatch):
    followed = setup_release_follow.ReleaseFollowed("", RUNNING, SERVED, "/bin/yoke")
    seen = []
    monkeypatch.setattr(
        setup_release_follow, "run_on_release",
        lambda yoke_bin, args, marker: seen.append(args) or 0,
    )
    parsed = argparse.Namespace(agent=True, apply=False)
    setup_release_follow.resume(followed, parsed, ["--agent", "--answer", "k=v"])

    assert seen == [["setup", "--agent"]]


def test_sign_in_follows_and_closes_the_shell(host, monkeypatch):
    monkeypatch.setattr(
        admission.writer, "set_connection",
        lambda *_a, **_k: {"connection": {"credential_source": {"path": "/t"}}},
    )
    credential = SimpleNamespace(org="acme", api_url=API, token="secret")
    value = admission.save_machine_credential(credential, {"ok": True}, None)

    shell = SimpleNamespace(release_followed=None, exited=False)
    shell.exit = lambda: setattr(shell, "exited", True)
    admission.accept_machine_credential(shell, value)

    assert host["installs"] == [SERVED]
    assert shell.exited and shell.release_followed is value[3]


def test_sign_in_on_the_served_release_continues(host, monkeypatch):
    host["served"] = RUNNING
    monkeypatch.setattr(
        admission.writer, "set_connection",
        lambda *_a, **_k: {"connection": {"credential_source": {"path": "/t"}}},
    )
    credential = SimpleNamespace(org="acme", api_url=API, token="secret")
    value = admission.save_machine_credential(credential, {"ok": True}, None)

    assert value[3] is None and host["installs"] == []


def _signed_in_follow(host, monkeypatch, shell):
    monkeypatch.setattr(
        admission.writer, "set_connection",
        lambda *_a, **_k: {"connection": {"credential_source": {"path": "/t"}}},
    )
    credential = SimpleNamespace(org="acme", api_url=API, token="secret")
    value = admission.save_machine_credential(credential, {"ok": True}, None)
    admission.accept_machine_credential(shell, value)
    return value[3]


def test_sign_in_rerun_keeps_the_project_mode_asked_before_sign_in(host, monkeypatch):
    shell = SimpleNamespace(
        release_followed=None,
        _project_mode_preset=True,
        result=SimpleNamespace(project_mode="create-repo"),
        exit=lambda: None,
    )
    followed = _signed_in_follow(host, monkeypatch, shell)
    seen = []
    monkeypatch.setattr(
        setup_release_follow, "run_on_release",
        lambda yoke_bin, args, marker: seen.append(args) or 0,
    )
    setup_release_follow.resume(followed, argparse.Namespace(), ["--tui"])
    setup_release_follow.resume(
        followed, argparse.Namespace(), ["--tui", "--project-mode", "existing-folder"]
    )

    assert seen == [
        ["setup", "--tui", "--project-mode", "create-repo"],
        ["setup", "--tui", "--project-mode", "existing-folder"],
    ]


def test_sign_in_before_a_project_choice_carries_nothing(host, monkeypatch):
    shell = SimpleNamespace(
        release_followed=None,
        _project_mode_preset=False,
        result=SimpleNamespace(project_mode="machine-only"),
        exit=lambda: None,
    )

    assert _signed_in_follow(host, monkeypatch, shell).carried_args == []
