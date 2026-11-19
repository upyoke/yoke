"""Layouts recognized by the sealed macOS Claude Desktop probe, and its causes."""

from __future__ import annotations

import subprocess

import pytest

from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.macos_claude_desktop_probe import (
    _AUTHENTICATION_SWIFT,
    _SWIFT,
    CLAUDE_DESKTOP_PROBE_PROGRAM,
)
from yoke_harness.standard_baseline_probes import standard_probe_failure

# Each fixture is one window frame as Vision reads it: all text, the sidebar
# navigation, and the account footer. Account names are fixture placeholders.
_FIXTURES = """
let switcher: Set<String> = ["chat", "cowork", "code"]
let footer: Set<String> = ["Example User · Max"]
let chat = (sidebar: Set<String>(["+ new chat", "chats", "projects"]), text: switcher)
let chatArtifacts = (sidebar: Set<String>(["+ new", "projects", "artifacts"]), text: switcher)
let code = (sidebar: Set<String>(["+ new", "search", "artifacts", "customize"]), text: switcher)
let cowork = (sidebar: Set<String>(["+ new task", "scheduled"]), text: Set<String>(["chat cowork code"]))
let firstRun: Set<String> = ["claude for mac", "get started"]
let signIn: Set<String> = ["sign in", "continue with google", "continue with email"]

func outcome(_ text: Set<String>, _ sidebar: Set<String>, _ footer: Set<String> = []) -> Int32? {
    classify(text: text.union(sidebar), sidebar: sidebar) { footer }
}

// Every signed-in tab passes from its sidebar plus the switcher or the footer.
precondition(outcome(chat.text, chat.sidebar) == signedIn)
precondition(outcome(chatArtifacts.text, chatArtifacts.sidebar) == signedIn)
precondition(outcome(code.text, code.sidebar) == signedIn)
precondition(outcome(cowork.text, cowork.sidebar) == signedIn)
precondition(outcome([], code.sidebar, footer) == signedIn)
precondition(outcome([], cowork.sidebar, ["Example User • Pro v"]) == signedIn)
// The first-run and Sign In screens are signed out, whatever else is read.
precondition(outcome(firstRun, []) == signedOut)
precondition(outcome(signIn, []) == signedOut)
precondition(outcome(signIn.union(switcher), code.sidebar, footer) == signedOut)
// Sidebar markers without account proof, or no known layout, keep looking;
// a deadline reached that way reports an unrecognized layout.
precondition(outcome([], code.sidebar, ["upgrade to pro"]) == nil)
precondition(outcome([], cowork.sidebar, ["ultra"]) == nil)
precondition(outcome(switcher, ["settings"], footer) == nil)
precondition(outcome(["claude for mac"], []) == nil)
precondition(layoutUnrecognized != signedOut)
"""


@pytest.mark.macos_only(reason="runs the probe's Swift classifier with the macOS SDK")
def test_layout_fixtures_map_to_outcomes(tmp_path):
    script = tmp_path / "classify.swift"
    script.write_text(
        "import Foundation\n" + _AUTHENTICATION_SWIFT + _FIXTURES, encoding="utf-8"
    )
    subprocess.run(
        ["/usr/bin/swift", str(script)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


@pytest.mark.macos_only(reason="type-checks the sealed Swift program with the macOS SDK")
def test_sealed_swift_program_type_checks(tmp_path):
    script = tmp_path / "probe.swift"
    script.write_text(_SWIFT, encoding="utf-8")
    subprocess.run(
        ["/usr/bin/swiftc", "-typecheck", str(script)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    ("swift_exit", "cause"),
    [
        (0, None),
        (10, "probe_check_unmet"),
        (13, "probe_request_timed_out"),
        (14, "probe_layout_unrecognized"),
        (99, "probe_launch_failed"),
    ],
)
def test_program_maps_swift_exits_to_named_causes(monkeypatch, swift_exit, cause):
    def fake_run(argv, **_kwargs):
        assert argv[0] == "/usr/bin/swift"
        return subprocess.CompletedProcess(argv, swift_exit)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exited:
        exec(CLAUDE_DESKTOP_PROBE_PROGRAM, {"EXIT": PROBE_EXIT_CODES})
    assert exited.value.code == (0 if cause is None else PROBE_EXIT_CODES[cause])


def test_unrecognized_layout_never_tells_the_operator_to_sign_in():
    failure = standard_probe_failure(
        "Claude desktop signed in", PROBE_EXIT_CODES["probe_layout_unrecognized"]
    )
    assert failure["cause"] == "probe_layout_unrecognized"
    assert "Do not sign in again" in failure["recovery"]
    assert "golden-capture" not in failure["recovery"]
    signed_out = standard_probe_failure(
        "Claude desktop signed in", PROBE_EXIT_CODES["probe_check_unmet"]
    )
    assert signed_out["cause"] == "probe_check_unmet"
    assert "Chat, Code or Cowork" in signed_out["recovery"]
