"""Operator-machine privacy boundary coverage.

The classifier names four categories; live tool calls and automated-test
isolation read that naming differently. A live call defers personal-folder
reads and GUI automation to the harness prompt and the operating system,
advises on broad home discovery, and refuses only the system privacy
database. The test tripwire blocks all four, because no operator stands
behind a unit test.

Every path here is synthetic: the suite must not read the real folders it is
describing, and does not need to in order to prove the classification.
"""

from __future__ import annotations

from pathlib import Path
import shlex

import pytest

from yoke_contracts.hook_runner.local_privacy_guard import (
    classify_shell_command,
    classify_subprocess_args,
)
from yoke_contracts.hook_runner.local_privacy_messages import (
    HOME_DISCOVERY,
    LIVE_ADVISORY,
    LIVE_ALLOWED,
    LIVE_DENY,
    LOCAL_GUI_AUTOMATION,
    PERSONAL_FILE_ACCESS,
    SYSTEM_PRIVACY_DATABASE,
    live_reason,
)


# A home directory that exists nowhere, so no assertion here can be satisfied
# by — or accidentally reach — the machine running the suite.
HOME = Path("/Users/synthetic-operator")
REPO = "/Users/synthetic-operator/checkout"


def _quote(path: str) -> str:
    return shlex.quote(path)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "category"),
    [
        (f"find {_quote(str(HOME))} -maxdepth 6 -name codex", HOME_DISCOVERY),
        ("find $HOME -maxdepth 4 -name python3", HOME_DISCOVERY),
        ("ls $HOME/*", HOME_DISCOVERY),
        ("du -sh ~/Downloads", HOME_DISCOVERY),
        ("rg token $HOME/Library/CloudStorage", HOME_DISCOVERY),
        ("cat ~/Documents/*.txt", HOME_DISCOVERY),
        ("cat ~/Documents/notes.txt", PERSONAL_FILE_ACCESS),
        ("cat ~/Downloads/reference/synthesis.md", PERSONAL_FILE_ACCESS),
        ("head -20 ~/Desktop/operator.txt", PERSONAL_FILE_ACCESS),
        (
            "cat '/Library/Application Support/com.apple.TCC/TCC.db'",
            SYSTEM_PRIVACY_DATABASE,
        ),
        ("osascript -e 'tell app \"Finder\" to activate'", LOCAL_GUI_AUTOMATION),
        ("screencapture /tmp/screen.png", LOCAL_GUI_AUTOMATION),
        ("zsh -lc 'osascript -e beep'", LOCAL_GUI_AUTOMATION),
    ],
)
def test_classifier_names_the_category(command: str, category: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    assert finding.category == category


@pytest.mark.parametrize(
    ("category", "severity"),
    [
        (SYSTEM_PRIVACY_DATABASE, LIVE_DENY),
        (HOME_DISCOVERY, LIVE_ADVISORY),
        (PERSONAL_FILE_ACCESS, LIVE_ALLOWED),
        (LOCAL_GUI_AUTOMATION, LIVE_ALLOWED),
    ],
)
def test_live_severity_per_category(category: str, severity: str) -> None:
    finding = classify_shell_command(
        {
            SYSTEM_PRIVACY_DATABASE: (
                "cat '/Library/Application Support/com.apple.TCC/TCC.db'"
            ),
            HOME_DISCOVERY: "find $HOME -name codex",
            PERSONAL_FILE_ACCESS: "cat ~/Documents/notes.txt",
            LOCAL_GUI_AUTOMATION: "screencapture /tmp/shot.png",
        }[category],
        home=HOME,
        cwd=REPO,
    )

    assert finding is not None
    assert finding.live_severity == severity


@pytest.mark.parametrize(
    "command",
    [
        f"find {_quote(REPO)} -maxdepth 4 -name codex",
        "find ~/.yoke -maxdepth 3 -name config.json",
        "cat ~/.codex/skills/example/SKILL.md",
        "ls ~/.local/bin",
        "cat ~/.cursor/hooks.json",
        "cat ~/.yoke/config*.json",
        "rg -n local_privacy_guard packages runtime",
        "git status --short",
        "ssh test-mac 'osascript -e beep'",
    ],
)
def test_classifier_finds_nothing_outside_the_managed_folders(command: str) -> None:
    assert classify_shell_command(command, home=HOME, cwd=REPO) is None


@pytest.mark.parametrize(
    "command", ["find . -name codex", "rg token", "grep -R token ."]
)
def test_relative_scans_from_home_are_discovery(command: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=str(HOME))

    assert finding is not None
    assert finding.category == HOME_DISCOVERY


def test_relative_scan_from_a_repository_finds_nothing() -> None:
    assert classify_shell_command("find . -name codex", home=HOME, cwd=REPO) is None


def test_subprocess_argv_and_shell_text_share_the_classifier() -> None:
    argv = ["zsh", "-lc", "screencapture /tmp/screen.png"]

    from_argv = classify_subprocess_args(argv, home=HOME, cwd=REPO)
    from_text = classify_subprocess_args(shlex.join(argv), home=HOME, cwd=REPO)

    assert from_argv == from_text
    assert from_argv is not None
    assert from_argv.service == "Screen Recording"


# ---------------------------------------------------------------------------
# The strongest finding in a command is the one reported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/Documents/a.txt '/Library/Application Support/com.apple.TCC/TCC.db'",
        "cat ~/Documents/a.txt ; cat '/Library/Application Support/com.apple.TCC/TCC.db'",
        "find $HOME -name x && cat '/Library/Application Support/com.apple.TCC/TCC.db'",
        "screencapture /tmp/s.png; cat '/Library/Application Support/com.apple.TCC/TCC.db'",
    ],
)
def test_a_weaker_earlier_finding_never_masks_the_privacy_database(
    command: str,
) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    assert finding.category == SYSTEM_PRIVACY_DATABASE


