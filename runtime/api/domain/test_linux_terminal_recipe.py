"""Linux recipe completion, browser approval, redaction and bounded startup proof."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from yoke_core.domain.ssh_linux_terminal_recipe import execute_linux_recipe
from yoke_harness import ssh_linux_browser_approval
from yoke_harness.test_machine_types import HostActionResult

ORIGIN = "https://app.stage.upyoke.com"
ENTRY = ORIGIN + "/connect?user_code=AB12-CD34"
DESKTOP = {"DISPLAY": ":10", "XAUTHORITY": "/home/tester/.Xauthority"}


def _terminal(monkeypatch, events, transcript, *, close_ok=True):
    class Terminal:
        session = "fake-session"

        def __init__(self, control):
            pass

        def open(self, entry_surface, size, environment=None):
            events.append(("open", entry_surface, size, environment))
            return True

        def transcript(self):
            return transcript

        def close(self):
            events.append("closed")
            return close_ok

    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.LinuxTerminal", Terminal
    )
    for module in ("ssh_linux_terminal_recipe", "ssh_linux_browser_gate"):
        monkeypatch.setattr(
            f"yoke_core.domain.{module}.send_recipe_keys",
            lambda *a, **kw: events.append(("keys", kw["keys"])) or True,
        )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.time.sleep",
        lambda delay: events.append(delay),
    )


def _control(**fields):
    return SimpleNamespace(
        secret_values=("opaque-credential",),
        _upload_bytes=lambda *a: True,
        _run=lambda *a, **kw: None,
        **fields,
    )


def _gate_recipe():
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["expected_text"] = ["Machine connected."]
    config["actions"] = [
        {
            "step": "operator-browser-approval",
            "keys": ["Enter"],
            "capture": False,
            "operator_gate": "machine_browser_approval",
            "completion_text": ["Machine connected."],
            "gate_timeout_seconds": 60.0,
        },
        {"step": "done", "keys": [], "capture": False},
    ]
    return config


@pytest.mark.parametrize("mode", ["complete", "cleanup_failed", "over_budget"])
def test_linux_recipe_completion_and_failures_use_shared_protocol(monkeypatch, mode):
    events = []
    _terminal(
        monkeypatch,
        events,
        "ready opaque-credential\n__YOKE_EXIT_0\n",
        close_ok=mode != "cleanup_failed",
    )
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["start_delay"] = 1.0 if mode != "over_budget" else 31.0
    result = execute_linux_recipe(
        _control(),
        entry_surface="/usr/bin/true",
        required_completion="done",
        config=config,
        size=(120, 40),
    )
    assert events[-1] == "closed"
    assert "opaque-credential" not in str(result.evidence)
    if mode == "complete":
        assert result.ok
        assert events[0] == ("open", "/usr/bin/true", (120, 40), None)
        assert result.evidence["steps"][0]["key"] == "done"
        assert result.evidence["steps"][0]["reached"]
        assert result.evidence["exit_code"] == 0
        assert 1.0 in events
    else:
        assert not result.ok
        assert (
            result.error_code
            == {
                "cleanup_failed": "linux_tmux_cleanup_failed",
                "over_budget": "terminal_recipe_timed_out",
            }[mode]
        )


def test_operator_gate_approves_through_desktop_chromium(monkeypatch, capsys):
    events, host_calls = [], []
    _terminal(
        monkeypatch,
        events,
        f"Open: {ENTRY}\nOne-time code: AB12-CD34\nMachine connected.\n__YOKE_EXIT_0\n",
    )
    monkeypatch.setattr(
        ssh_linux_browser_approval,
        "ensure_desktop",
        lambda control: {"environment": DESKTOP, "desktop_session": "reused"},
    )

    def host(_control, command, *arguments, desktop=True):
        host_calls.append(command)
        return {
            "prepare": {"ok": True, "chromium": "started"},
            "tabs": {"ok": True, "urls": [ENTRY]},
            "approve": {
                "ok": True,
                "state": "approved",
                "starting_url": ENTRY,
                "result_url": ORIGIN + "/orgs/acme/frontier",
            },
        }[command]

    monkeypatch.setattr(ssh_linux_browser_approval, "_host", host)
    result = execute_linux_recipe(
        _control(capture_terminal_checkpoint=lambda: {"artifact_handle": "frame-1"}),
        entry_surface="yoke setup",
        required_completion="done",
        config=_gate_recipe(),
        size=(120, 40),
        allowed_operator_urls=(ORIGIN,),
    )
    assert result.ok, result.evidence
    # The installer runs on the desktop so its link opens in that Chromium.
    assert events[0] == ("open", "yoke setup", (120, 40), DESKTOP)
    assert host_calls == ["prepare", "tabs", "approve"]
    gate = result.evidence["steps"][0]
    assert gate["browser_approval"] == {
        "browser": "Chromium",
        "approval_entry": "/connect",
        "result_url": ORIGIN + "/orgs/acme/frontier",
        "visible_control": "Approve machine",
    }
    assert gate["artifact_handle"] == "frame-1"
    assert gate["browser_automation_error_code"] is None
    event = json.loads(capsys.readouterr().out.splitlines()[0])
    assert event["approval_automation"] == "self_approving_visible_chromium"


def test_operator_gate_without_a_desktop_refuses_with_a_named_reason(monkeypatch):
    events = []
    _terminal(monkeypatch, events, "")

    def no_desktop(control):
        raise RuntimeError("linux_desktop_session_required: no XFCE session")

    monkeypatch.setattr(ssh_linux_browser_approval, "ensure_desktop", no_desktop)
    result = execute_linux_recipe(
        _control(),
        entry_surface="yoke setup",
        required_completion="done",
        config=_gate_recipe(),
        size=(120, 40),
        allowed_operator_urls=(ORIGIN,),
    )
    assert not result.ok
    assert result.error_code == "headless_linux_browser_approval_unavailable"
    assert "linux_desktop_session_required" in result.evidence["recovery"]
    assert "linux-host-provisioning.md" in result.evidence["recovery"]
    assert not any(event[0] == "open" for event in events if isinstance(event, tuple))


def test_chromium_refusal_stops_before_the_installer_starts(monkeypatch):
    events = []
    _terminal(monkeypatch, events, "")
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.prepare_desktop_chromium",
        lambda control: HostActionResult(
            False,
            {"recovery": "Run xdg-settings set default-web-browser chromium.desktop."},
            "linux_desktop_default_browser_not_chromium",
        ),
    )
    result = execute_linux_recipe(
        _control(),
        entry_surface="yoke setup",
        required_completion="done",
        config=_gate_recipe(),
        size=(120, 40),
        allowed_operator_urls=(ORIGIN,),
    )
    assert result.error_code == "linux_desktop_default_browser_not_chromium"
    assert "xdg-settings" in result.evidence["recovery"]
    assert events == ["closed"]


def _ready_recipe():
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["actions"] = [
        {
            "step": "uv-consent",
            "keys": ["Enter"],
            "capture": False,
            "ready_text": ["Install uv now?"],
            "ready_timeout_seconds": 0.05,
        },
        {"step": "done", "keys": [], "capture": False},
    ]
    return config


def test_step_whose_ready_text_never_appears_fails_by_name(monkeypatch):
    events = []
    _terminal(monkeypatch, events, "Starting Yoke setup\n")
    result = execute_linux_recipe(
        _control(),
        entry_surface="/usr/bin/true",
        required_completion="done",
        config=_ready_recipe(),
        size=(120, 40),
    )
    assert result.error_code == "terminal_action_not_ready"
    assert result.evidence["step"] == "uv-consent"
    assert result.evidence["waiting_for"] == ["Install uv now?"]
    assert not any(event[0] == "keys" for event in events if isinstance(event, tuple))


def test_setup_exit_before_its_prompt_reports_that_exit(monkeypatch):
    events = []
    refusal = "setup_terminal_ownership_lost: setup stopped. Run `yoke setup` again."
    _terminal(monkeypatch, events, f"Starting Yoke setup\n{refusal}\n__YOKE_EXIT_1\n")
    config = _ready_recipe()
    config["actions"][0]["ready_timeout_seconds"] = 300
    result = execute_linux_recipe(
        _control(),
        entry_surface="/usr/bin/true",
        required_completion="done",
        config=config,
        size=(120, 40),
    )
    assert result.error_code == "terminal_setup_exited"
    assert result.evidence["step"] == "uv-consent"
    assert result.evidence["setup_exit"] == {"exit_code": 1, "refusal": refusal}
