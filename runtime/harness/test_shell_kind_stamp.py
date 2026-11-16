"""Each harness's shell tools resolve to a shell kind the client stamps."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.harness_shell_tools import (
    HARNESS_SHELL_TOOLS,
    SHELL_KIND_PAYLOAD_KEY,
    payload_shell_kind,
    shell_kind_for,
    shell_tools,
)
from yoke_contracts.hook_tool_names import canonicalize_shell_payload, payload_tool_name
from yoke_harness.hooks.shell_kind_stamp import stamp_shell_kind

pytestmark = pytest.mark.windows


def test_every_harness_declares_its_shell_tools() -> None:
    assert set(HARNESS_SHELL_TOOLS) == set(CANONICAL_HARNESS_IDS)
    with pytest.raises(KeyError, match="harness_shell_tools"):
        shell_tools("unknown-harness")


@pytest.mark.parametrize(
    ("harness", "tool", "windows", "expected"),
    [
        ("claude-code", "Bash", True, "bash"),  # Git Bash keeps the Bash parser.
        ("claude-code", "PowerShell", False, "powershell"),
        ("claude-code", "PowerShell", True, "powershell"),
        ("codex", "Bash", True, "powershell"),
        ("codex", "shell", False, "bash"),
        ("cursor", "Shell", True, "powershell"),
        ("cursor", "", False, "bash"),
        ("claude-code", "Edit", True, None),
    ],
)
def test_shell_kind_follows_tool_and_os(harness, tool, windows, expected) -> None:
    assert shell_kind_for(harness, tool, windows=windows) == expected


def _stamped(payload: dict, executor: str, *, windows: bool) -> dict:
    return json.loads(stamp_shell_kind(json.dumps(payload), executor, windows=windows))


def test_claude_powershell_is_stamped_and_canonicalized_where_evaluated() -> None:
    out = _stamped(
        {"tool_name": "PowerShell", "tool_input": {"command": "git status"}},
        "claude",
        windows=True,
    )
    # The client keeps the native name: an older server keeps its own routing.
    assert out[SHELL_KIND_PAYLOAD_KEY] == "powershell"
    assert out["tool_name"] == "PowerShell"
    assert payload_tool_name(out) == "Bash"
    canonical = canonicalize_shell_payload(dict(out))
    assert canonical["tool_name"] == "Bash"
    assert payload_shell_kind(canonical) == "powershell"


def test_evaluator_canonicalizes_an_unstamped_shell_payload() -> None:
    claude = canonicalize_shell_payload({"tool_name": "PowerShell"})
    assert claude == {"tool_name": "Bash", SHELL_KIND_PAYLOAD_KEY: "powershell"}
    cursor = canonicalize_shell_payload({"tool_name": "Shell"})
    assert cursor == {"tool_name": "Bash", SHELL_KIND_PAYLOAD_KEY: "bash"}
    assert canonicalize_shell_payload({"tool_name": "Edit"}) == {"tool_name": "Edit"}


def test_codex_and_cursor_shells_follow_the_client_os() -> None:
    codex = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert _stamped(codex, "codex", windows=True)[SHELL_KIND_PAYLOAD_KEY] == "powershell"
    assert _stamped(codex, "codex", windows=False)[SHELL_KIND_PAYLOAD_KEY] == "bash"
    gate = {"hook_event_name": "beforeShellExecution", "command": "dir"}
    stamped = _stamped(gate, "cursor", windows=True)
    assert stamped[SHELL_KIND_PAYLOAD_KEY] == "powershell"
    assert "tool_name" not in stamped and payload_tool_name(stamped) == "Bash"


def test_non_shell_tools_and_foreign_input_pass_through() -> None:
    edit = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "a"}})
    assert stamp_shell_kind(edit, "claude", windows=True) == edit
    assert stamp_shell_kind("not json", "claude", windows=True) == "not json"
    assert stamp_shell_kind(edit, "no-such-harness", windows=True) == edit


def test_unstamped_payload_falls_back_to_the_tool_name() -> None:
    assert payload_shell_kind({"tool_name": "PowerShell"}) == "powershell"
    assert payload_shell_kind({"tool_name": "Bash"}) == "bash"
    assert payload_shell_kind({SHELL_KIND_PAYLOAD_KEY: "bash", "tool_name": "PowerShell"}) == "bash"


def test_claude_machine_hook_matches_both_shell_tools() -> None:
    (pre,) = [e for e in HARNESS_MACHINE_HOOKS["claude-code"].events if e.verb == "PreToolUse"]
    assert set(pre.matcher.split("|")) == {
        name for name, kind in HARNESS_SHELL_TOOLS["claude-code"].items() if name
    }
