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

from runtime.api.cli.yoke_operations_cli_hooks_test_support import (https_connection as https_connection, local_subset as local_subset)
from runtime.api.cli.yoke_hooks_relay_orientation_test_support import (oriented as oriented)

import hashlib
import io
import json
import sys

import pytest

from runtime.api.cli.yoke_operations_cli_hooks_test_support import (
    _FakeResponse,
    cli_main,
)
from runtime.api.cli.yoke_hooks_relay_orientation_test_support import (
    ORIENTATION,
    _server_response,
)
from yoke_contracts.hook_runner.config_owner import (
    CURSOR_EXECUTOR_ID,
    EXECUTOR_ENV_VAR,
)
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


@pytest.fixture(autouse=True)
def prompt_submit_payload(monkeypatch):
    monkeypatch.setenv(EXECUTOR_ENV_VAR, "claude-code")
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s-1"}'))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )


@pytest.fixture()
def delivery_confirmations(monkeypatch):
    """Record every delivery the adapter confirms for the composed block."""
    confirmed: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.confirm_orientation_delivery",
        lambda body: confirmed.append(body),
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
    assert len(delivery_confirmations) == 1
    assert ORIENTATION in delivery_confirmations[0]


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
    assert len(delivery_confirmations) == 1
    assert ORIENTATION in delivery_confirmations[0]


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


@pytest.mark.parametrize("executor", ["claude-code", "codex", CURSOR_EXECUTOR_ID])
def test_delivered_marker_fingerprints_exact_emitted_body(
    executor,
    monkeypatch,
    tmp_path,
    capsys,
    https_connection,
    local_subset,
):
    from yoke_core.domain import session_orientation_delivery as delivery

    monkeypatch.setenv(EXECUTOR_ENV_VAR, executor)
    monkeypatch.setenv(
        "CURSOR_INVOKED_AS", "cursor-agent" if executor == CURSOR_EXECUTOR_ID else ""
    )
    delivery._composed_session.set(None)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(delivery, "_attempt_marker", lambda _: tmp_path / "attempt")
    monkeypatch.setattr(delivery, "_delivered_marker", lambda _: tmp_path / "delivered")
    orientation = ORIENTATION + "UTF-8: café ☃\n"

    def compose(*_args, **_kwargs):
        delivery.claim_orientation_attempt("s-1")
        return orientation

    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.orientation_for_hook", compose
    )
    cursor = executor == CURSOR_EXECUTOR_ID
    transcript = tmp_path / "s-1.jsonl"
    transcript.touch()
    payload = {
        "transcript_path": str(transcript),
        "session_id": "s-1",
        "conversation_id": "s-1",
        "workspace_roots": ["/repo"],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    resume = "merged resume body\n"
    server_context = (
        {"additional_context": resume}
        if cursor
        else {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": resume,
            }
        }
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(
            _server_response(stdout=json.dumps(server_context))
        ),
    )

    assert (
        cli_main(["hook", "evaluate", "SessionStart" if cursor else "UserPromptSubmit"])
        == 0
    )

    emitted = json.loads(capsys.readouterr().out)
    body = (
        emitted["additional_context"]
        if cursor
        else emitted["hookSpecificOutput"]["additionalContext"]
    )
    assert orientation in body and resume in body
    encoded = body.encode("utf-8")
    assert len(encoded) > len(body)
    assert json.loads((tmp_path / "delivered").read_text()) == {
        "byte_count": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


# (event, payload extra, oriented?) for one session's life on each harness:
# orient once, stay silent on the next context event, and orient again after
# the harness's own compaction signal.
_LIFECYCLES = {
    "claude-code": [
        ("UserPromptSubmit", {}, True),
        ("UserPromptSubmit", {}, False),
        ("SessionStart", {"source": "compact"}, False),
        ("UserPromptSubmit", {}, True),
        ("UserPromptSubmit", {}, False),
    ],
    "codex": [
        ("SessionStart", {"source": "startup"}, True),
        ("UserPromptSubmit", {}, False),
        ("SessionStart", {"source": "compact"}, True),
        ("UserPromptSubmit", {}, False),
    ],
    CURSOR_EXECUTOR_ID: [
        ("SessionStart", {}, True),
        ("PostToolUse", {}, False),
        ("PreCompact", {"trigger": "auto"}, False),
        ("PostToolUse", {}, True),
        ("PostToolUse", {}, False),
    ],
}


@pytest.mark.usefixtures("bound_project_context")
@pytest.mark.parametrize("executor", sorted(_LIFECYCLES))
def test_orientation_lands_once_and_returns_after_compaction(
    executor, monkeypatch, tmp_path, capsys, https_connection, local_subset
):
    from yoke_core.domain import session_orientation_delivery as delivery
    from yoke_core.domain.project_scratch_roots import ENV_KEY

    monkeypatch.setenv(ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(EXECUTOR_ENV_VAR, executor)
    cursor = executor == CURSOR_EXECUTOR_ID
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent" if cursor else "")
    delivery._composed_session.set(None)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_a, **_k: _FakeResponse(_server_response())
    )
    project = tmp_path / "project"
    (project / ".yoke").mkdir(parents=True)
    transcript = tmp_path / "s-life.jsonl"
    transcript.touch()
    base = {
        "session_id": "s-life",
        "conversation_id": "s-life",
        "cwd": str(project),
        "workspace_roots": [str(project)],
        "transcript_path": str(transcript),
    }
    seen = []
    for event, extra, _oriented in _LIFECYCLES[executor]:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**base, **extra})))
        assert cli_main(["hook", "evaluate", event]) == 0
        out = capsys.readouterr().out
        seen.append((event, "## Yoke Orientation" in out, "NOTE:" in out))

    assert seen == [
        (event, oriented, False) for event, _extra, oriented in _LIFECYCLES[executor]
    ]
