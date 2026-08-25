"""Only a printed orientation block retires a session's orientation.

Composing the block and delivering it were one fact, so a process that lost
it afterwards lost it permanently — the shape a live Cursor session hit
during a relay-turbulence window. These regressions pin the split: an
evaluation that printed the block confirms its own delivery, a degradation
that preserved it counts, and a deny that replaced it does not — including
the Cursor and Codex denies that carry an allow's exit code, where the exit
status cannot settle the question at all.

Shares the wire fixtures of ``test_yoke_operations_cli_hooks.py``.
"""

# Imported pytest fixtures are intentionally requested by their registered
# names in the tests below.
# ruff: noqa: F811

from __future__ import annotations

import io
import json
import sys

import pytest

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    cli_main,
    https_connection,
    local_subset,
)
from runtime.api.cli.test_yoke_hooks_relay_orientation import (  # noqa: F401
    ORIENTATION,
    _server_response,
    oriented,
)
from yoke_contracts.hook_runner.config_owner import (
    CURSOR_EXECUTOR_ID,
    EXECUTOR_ENV_VAR,
)
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


@pytest.fixture(autouse=True)
def prompt_submit_payload(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s-1"}'))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )


@pytest.fixture()
def delivery_confirmations(monkeypatch):
    """Record every delivery the adapter confirms for the composed block."""
    confirmed: list[bool] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.confirm_orientation_delivery",
        lambda: confirmed.append(True),
    )
    return confirmed


def test_a_printed_block_confirms_its_own_delivery(
    monkeypatch,
    capsys,
    https_connection,
    local_subset,
    oriented,
    delivery_confirmations,
) -> None:
    """Composition is not delivery: only a process that survived to print
    the block may retire the session's orientation, or a hook the harness
    kills mid-flight leaves the session un-oriented forever."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response()),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    capsys.readouterr()
    assert rc == 0
    assert delivery_confirmations == [True]


def test_a_degraded_relay_still_confirms_the_preserved_block(
    monkeypatch,
    capsys,
    https_connection,
    local_subset,
    oriented,
    delivery_confirmations,
) -> None:
    """The degradation preserves the client's allow stdout, so the block did
    reach the agent — re-delivering it later would be a duplicate."""
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 0
    assert "## Yoke Orientation" in out.out
    assert delivery_confirmations == [True]


def test_a_deny_leaves_the_dropped_block_unconfirmed(
    monkeypatch,
    capsys,
    https_connection,
    local_subset,
    oriented,
    delivery_confirmations,
) -> None:
    """A deny prints its block message instead of the merged allow stdout.
    The orientation went nowhere, so the session must still count as
    un-oriented and get it on the next context-bearing event. Cursor and
    Codex denies carry an allow's exit code, so only the printed text can
    settle this."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(
            _server_response(
                stdout="DENY: server policy",
                exit_code=2,
                outcome="denied",
            )
        ),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    capsys.readouterr()
    assert rc == 2
    assert delivery_confirmations == []


def test_a_cursor_deny_does_not_retire_the_orientation_it_dropped(
    monkeypatch,
    capsys,
    https_connection,
    local_subset,
    oriented,
    delivery_confirmations,
) -> None:
    """Cursor reads its deny verdict from JSON on exit 0. Treating that exit
    code as delivery is what left the reported session un-oriented for its
    whole life."""
    monkeypatch.setenv(EXECUTOR_ENV_VAR, CURSOR_EXECUTOR_ID)
    local_subset.result = LocalSubsetEvaluation(
        stdout=json.dumps({"permission": "deny", "agent_message": "no"}),
        exit_code=0,
        denied=True,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: pytest.fail("client deny must not POST to the server"),
    )

    rc = cli_main(["hook", "evaluate", "SessionStart"])

    out = capsys.readouterr()
    assert rc == 0
    assert ORIENTATION not in out.out
    assert delivery_confirmations == []
