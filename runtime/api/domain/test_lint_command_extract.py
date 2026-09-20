"""Shared PreToolUse command extractor — one reader, bound-variable expansion."""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain import lint_command_extract as extract
from yoke_core import domain as domain_pkg


def test_extracts_tool_input_command() -> None:
    assert (
        extract.extract_command({"tool_input": {"command": "git status"}})
        == "git status"
    )


def test_extracts_cmd_and_top_level_keys() -> None:
    assert extract.extract_command({"toolInput": {"cmd": "ls"}}) == "ls"
    assert extract.extract_command({"command": "pwd"}) == "pwd"


def test_simple_assignment_is_substituted() -> None:
    command = extract.extract_command(
        {"tool_input": {"command": "p=head; yoke relay status | $p -4"}}
    )
    assert "$p" not in command
    assert "| head -4" in command


def test_unbound_substitution_stays_visible() -> None:
    command = extract.extract_command(
        {"tool_input": {"command": "yoke relay status | $p -4"}}
    )
    assert "$p" in command


def test_unresolved_command_token_detects_dollar_argv0() -> None:
    assert extract.is_unresolved_command_token("$p")
    assert extract.is_unresolved_command_token("${cmd}")
    assert not extract.is_unresolved_command_token("head")


def test_lint_modules_do_not_define_private_command_extractors() -> None:
    root = Path(domain_pkg.__file__).resolve().parent
    offenders: list[str] = []
    defined = re.compile(
        r"^def (_extract_command|_extract_bash_command|extract_command)\(",
        re.M,
    )
    walk = re.compile(r'tool_input\.get\("command"\)')
    for path in sorted(root.glob("lint_*.py")):
        if path.name == "lint_command_extract.py" or "test_helpers" in path.name:
            continue
        text = path.read_text()
        if defined.search(text) or walk.search(text):
            offenders.append(path.name)
    assert offenders == []
