"""Verdict composition across the hook-relay split.

The relay client evaluates the LOCAL_STATE_POLICIES subset itself and
composes with the server verdict: any deny wins regardless of side, two
allows merge stdouts, and transport degradation never discards the client
half. Shares the wire fixtures of ``test_yoke_operations_cli_hooks.py``
(the ``local_subset`` holder is autouse there and here via import).
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
from yoke_harness.hooks.decision_render import HOOK_SPECIFIC_OUTPUT_KEY
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


def _context_envelope(body: str, event_name: str = "PreToolUse") -> str:
    return json.dumps({
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": event_name,
            "additionalContext": body,
        }
    })


def _server_response(**overrides) -> bytes:
    payload = {
        "hook_schema": 1, "stdout": "", "exit_code": 0,
        "wait_ms": 1, "degraded": [], "outcome": "completed",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_client_local_deny_short_circuits_without_post(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    """A client-side local-state deny wins outright and skips the POST —
    the server verdict could not flip it."""
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO('{"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor", lambda: "claude",
    )
    local_subset.result = LocalSubsetEvaluation(
        stdout="BLOCKED: destructive git verb", exit_code=2, denied=True,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: pytest.fail("client deny must not POST to the server"),
    )

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    out = capsys.readouterr()
    assert rc == 2
    assert out.out == "BLOCKED: destructive git verb"
    assert local_subset.calls == [("PreToolUse", "claude", None, True, {})]


def test_both_allow_advisory_envelopes_merge_into_one(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"tool_name": "Edit"}'))
    local_subset.result = LocalSubsetEvaluation(
        stdout=_context_envelope("client hint"), exit_code=0, denied=False,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(
            _server_response(stdout=_context_envelope("server hint")),
        ),
    )

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    out = capsys.readouterr()
    assert rc == 0
    envelope = json.loads(out.out)
    assert envelope[HOOK_SPECIFIC_OUTPUT_KEY]["additionalContext"] == (
        "client hint\n\nserver hint"
    )


def test_client_payload_extra_posts_to_server(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"tool_name": "Bash"}'))
    local_subset.result = LocalSubsetEvaluation(
        stdout="", exit_code=0, denied=False, payload_extra={"client_fact": 7},
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(_server_response())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert captured["body"]["payload_extra"] == {"client_fact": 7}


def test_client_plain_stdout_relays_through_empty_server_allow(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    """Lifecycle shape: the orientation block is client-rendered plain text
    and the server's lifecycle chain is empty — the client half must reach
    the harness unchanged."""
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s-orient"}'))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )
    local_subset.result = LocalSubsetEvaluation(
        stdout="## Yoke Orientation\n", exit_code=0, denied=False,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response()),
    )

    rc = cli_main(["hook", "evaluate", "UserPromptSubmit"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "## Yoke Orientation\n"


def test_server_deny_relays_verbatim_and_drops_client_advisory(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    """Mirror of the in-chain renderer rule: deny text is never diluted by
    sibling advisories — the server deny renders alone."""
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"tool_name": "Bash"}'))
    local_subset.result = LocalSubsetEvaluation(
        stdout=_context_envelope("client hint"), exit_code=0, denied=False,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(_server_response(
            stdout="DENY: server policy", exit_code=2, outcome="denied",
        )),
    )

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    out = capsys.readouterr()
    assert rc == 2
    assert out.out == "DENY: server policy"


def test_missing_outcome_is_non_contract_and_preserves_client_stdout(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    """The structured ``outcome`` is required: a response without it is
    not the contract, degrades the server half, and keeps the client half."""
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"tool_name": "Bash"}'))
    local_subset.result = LocalSubsetEvaluation(
        stdout="client advisory\n", exit_code=0, denied=False,
    )
    legacy = {"hook_schema": 1, "stdout": "", "exit_code": 0,
              "wait_ms": 1, "degraded": []}
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(json.dumps(legacy).encode("utf-8")),
    )

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "client advisory\n"
    assert "not the hook contract" in out.err


def test_unreachable_server_degrades_but_preserves_client_stdout(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    import urllib.error

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    local_subset.result = LocalSubsetEvaluation(
        stdout="client advisory\n", exit_code=0, denied=False,
    )

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "client advisory\n"
    assert "degraded to no-op allow" in out.err
    assert "PreToolUse" in out.err


def test_non_200_degrades_to_noop_with_empty_client_half(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    import urllib.error

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "boom", hdrs=None, fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "PostToolUse"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "HTTP 500" in out.err
