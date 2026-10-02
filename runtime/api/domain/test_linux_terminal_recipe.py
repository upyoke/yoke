"""Linux recipe completion, credential redaction and bounded startup proof."""

from types import SimpleNamespace
import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from yoke_core.domain.ssh_linux_terminal_recipe import execute_linux_recipe
from yoke_core.domain.machine_qa_saved_profile_approval import BrowserApprovalResult
from runtime.api.domain.machine_qa_browser_flow_test_support import (
    EXAMPLE_FLOW,
    EXAMPLE_ORIGIN,
)


@pytest.mark.parametrize(
    "mode", ["complete", "cleanup_failed", "operator_gate", "over_budget"]
)
def test_linux_recipe_completion_and_failures_use_shared_protocol(monkeypatch, mode):
    events = []

    class Terminal:
        session = "fake-session"

        def __init__(self, control):
            pass

        def open(self, entry_surface, size):
            events.append((entry_surface, size))
            return True

        def transcript(self):
            return "ready opaque-credential\n__YOKE_EXIT_0\n"

        def close(self):
            events.append("closed")
            return mode != "cleanup_failed"

    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.LinuxTerminal", Terminal
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.send_recipe_keys",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.time.sleep",
        lambda delay: events.append(delay),
    )
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["start_delay"] = 1.0 if mode != "over_budget" else 31.0
    if mode == "operator_gate":
        config["actions"][0]["operator_gate"] = {"kind": "browser_approval"}
    result = execute_linux_recipe(
        SimpleNamespace(
            secret_values=("opaque-credential",),
            _upload_bytes=lambda *a: True,
            _run=lambda *a, **kw: None,
        ),
        entry_surface="/usr/bin/true",
        required_completion="done",
        config=config,
        size=(120, 40),
    )
    assert events[-1] == "closed"
    assert "opaque-credential" not in str(result.evidence)
    if mode == "complete":
        assert result.ok
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
                "operator_gate": "machine_browser_approval_kind_invalid",
                "over_budget": "terminal_recipe_timed_out",
            }[mode]
        )


def test_linux_browser_gate_uses_registered_candidate_and_terminal_completion(
    monkeypatch,
):
    closed, approvals = [], []
    code = "AB12-CD34"
    gate_text = f"ready\nOne-time code: {code}\nOpen: {EXAMPLE_ORIGIN}/connect\n"
    transcripts = iter((gate_text, gate_text, gate_text + "connected\n"))

    class Terminal:
        session = "registered-terminal"

        def __init__(self, control):
            self.control = control

        def open(self, entry_surface, size):
            return True

        def transcript(self):
            return next(transcripts, gate_text + "connected\n__YOKE_EXIT_0\n")

        def close(self):
            closed.append(True)
            return True

    control = SimpleNamespace(
        material=SimpleNamespace(project_id=1),
        secret_values=(),
        _upload_bytes=lambda *args: True,
        _run=lambda *args, **kw: None,
    )

    def approve(actual_control, **kw):
        assert actual_control is control
        assert kw["verification_url"] == EXAMPLE_ORIGIN + "/connect"
        assert kw["user_code"] == code
        assert kw["flow"] == EXAMPLE_FLOW
        assert 0 < kw["timeout_seconds"] <= 20
        approvals.append(True)
        return BrowserApprovalResult(True, {"browser": "candidate-daemon"})

    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.LinuxTerminal", Terminal
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.send_recipe_keys",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.time.sleep", lambda seconds: None
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_saved_profile_approval.approve_machine_from_profile",
        approve,
    )
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["actions"][0].update(
        operator_gate="machine_browser_approval",
        browser_approval=EXAMPLE_FLOW,
        gate_timeout_seconds=20,
        completion_text=["connected"],
    )
    result = execute_linux_recipe(
        control,
        entry_surface="candidate onboard",
        required_completion="done",
        config=config,
        size=(120, 40),
        allowed_operator_urls=(EXAMPLE_ORIGIN,),
    )
    assert result.ok
    assert approvals == [True]
    assert closed == [True]
    assert result.evidence["steps"][0]["browser_approval"] == {
        "browser": "candidate-daemon"
    }
