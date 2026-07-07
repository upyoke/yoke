"""Codex Bash failure truth — TestCodexBashFailureTruth.

Drives representative Codex hook payloads through the real
``parse_hook_event -> detect_anomalies -> build_envelope`` pipeline that
``observe.main()`` uses at runtime.
"""

from __future__ import annotations

from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    parse_hook_event,
)


class TestCodexBashFailureTruth:
    """Prove Codex Bash failure telemetry classification end to end.

    These tests drive representative Codex hook payloads through the real
    ``parse_hook_event -> detect_anomalies -> build_envelope`` pipeline that
    ``observe.main()`` uses at runtime. The goal is to prove that:

    * A ``PostToolUseFailure`` Codex Bash payload reaches ``HarnessToolCallFailed``
      with nonzero exit semantics.
    * A normal successful Bash ``PostToolUse`` payload still reaches
      ``HarnessToolCallCompleted`` with ``exit_code=0``.
    * An ambiguous Bash ``PostToolUse`` payload with hard-failure text but
      no top-level ``error`` and no ``Exit code N`` string does NOT get
      recorded as ``HarnessToolCallCompleted`` with ``exit_code=0``.
    * The fallback guard preserves existing structured-exit and
      benign-failure behavior.
    """

    # Representative payloads mirror the real Codex hook JSON shape. The
    # Codex runtime posts the Bash command under ``tool_input`` and the
    # response under ``tool_response.content``. ``PostToolUseFailure`` adds
    # a top-level ``error`` field; ``PostToolUse`` typically does not.

    BASH_SUCCESS_PAYLOAD = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
        "tool_response": {"content": "hello\n"},
        "tool_use_id": "tu-ok-1",
        "session_id": "codex-session",
    }

    BASH_EXPLICIT_FAILURE_PAYLOAD = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat /no/such/path"},
        "tool_response": {"content": "cat: /no/such/path: No such file or directory"},
        "error": "Exit code 1",
        "tool_use_id": "tu-fail-1",
        "session_id": "codex-session",
    }

    BASH_AMBIGUOUS_NO_SUCH_FILE_PAYLOAD = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat /tmp/yok1272/does-not-exist.log"},
        "tool_response": {
            "content": "cat: /tmp/yok1272/does-not-exist.log: No such file or directory"
        },
        "tool_use_id": "tu-ambig-1",
        "session_id": "codex-session",
    }

    BASH_AMBIGUOUS_COMMAND_NOT_FOUND_PAYLOAD = {
        "tool_name": "Bash",
        "tool_input": {"command": "definitely_not_a_real_binary --help"},
        "tool_response": {
            "content": "zsh: command not found: definitely_not_a_real_binary"
        },
        "tool_use_id": "tu-ambig-2",
        "session_id": "codex-session",
    }

    BASH_AMBIGUOUS_PERMISSION_DENIED_PAYLOAD = {
        "tool_name": "Bash",
        "tool_input": {"command": "touch /root/denied"},
        "tool_response": {"content": "touch: /root/denied: Permission denied"},
        "tool_use_id": "tu-ambig-3",
        "session_id": "codex-session",
    }

    # --- AC-2: PostToolUseFailure Codex Bash -> HarnessToolCallFailed --------------

    def test_post_tool_use_failure_produces_tool_call_failed(self):
        rec = parse_hook_event(
            self.BASH_EXPLICIT_FAILURE_PAYLOAD,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.is_failure is True
        assert rec.exit_code == 1
        detect_anomalies(rec)
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"
        assert env["exit_code"] == 1

    # --- AC-3: successful Bash PostToolUse stays HarnessToolCallCompleted ---------

    def test_post_tool_use_success_still_produces_tool_call_completed(self):
        rec = parse_hook_event(
            self.BASH_SUCCESS_PAYLOAD,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0
        detect_anomalies(rec)
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"
        assert env["event_outcome"] == "completed"
        assert env["exit_code"] == 0

    # --- AC-4: ambiguous hard-failure text -> NOT clean success ------------

    def test_ambiguous_no_such_file_reclassified_as_failure(self):
        rec = parse_hook_event(
            self.BASH_AMBIGUOUS_NO_SUCH_FILE_PAYLOAD,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.is_failure is True, (
            "Ambiguous 'No such file or directory' payload must not be "
            "silently recorded as a clean success"
        )
        assert rec.exit_code == 1, (
            "Ambiguous hard-failure payloads must use sentinel exit_code=1"
        )
        detect_anomalies(rec)
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"
        assert env["exit_code"] == 1

    def test_ambiguous_command_not_found_reclassified_as_failure(self):
        rec = parse_hook_event(
            self.BASH_AMBIGUOUS_COMMAND_NOT_FOUND_PAYLOAD,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.is_failure is True
        assert rec.exit_code == 1
        detect_anomalies(rec)
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"

    def test_ambiguous_permission_denied_reclassified_as_failure(self):
        rec = parse_hook_event(
            self.BASH_AMBIGUOUS_PERMISSION_DENIED_PAYLOAD,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.is_failure is True
        assert rec.exit_code == 1
        detect_anomalies(rec)
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"

    def test_ambiguous_fallback_only_applies_to_post_tool_use(self):
        """The fallback is scoped to ``hook_event == 'PostToolUse'``.

        Other hook events (PreToolUse, PostToolUseFailure) must not pick
        up the fallback path — PostToolUseFailure already has its own
        failure channel via the top-level ``error`` field.
        """
        # PostToolUseFailure without a top-level error is a malformed edge
        # case — the fallback should still NOT apply because the hook event
        # semantics already indicate failure should come from the error
        # field, not text pattern matching.
        payload = dict(self.BASH_AMBIGUOUS_NO_SUCH_FILE_PAYLOAD)
        rec = parse_hook_event(payload, hook_event="PostToolUseFailure")
        # No error field, no "Exit code N", hook event is not PostToolUse
        # → fallback skipped, exit_code defaults to 0, not reclassified.
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0

    # --- AC-5: preserve structured-exit and benign-failure behavior --------

    def test_approval_gate_structured_exit_not_reclassified(self):
        """An approval-gate payload is routed through PostToolUseFailure
        with a top-level error like 'Awaiting human approval'. The fallback
        must not fire (because ``is_failure`` is already True and the
        structured_exit anomaly handles reclassification downstream).
        """
        approval_payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "some-gated-command"},
            "tool_response": {"content": ""},
            "error": "Awaiting human approval",
            "tool_use_id": "tu-approval",
        }
        rec = parse_hook_event(approval_payload, hook_event="PostToolUseFailure")
        assert rec is not None
        assert rec.is_failure is True
        detect_anomalies(rec)
        env = build_envelope(rec)
        # structured_exit anomaly must reclassify to HarnessToolCallStructuredExit
        assert env["event_name"] == "HarnessToolCallStructuredExit"
        assert env["event_outcome"] == "structured_exit"

    def test_benign_edit_failure_not_affected_by_fallback(self):
        """The benign-failure anomaly applies to Edit-tool ``String to
        replace not found`` events delivered via PostToolUseFailure. The
        Bash-scoped fallback must not interfere with this path.
        """
        benign_payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/tmp/foo.py",
                "old_string": "a",
                "new_string": "b",
            },
            "tool_response": {},
            "error": "String to replace not found in file",
            "tool_use_id": "tu-benign",
        }
        rec = parse_hook_event(benign_payload, hook_event="PostToolUseFailure")
        assert rec is not None
        assert rec.is_failure is True
        detect_anomalies(rec)
        assert "benign_failure" in rec.anomalies
        env = build_envelope(rec)
        # benign_failure downgrades severity but keeps HarnessToolCallFailed
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["severity"] == "INFO"

    def test_bash_success_with_exit_code_zero_text_not_reclassified(self):
        """A Bash command whose output legitimately contains an ``Exit
        code 0`` string (e.g. a test runner summary) must still be
        recorded as HarnessToolCallCompleted.
        """
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "tool_response": {"content": "All tests pass. Exit code 0"},
            "tool_use_id": "tu-exit-0",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"

    def test_bash_nonzero_exit_code_from_response_text(self):
        """A Bash payload whose response includes ``Exit code 2`` parses
        the real exit code AND flips ``is_failure`` to ``True``.

        Full audit-truth regression coverage for nonzero parsed exits
        (event_outcome, event_name, anomaly-flag independence) lives in
        ``test_observe_nonzero_exit_outcome.py``; this test guards the
        parser-level contract only.
        """
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep missing /tmp/file"},
            "tool_response": {"content": "grep: No such file or directory\nExit code 2"},
            "tool_use_id": "tu-exit-2",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.exit_code == 2
        assert rec.is_failure is True

    def test_successful_grep_output_with_failure_phrase_not_reclassified(self):
        """Successful content search output must not trip the fallback.

        A truthful success can legitimately print phrases like
        ``command not found`` when grep finds those words in docs or code.
        The fallback should only match stderr-shaped lines for the executed
        command, not arbitrary successful output text.
        """
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "rg -n \"command not found\" yoke/docs"},
            "tool_response": {
                "content": "runtime/docs/hooks.md:350:command not found"
            },
            "tool_use_id": "tu-grep-ok",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"

    def test_successful_echo_of_failure_text_not_reclassified(self):
        """Literal echoed text must not be treated as stderr from another command."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'cat: /tmp/missing: No such file or directory'"},
            "tool_response": {
                "content": "cat: /tmp/missing: No such file or directory"
            },
            "tool_use_id": "tu-echo-ok",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"
