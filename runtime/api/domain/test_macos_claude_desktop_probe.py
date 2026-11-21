"""Layouts recognized by the sealed macOS Claude Desktop probe, and its causes."""

from __future__ import annotations

import sqlite3
import subprocess
import time

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
// Claude Desktop 6.6395.1 Code tab: Customize became Plugins, the mode switcher
// is icons only, and the footer reads the account and plan.
let code66395 = (
    sidebar: Set<String>(["+ new", "search", "artifacts", "plugins", "more"]),
    text: Set<String>(["new session", "choose environment", "describe a task or ask a question"])
)
let footer66395: Set<String> = ["example · ultra"]
// A redesign this probe has never seen: no known sidebar marker at all.
let redesigned = (
    sidebar: Set<String>(["home", "library", "agents"]),
    text: Set<String>(["what should we build?", "this computer", "choose folder"])
)
let firstRun: Set<String> = ["claude for mac", "get started"]
let signIn: Set<String> = ["sign in", "continue with google", "continue with email"]
let loading: Set<String> = ["claude"]

func outcome(
    _ text: Set<String>, _ sidebar: Set<String>, _ footer: Set<String> = [], session: Bool = false
) -> Int32? {
    classify(session: session, text: text.union(sidebar), sidebar: sidebar) { footer }
}

// The app's stored session signs in any rendered window, whatever its layout.
precondition(outcome(code66395.text, code66395.sidebar, session: true) == signedIn)
precondition(outcome(redesigned.text, redesigned.sidebar, session: true) == signedIn)
precondition(outcome(loading, [], session: true) == nil)
// The first-run and Sign In screens are signed out, with or without a session.
precondition(outcome(firstRun, [], session: true) == signedOut)
precondition(outcome(signIn, [], session: true) == signedOut)
precondition(outcome(firstRun, []) == signedOut)
precondition(outcome(signIn, []) == signedOut)
precondition(outcome(signIn.union(switcher), code.sidebar, footer) == signedOut)
// Without a readable session, every signed-in tab passes from its sidebar
// plus the switcher or the footer, including the 6.6395.1 Code layout.
precondition(outcome(chat.text, chat.sidebar) == signedIn)
precondition(outcome(chatArtifacts.text, chatArtifacts.sidebar) == signedIn)
precondition(outcome(code.text, code.sidebar) == signedIn)
precondition(outcome(cowork.text, cowork.sidebar) == signedIn)
precondition(outcome(code66395.text, code66395.sidebar, footer66395) == signedIn)
precondition(outcome([], code.sidebar, footer) == signedIn)
precondition(outcome([], cowork.sidebar, ["Example User • Pro v"]) == signedIn)
// Sidebar markers without account proof, or no known layout, keep looking;
// a deadline reached that way reports an unrecognized layout.
precondition(outcome(code66395.text, code66395.sidebar) == nil)
precondition(outcome(redesigned.text, redesigned.sidebar, footer) == nil)
precondition(outcome([], code.sidebar, ["upgrade to pro"]) == nil)
precondition(outcome([], cowork.sidebar, ["ultra"]) == nil)
precondition(outcome(switcher, ["settings"], footer) == nil)
precondition(outcome(["claude for mac"], []) == nil)
precondition(layoutUnrecognized != signedOut)

// Signed in passes only after it held for the settle period; a Sign In screen
// in between fails at once, and an unclassified frame restarts the wait.
var held = Verdicts()
precondition(held.add(signedIn, at: 0) == nil)
precondition(held.add(signedIn, at: settleSeconds - 1) == nil)
precondition(held.add(signedIn, at: settleSeconds) == signedIn)
var revoked = Verdicts()
precondition(revoked.add(signedIn, at: 0) == nil)
precondition(revoked.add(signedOut, at: 2) == signedOut)
var flicker = Verdicts()
precondition(flicker.add(signedIn, at: 0) == nil)
precondition(flicker.add(nil, at: 3) == nil)
precondition(flicker.add(signedIn, at: 4) == nil)
precondition(flicker.add(signedIn, at: 4 + settleSeconds) == signedIn)
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
        (11, "probe_app_open_failed"),
        (12, "probe_executable_missing"),
        (13, "probe_request_timed_out"),
        (14, "probe_layout_unrecognized"),
        (15, "probe_app_quit_blocked"),
        (99, "probe_launch_failed"),
    ],
)
def test_program_maps_swift_exits_to_named_causes(monkeypatch, tmp_path, swift_exit, cause):
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_run(argv, **_kwargs):
        assert argv[0] == "/usr/bin/swift"
        return subprocess.CompletedProcess(argv, swift_exit)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _run_program() == (0 if cause is None else PROBE_EXIT_CODES[cause])


