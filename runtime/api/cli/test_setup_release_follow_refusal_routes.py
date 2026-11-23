"""A failed release follow is reported as itself, never as a failed sign-in."""

import argparse
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import onboard, onboard_agent
from yoke_cli.config import onboard_wizard_flow_hosted_machine as hosted
from yoke_cli.config import onboard_wizard_flow_machine_admission as admission
from yoke_cli.config import setup_agent_approvals as approvals
from yoke_cli.config import setup_release_follow as follow
from yoke_cli.config import setup_release_start as start
from yoke_cli.config import self_update

CODE = "windows_scheduled_install_failed"
REFUSAL = start.StartFollowRefused(f"{CODE}: no desktop. Next: sign in", code=CODE)


class Base:
    def __init__(self):
        self.errors, self.accepted = [], []

    def _goto_hosted_machine_error(self, message):
        self.errors.append(message)


class Shell(approvals.AgentApprovals, Base):
    def __init__(self, saved):
        Base.__init__(self)
        self.result = SimpleNamespace(config_path=None)
        self._answers = SimpleNamespace(pending_approval=saved, keep_pending_approval=self._keep)
        self.kept = []

    def _keep(self, value):
        self.kept.append(value)
        self._answers.pending_approval = value


def test_agent_follow_failure_is_not_saved_as_a_sign_in_error(monkeypatch):
    credential = SimpleNamespace(org="acme", api_url="https://a", token="t")
    stored = []
    monkeypatch.setattr(approvals.hosted_machine_authorization, "poll_once", lambda _p: credential)
    monkeypatch.setattr(approvals.yoke_token_verify, "verify", lambda *_a: {"ok": True})
    monkeypatch.setattr(
        approvals, "store_machine_credential",
        lambda *a: stored.append(a) or (credential, {"ok": True}, "/token"),
    )

    def refuse(_url):
        raise REFUSAL

    monkeypatch.setattr(admission.setup_release_start, "follow_after_sign_in", refuse)
    shell = Shell({"kind": "machine", "device_code": "d"})
    with pytest.raises(start.StartFollowRefused):
        shell._poll_hosted_machine_authorization(SimpleNamespace(device_code="d"), "")
    assert len(stored) == 1 and shell.errors == []
    assert shell.kept == [None] and shell._answers.pending_approval is None


def test_agent_surface_emits_the_refusal_code(monkeypatch):
    emitted = []
    monkeypatch.setattr(onboard_agent.responses, "emit", emitted.append)
    monkeypatch.setattr(
        onboard_agent.answers, "open_store",
        lambda: SimpleNamespace(release=lambda: None, waiting_key=None),
    )
    monkeypatch.setattr(onboard_agent, "_apply_presets", lambda *_a: None)
    monkeypatch.setattr(
        onboard_agent.onboard_resume, "prepare_run",
        lambda _p: SimpleNamespace(error=None, destination=None, env_name="e"),
    )

    def refuse(*_a):
        raise REFUSAL

    monkeypatch.setattr(onboard_agent.setup_release_start, "check_at_start", refuse)
    parsed = argparse.Namespace(agent_answers=[], discard=False)
    code = onboard_agent.run(parsed, defaults=argparse.Namespace())
    assert code == onboard_agent.responses.EXIT_CODES[onboard_agent.responses.STATE_REFUSED]
    assert emitted[0]["reason"] == CODE and "sign in" in emitted[0]["recovery"]


def test_tui_poll_error_exits_with_the_refusal_not_the_sign_in_view():
    captured = {}
    shell = SimpleNamespace(
        result=SimpleNamespace(config_path=None),
        follow_refused=None,
        exited=False,
        _run_checking=lambda **kw: captured.update(kw),
        _approval_detail_lines=lambda *_a: [],
        _approval_copy_targets=lambda _p: (),
        _approval_human=lambda _p: None,
        _goto_hosted_machine_error=lambda _m: pytest.fail("routed to sign-in error"),
        _goto_hosted_machine_denied=lambda _m: pytest.fail("routed to denial"),
    )
    shell.exit = lambda: setattr(shell, "exited", True)
    hosted.HostedMachineConnectFlow._poll_hosted_machine_authorization(shell, object(), "")
    captured["on_error"](REFUSAL)
    assert shell.exited and shell.follow_refused is REFUSAL


def test_closed_wizard_reraises_and_setup_prints_it_with_exit_one(monkeypatch, capsys):
    shell = SimpleNamespace(release_followed=None, follow_refused=REFUSAL)

    def wizard(_parsed):
        admission.raise_carried_follow(shell)
        return 0

    monkeypatch.setattr(onboard, "_onboard", wizard)
    assert onboard.onboard([]) == 1
    assert f"error: {CODE}" in capsys.readouterr().err


def test_scheduled_refusal_keeps_its_recovery_through_the_start_follow(monkeypatch):
    text = f"{CODE}: failed. Next: sign in at this machine's desktop"

    def refuse(_version):
        raise self_update.ScheduledInstallRefused(text)

    monkeypatch.setattr(start, "local_handshake_version", lambda: "0.2.0.1")
    monkeypatch.setattr(start, "_served_release", lambda _u: "0.2.0.202611230628")
    monkeypatch.setattr(start.install_binding, "require_packaged_install", lambda _c: None)
    monkeypatch.setattr(start.setup_release_marker, "current", lambda: None)
    monkeypatch.setattr(follow, "install_exact", refuse)
    monkeypatch.setattr(
        start.onboard_apply_lock, "acquire",
        lambda: __import__("contextlib").nullcontext(),
    )
    with pytest.raises(start.StartFollowRefused) as caught:
        start.follow_after_sign_in("https://a")
    assert caught.value.code == CODE and str(caught.value) == text
    assert "yoke update`" not in str(caught.value)