def test_an_allowed_read_does_not_mask_a_later_broad_scan() -> None:
    finding = classify_shell_command(
        "cat ~/Documents/a.txt && find $HOME -name codex", home=HOME, cwd=REPO
    )

    assert finding is not None
    assert finding.category == HOME_DISCOVERY


# ---------------------------------------------------------------------------
# A search tool pointed at one named file is a targeted read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rg pattern ~/Downloads/reference/synthesis.md",
        "grep -r pattern ~/Documents/notes.txt",
        "ls ~/Desktop/operator.txt",
    ],
)
def test_one_named_file_is_targeted_even_for_a_search_tool(command: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    assert finding.category == PERSONAL_FILE_ACCESS


@pytest.mark.parametrize(
    "command",
    [
        "rg token ~/Downloads",
        "rg token $HOME/Library/CloudStorage",
        "find ~/Documents -name '*.md'",
    ],
)
def test_a_tree_operand_stays_discovery(command: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    assert finding.category == HOME_DISCOVERY


# ---------------------------------------------------------------------------
# Message accuracy
# ---------------------------------------------------------------------------


def test_advisory_names_yoke_as_not_refusing_and_teaches_anchoring() -> None:
    finding = classify_shell_command("find $HOME -name codex", home=HOME, cwd=REPO)

    assert finding is not None
    reason = finding.reason()
    assert "not refusing" in reason
    assert "resolve_native_cli" in reason
    assert "harness permission prompt" in reason


def test_deny_names_yoke_as_the_refusing_authority() -> None:
    finding = classify_shell_command(
        "cat '/Library/Application Support/com.apple.TCC/TCC.db'",
        home=HOME,
        cwd=REPO,
    )

    assert finding is not None
    reason = finding.reason()
    assert "Yoke refuses this itself" in reason
    assert "System Settings" in reason


@pytest.mark.parametrize(
    "command",
    ["cat ~/Documents/notes.txt", "osascript -e beep"],
)
def test_allowed_categories_defer_to_harness_and_os_authority(command: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    text = finding.test_isolation_reason()
    assert "Yoke does not decide" in text
    assert "harness permission prompt" in text


@pytest.mark.parametrize("category", [PERSONAL_FILE_ACCESS, LOCAL_GUI_AUTOMATION])
def test_a_live_allowed_category_has_no_live_message(category: str) -> None:
    with pytest.raises(ValueError, match="live tool calls"):
        live_reason(category, "target", "service")


@pytest.mark.parametrize(
    "command",
    ["cat ~/Documents/notes.txt", "find $HOME -name codex", "osascript -e beep"],
)
def test_messages_avoid_tmp_and_unrelated_permission_advice(command: str) -> None:
    finding = classify_shell_command(command, home=HOME, cwd=REPO)

    assert finding is not None
    text = finding.test_isolation_reason()
    assert "/tmp" not in text
    assert "Full Disk Access" not in text
