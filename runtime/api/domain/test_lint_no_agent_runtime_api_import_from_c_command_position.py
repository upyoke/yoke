"""Only an interpreter in command position is a ``python -c`` invocation.

A heredoc that feeds a typed ``yoke`` command on stdin is data, even when
its prose quotes an import one-liner, and a quoted operand that mentions
``python3 -c`` names no interpreter. A real reach-in in command position —
alone or behind a launcher such as ``env``, ``uv run`` or ``timeout`` — is
still refused.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import lint_no_agent_runtime_api_import_from_c as lint

REACH_IN = 'python3 -c "from yoke_core.domain.events import emit"'


def _eval(command: str):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return lint.evaluate_payload(payload)


def test_heredoc_prose_fed_to_a_yoke_command_is_data() -> None:
    command = (
        "yoke items structured-field append-addendum YOK-4412 "
        "--field spec --stdin <<'EOF'\n"
        "Agents reached for\n"
        f"    {REACH_IN}\n"
        "instead of the registered adapter.\n"
        "EOF"
    )
    assert _eval(command) is None


def test_quoted_search_operand_names_no_interpreter() -> None:
    assert _eval(f"rg -n '{REACH_IN}' docs/") is None


def test_echoed_one_liner_names_no_interpreter() -> None:
    assert _eval(f"echo '{REACH_IN}'") is None


@pytest.mark.parametrize(
    "command",
    [
        REACH_IN,
        f"echo start; {REACH_IN}",
        f"cat <<'EOF' > /tmp/x\nnote\nEOF\n{REACH_IN}",
        f"env YOKE_ENV=prod {REACH_IN}",
        f"YOKE_ENV=prod {REACH_IN}",
        f"uv run {REACH_IN}",
        f"uv run -- {REACH_IN}",
        f"timeout 10 {REACH_IN}",
    ],
)
def test_command_position_reach_in_is_still_refused(command: str) -> None:
    verdict = _eval(command)
    assert verdict is not None
    assert "from yoke_core.domain.events import emit" in verdict[0]
