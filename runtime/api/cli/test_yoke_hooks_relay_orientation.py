"""Session orientation composed client-side and merged into hook stdout.

The server skips the orientation policy over https because it cannot see the
client machine, so the client composes orientation itself. These regressions
pin where that text is allowed to land: merged into an allow, preserved
through every transport degradation, and never appended to a deny — a block
message the agent reads must not be buried under startup context.

Shares the wire fixtures of ``test_yoke_operations_cli_hooks.py``.
"""

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
from yoke_harness.hooks.decision_render import (
    HOOK_SPECIFIC_OUTPUT_KEY,
    render_context_stdout,
)
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


ORIENTATION = "## Yoke Orientation\n\nsession s-1\n"


def _server_response(**overrides) -> bytes:
    payload = {
        "hook_schema": 1, "stdout": "", "exit_code": 0,
        "wait_ms": 1, "degraded": [], "outcome": "completed",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


@pytest.fixture()
def oriented(monkeypatch):
    """Make the client-side orientation composer return fixed text."""
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.orientation_for_hook",
        lambda event_name, stdin_data: ORIENTATION,
    )


@pytest.fixture(autouse=True)
def prompt_submit_payload(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s-1"}'))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor", lambda *_a, **_k: None,
    )


def test_blank_context_renders_no_envelope() -> None:
    """An empty orientation must stay empty rather than becoming an envelope
    with nothing in it — the harness would otherwise show the agent a blank
    additional-context block on every prompt."""
    for blank in ("", "   ", "\n\n"):
        assert render_context_stdout(blank, "UserPromptSubmit") == ""


def test_context_renders_the_harness_additional_context_envelope() -> None:
    inner = json.loads(
        render_context_stdout("orientation body", "UserPromptSubmit")
    )[HOOK_SPECIFIC_OUTPUT_KEY]

    assert inner["hookEventName"] == "UserPromptSubmit"
    assert inner["additionalContext"] == "orientation body"


def test_client_orientation_merges_into_the_allow_stdout(
    monkeypatch, capsys, https_connection, local_subset, oriented,
) -> None:
    """Without this the top-level session of a managed project starts with
    nothing while its subagents start fully oriented."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response()),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 0
    envelope = json.loads(out.out)
    assert "## Yoke Orientation" in (
        envelope[HOOK_SPECIFIC_OUTPUT_KEY]["additionalContext"]
    )


def test_client_orientation_survives_an_unreachable_server(
    monkeypatch, capsys, https_connection, local_subset, oriented,
) -> None:
    """Orientation is composed entirely from this machine, so a dead tunnel
    costs the session its server policy verdict but not its bearings."""
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 0
    assert "## Yoke Orientation" in out.out
    assert "degraded to no-op allow" in out.err


def test_client_deny_is_not_diluted_by_orientation(
    monkeypatch, capsys, https_connection, local_subset, oriented,
) -> None:
    """A deny's stdout is the block message the agent reads; appending
    orientation to it would bury the reason the call was refused."""
    local_subset.result = LocalSubsetEvaluation(
        stdout="BLOCKED: destructive git verb", exit_code=2, denied=True,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: pytest.fail("client deny must not POST to the server"),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 2
    assert out.out == "BLOCKED: destructive git verb"


def test_server_deny_is_not_diluted_by_orientation(
    monkeypatch, capsys, https_connection, local_subset, oriented,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response(
            stdout="DENY: server policy", exit_code=2, outcome="denied",
        )),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 2
    assert out.out == "DENY: server policy"
