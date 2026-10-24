"""The import lint exempts ``yoke dev run --`` whatever flags surround it.

Its own refusal recommends ``yoke dev run -- python3 -c '<body>'``, so the
exemption has to hold with global flags before ``dev run``
(``yoke --env prod-db-admin dev run --``) and run flags after it
(``yoke dev run --lane /x --``), while a ``yoke`` call in an earlier shell
command still exempts nothing.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import lint_no_agent_runtime_api_import_from_c as lint

BODY = '"import yoke_core, yoke_contracts"'


def _eval(command: str):
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    return lint.evaluate_payload(payload)


@pytest.mark.parametrize(
    "wrapper",
    ["yoke --env prod-db-admin dev run -- ", "yoke dev run --lane /x -- "],
)
def test_global_and_run_flags_keep_the_wrapper(wrapper):
    assert _eval(f"python3 -c {BODY}") is not None
    assert _eval(f"{wrapper}python3 -c {BODY}") is None


@pytest.mark.parametrize(
    "command",
    [
        'yoke --env x items get 1; python3 -c "import yoke_core"',
        'yoke dev run -- true; echo -- python3 -c "import yoke_core"',
    ],
)
def test_a_yoke_call_in_an_earlier_command_does_not_exempt(command):
    assert _eval(command) is not None
