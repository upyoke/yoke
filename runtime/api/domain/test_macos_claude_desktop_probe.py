"""Authentication markers recognized by the sealed macOS Claude Desktop probe."""

from __future__ import annotations

import subprocess

import pytest

from yoke_harness.macos_claude_desktop_probe import _AUTHENTICATION_SWIFT


@pytest.mark.macos_only(reason="runs the probe's Swift classifier with the macOS SDK")
def test_authenticated_chat_and_code_markers(tmp_path):
    script = tmp_path / "authentication.swift"
    script.write_text(
        "import Foundation\n"
        + _AUTHENTICATION_SWIFT
        + """
let chat: Set<String> = ["+ new", "projects", "artifacts"]
let code: Set<String> = ["+ new", "search", "artifacts", "customize"]
let login: Set<String> = ["sign in", "continue with google"]
precondition(isSignedInChat(chat))
precondition(isSignedInChat(["new chat", "chats", "projects"]))
precondition(!isSignedInChat(code))
precondition(isCodeSidebar(code))
precondition(!isCodeSidebar(login))
precondition(hasAccountFooter(["Example User • Ultra v"]))
precondition(hasAccountFooter(["Example User · Pro"]))
precondition(!hasAccountFooter(["ultra"]))
precondition(!hasAccountFooter(["upgrade to pro"]))
precondition(!hasAccountFooter(login))
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["/usr/bin/swift", str(script)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
