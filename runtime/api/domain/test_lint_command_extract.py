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


def test_engine_and_harness_share_the_contracts_command_reader() -> None:
    from yoke_contracts.hook_runner.command_extract import (
        extract_command as contracts_extract,
    )
    from yoke_harness.hooks.local_policy_common import (
        command_from_payload,
        git_invocations,
    )

    assert extract.extract_command is contracts_extract
    payload = {"tool_input": {"command": "p=git; $p reset --hard"}}
    assert "git reset --hard" in command_from_payload(payload)
    args, _repo = git_invocations("do git stash drop")[0]
    assert args[:2] == ["stash", "drop"]


def test_polling_extract_still_exports_tool_input_for_waiter() -> None:
    from yoke_core.domain.lint_long_command_polling_extract import (
        _extract_tool_input,
    )
    from yoke_core.domain.lint_long_command_polling_waiter import (
        evaluate_bg_waiter,
    )

    payload = {"toolInput": {"run_in_background": True}}
    assert _extract_tool_input(payload)["run_in_background"] is True
    assert callable(evaluate_bg_waiter)


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