# Chromium cookie expiry: microseconds since 1601-01-01.
_CHROMIUM_EPOCH_OFFSET = 11644473600


def _chromium_time(offset_seconds: float) -> int:
    return int((time.time() + _CHROMIUM_EPOCH_OFFSET + offset_seconds) * 1_000_000)


def _cookie_store(home, cookies):
    store = home / "Library/Application Support/Claude/Cookies"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.unlink(missing_ok=True)
    db = sqlite3.connect(store)
    db.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT,"
        " encrypted_value BLOB, expires_utc INTEGER)"
    )
    db.executemany(
        "INSERT INTO cookies VALUES (?, ?, '', x'00', ?)", cookies
    )
    db.commit()
    db.close()
    return store


def _run_program() -> int:
    with pytest.raises(SystemExit) as exited:
        exec(CLAUDE_DESKTOP_PROBE_PROGRAM, {"EXIT": PROBE_EXIT_CODES})
    return exited.value.code


def _record_swift_session(monkeypatch, seen, swift_exit=0, after=None):
    def fake_run(argv, **_kwargs):
        seen.append(argv[-1])
        if after is not None:
            after()
        return subprocess.CompletedProcess(argv, swift_exit)

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.mark.parametrize(
    ("cookies", "session"),
    [
        ([(".claude.ai", "sessionKey", 3600)], "session"),
        ([("claude.ai", "sessionKey", 3600)], "session"),
        ([(".claude.ai", "sessionKey", -3600)], "no-session"),
        ([(".claude.ai", "sessionKeyLC", 3600)], "no-session"),
        ([(".example.com", "sessionKey", 3600)], "no-session"),
        ([], "no-session"),
    ],
)
def test_the_app_session_cookie_selects_the_signal(monkeypatch, tmp_path, cookies, session):
    monkeypatch.setenv("HOME", str(tmp_path))
    _cookie_store(
        tmp_path, [(host, name, _chromium_time(offset)) for host, name, offset in cookies]
    )
    seen = []
    _record_swift_session(monkeypatch, seen)
    assert _run_program() == 0
    assert seen == [session]


def test_a_missing_or_unreadable_store_falls_back_to_the_sidebar(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = []
    _record_swift_session(monkeypatch, seen)
    assert _run_program() == 0
    store = tmp_path / "Library/Application Support/Claude/Cookies"
    store.parent.mkdir(parents=True)
    store.write_bytes(b"not a database")
    assert _run_program() == 0
    assert seen == ["no-session", "no-session"]


def test_a_session_dropped_while_the_app_ran_is_signed_out(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _cookie_store(tmp_path, [(".claude.ai", "sessionKey", _chromium_time(3600))])
    seen = []
    _record_swift_session(
        monkeypatch, seen, after=lambda: _cookie_store(tmp_path, [])
    )
    assert _run_program() == PROBE_EXIT_CODES["probe_check_unmet"]
    assert seen == ["session"]


def test_the_probe_never_reads_a_cookie_value():
    assert "SELECT expires_utc FROM cookies" in CLAUDE_DESKTOP_PROBE_PROGRAM
    assert "encrypted_value" not in CLAUDE_DESKTOP_PROBE_PROGRAM
    assert "SELECT value" not in CLAUDE_DESKTOP_PROBE_PROGRAM


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


def test_an_app_left_open_points_at_reset_not_reinstall():
    blocked = standard_probe_failure(
        "Claude desktop signed in", PROBE_EXIT_CODES["probe_app_quit_blocked"]
    )
    assert blocked["cause"] == "probe_app_quit_blocked"
    assert "previous session left the app open" in blocked["recovery"]
    assert "`yoke test-machine reset`" in blocked["recovery"]
    assert "needs no reinstall" in blocked["recovery"]
    assert "Repair the executable" not in blocked["recovery"]
    missing = standard_probe_failure(
        "Claude desktop signed in", PROBE_EXIT_CODES["probe_executable_missing"]
    )
    assert missing["cause"] == "probe_executable_missing"
    assert "Install" in missing["recovery"]


def test_the_sealed_program_names_open_and_quit_failures_apart():
    assert "else { return openFailed }" in _SWIFT
    assert "if stillRunning() { exit(quitBlocked) }" in _SWIFT
    assert "exit(11)" not in _SWIFT
