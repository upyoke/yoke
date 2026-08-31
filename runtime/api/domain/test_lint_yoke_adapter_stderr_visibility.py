"""Regression corpus for visible stderr on mutating Yoke adapters."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import lint_yoke_adapter_stderr_visibility as lint
from yoke_core.hooks.types import Next, Outcome


def _payload(command: str, **extra: object) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


@pytest.mark.parametrize(
    "command, detected",
    [
        (
            "yoke items create --title example --json 2>&1 | "
            "python3 -c 'import json,sys; json.load(sys.stdin)'",
            "merged stderr",
        ),
        (
            "printf %s done | yoke say --stdin --item YOK-1 "
            "2>/dev/null | tail -1",
            "suppressed stderr",
        ),
    ],
)
def test_incident_commands_are_denied(command: str, detected: str):
    result = _eval(command)

    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert detected in reason
    assert outcome == "denied"


@pytest.mark.parametrize(
    "command",
    [
        "yoke dash 'title' 'instruction' 2>/dev/null",
        "yoke items cancel YOK-1 2>&-",
        "yoke items structured-field replace YOK-1 --stdin 2>/dev/null",
        "yoke items section upsert YOK-1 --stdin 2>/dev/null",
        "yoke claims work acquire --item YOK-1 2>&-",
        "yoke claims work release --item YOK-1 2>/dev/null",
        "yoke lifecycle transition YOK-1 --from idea --to implementing 2>&-",
        "yoke session-control launch create --item YOK-1 2>/dev/null",
        "yoke session-control launch retry launch-1 2>&-",
        "yoke session-control launch reconcile launch-1 2>/dev/null",
        "yoke messages acknowledge message-1 2>&-",
        "yoke deployment-runs create flow-1 2>/dev/null",
    ],
)
def test_named_mutating_adapter_families_are_denied(command: str):
    result = _eval(command)

    assert result is not None
    assert result[0] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "yoke db read 'SELECT 1' 2>/dev/null | tail -1",
        "yoke items get YOK-1 --json 2>&1 | python3 -c 'print(1)'",
        "yoke session-control launch preview --json 2>&1 | head -1",
        "yoke session-control launch list --json 2>/dev/null | tail -1",
        "yoke messages list --json 2>&1 | python3 -c 'print(1)'",
        "yoke sessions list --json 2>/dev/null | tail -1",
        "yoke claims path list --json 2>&1 | head -1",
        "yoke items create --title example --json | python3 -c 'print(1)'",
        "yoke say --stdin --session sess-test | tail -1",
        "command -v yoke 2>/dev/null",
        "ssh host true 2>/dev/null",
        "yoke watch pytest -- runtime/api/domain/test_example.py",
        "pytest runtime/api/domain/test_example.py -k 'yoke say 2>/dev/null'",
        "git grep -n 'yoke say --stdin 2>/dev/null' -- tests",
        "yoke say --help 2>/dev/null | tail -1",
        "yoke claims work acquire --item YOK-1 2>&1",
    ],
)
def test_legitimate_session_corpus_is_allowed(command: str):
    assert _eval(command) is None


def test_global_env_selector_still_classifies_mutation():
    result = _eval(
        "YOKE_TRACE=1 yoke --env prod-db-admin deployment-runs create flow-1 "
        "2>/dev/null"
    )

    assert result is not None
    assert "yoke deployment-runs create" in result[1]


def test_quoted_redirection_text_is_not_shell_redirection():
    assert _eval(
        "yoke items create --title 'example 2>/dev/null' --json | tail -1"
    ) is None


def test_non_bash_tool_is_allowed():
    payload = _payload("yoke say --stdin 2>/dev/null", tool_name="Read")
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert lint.evaluate_payload(payload) is None


def test_suppression_token_is_audit_only():
    command = (
        "yoke say --stdin 2>/dev/null "
        "# lint:no-yoke-adapter-stderr-visibility-check"
    )
    with mock.patch.object(lint, "_read_mode", return_value="deny"), \
         mock.patch.object(lint, "_emit_audit_event") as emit_mock:
        decision = lint.evaluate(lint._build_context_from_payload(_payload(command)))

    assert decision.outcome is Outcome.DENY
    assert decision.next is Next.STOP
    body = json.loads(decision.message)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "does NOT unblock" in body["hookSpecificOutput"][
        "permissionDecisionReason"
    ]
    assert emit_mock.call_args.args[3] == "suppression_attempted"


def test_warn_mode_reports_without_blocking():
    with mock.patch.object(lint, "_read_mode", return_value="warn"), \
         mock.patch.object(lint, "_emit_audit_event"):
        decision = lint.evaluate(
            lint._build_context_from_payload(
                _payload("yoke claims work acquire --item YOK-1 2>&-")
            )
        )

    assert decision.outcome is Outcome.WARN
    assert not decision.block
    assert "mode=warn" in decision.audit_fields["reason"]


def test_denial_teaches_bare_and_visible_stderr_shapes():
    result = _eval("yoke messages acknowledge message-1 2>/dev/null")

    assert result is not None
    reason = result[1]
    assert "Run the adapter bare" in reason
    assert "leave stderr attached to the terminal" in reason
    assert "--json | python3 -c" in reason
