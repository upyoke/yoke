"""Codex transcript reconciliation — TestCodexTranscriptReconciliation.

Last-resort exit-code reconciliation that reads ``exec_command_end`` entries
from Codex JSONL transcripts when the hook payload lacks native exit info.
"""

from __future__ import annotations

import json

from yoke_core.domain.observe import build_envelope, parse_hook_event


class TestCodexTranscriptReconciliation:
    """Codex does not emit a PostToolUseFailure event, and its PostToolUse
    payload carries no native ``exit_code`` or ``status`` — silent nonzero
    exits like ``false`` or ``exit 7`` produce empty ``tool_response`` and
    no hard-failure text. These tests prove the last-resort transcript
    reconciliation path: matching ``tool_use_id`` to the transcript's
    ``call_id`` and reading the ``exec_command_end`` entry's exit code.

    Graceful degradation is part of the contract — the Codex transcript
    JSONL schema is not published by OpenAI on the public hooks docs
    page, so any I/O or schema mismatch must leave classification
    unchanged rather than crash the hook path.
    """

    # Canonical shape observed in live rollouts under
    # ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl. The outer envelope is
    # an ``event_msg`` whose ``payload`` carries the Bash exit details.
    @staticmethod
    def _exec_end_line(call_id: str, exit_code: int, status: str) -> str:
        return json.dumps({
            "timestamp": "2026-04-17T00:10:09.804Z",
            "type": "event_msg",
            "payload": {
                "type": "exec_command_end",
                "call_id": call_id,
                "process_id": "3766",
                "turn_id": "019d98c5-136c-7052-b879-eea9a0eee69e",
                "command": ["/bin/zsh", "-lc", "whatever"],
                "cwd": "/Users/dev/yoke",
                "source": "unified_exec_startup",
                "stdout": "",
                "stderr": "",
                "aggregated_output": "",
                "exit_code": exit_code,
                "duration": {"secs": 0, "nanos": 1000},
                "formatted_output": "",
                "status": status,
            },
        })

    def test_silent_false_exit_reclassified_via_transcript(self, tmp_path):
        """``false`` exits 1 with no output — the PostToolUse payload has
        empty tool_response, no error field, no Exit code N text. Before
        transcript reconciliation this was silently recorded as success."""
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            self._exec_end_line("call_false", 1, "failed") + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_false",
            "transcript_path": str(transcript),
            "session_id": "codex-session",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is True, (
            "Silent nonzero exit must be reclassified via transcript"
        )
        assert rec.exit_code == 1
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"
        assert env["exit_code"] == 1

    def test_silent_exit_7_preserves_true_exit_code(self, tmp_path):
        """The transcript carries the real exit code — reconciliation must
        preserve it, not collapse every failure to sentinel 1."""
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            self._exec_end_line("call_exit7", 7, "failed") + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "exit 7"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_exit7",
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is True
        assert rec.exit_code == 7

    def test_successful_bash_not_reclassified(self, tmp_path):
        """Transcript says exit_code=0, status=success — gate must leave
        the record as a clean success."""
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            self._exec_end_line("call_ok", 0, "success") + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi\n"},
            "tool_use_id": "call_ok",
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False
        assert rec.exit_code == 0

    def test_no_transcript_path_no_reconciliation(self, tmp_path):
        """If the payload omits ``transcript_path`` (e.g. Claude Code),
        reconciliation is skipped and the existing classification wins."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_anything",
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        # Without transcript access we stay on the existing (imperfect)
        # classification — exit_code=0 for a silent false. This is the
        # pre-reconciliation contract, preserved for Claude Code payloads.
        assert rec.is_failure is False
        assert rec.exit_code == 0

    def test_missing_transcript_file_graceful_degradation(self, tmp_path):
        """Nonexistent transcript file must not raise — gate returns to
        the unreconciled classification."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_missing",
            "transcript_path": str(tmp_path / "does-not-exist.jsonl"),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False  # graceful: unchanged
        assert rec.exit_code == 0

    def test_schema_mismatch_graceful_degradation(self, tmp_path):
        """If the transcript JSONL doesn't contain exec_command_end entries
        (e.g. Claude transcript, or a future Codex schema change),
        reconciliation returns None — classification unchanged."""
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            json.dumps({"type": "something_else", "payload": {"type": "foo"}}) + "\n"
            + "not valid json\n"
            + json.dumps({"payload": {"type": "exec_command_end", "call_id": "different_id", "exit_code": 99, "status": "failed"}}) + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_target",  # does not match transcript
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        assert rec.is_failure is False  # unchanged — no matching call_id
        assert rec.exit_code == 0

    def test_hard_failure_text_wins_without_transcript_read(self, tmp_path):
        """The hard-failure-text fallback sets exit_code=1
        BEFORE reconciliation runs. If reconciliation only fires when the
        record would still be exit_code=0, the existing ambiguous-text
        classification is preserved — transcript is not consulted."""
        transcript = tmp_path / "rollout.jsonl"
        # Transcript claims exit_code=0 (contradicting the payload text).
        # The reconciler should NOT overturn the fallback's correct-enough
        # classification because exit_code is already non-zero.
        transcript.write_text(
            self._exec_end_line("call_cat", 0, "success") + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat /nope"},
            "tool_response": {
                "content": "cat: /nope: No such file or directory"
            },
            "tool_use_id": "call_cat",
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        # set exit_code=1 before reconciliation could run; gate
        # short-circuits (only fires when is_failure=False and exit_code
        # is None or 0).
        assert rec.is_failure is True
        assert rec.exit_code == 1

    def test_reconciliation_only_applies_to_post_tool_use(self, tmp_path):
        """Reconciliation is scoped to ``hook_event=='PostToolUse'`` —
        don't consult the transcript for other events (no such event in
        practice, but the guard prevents surprises)."""
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            self._exec_end_line("call_x", 1, "failed") + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_x",
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PreToolUse")
        assert rec is not None
        # PreToolUse → reconciliation skipped, exit_code defaults to 0.
        assert rec.is_failure is False
        assert rec.exit_code == 0

    def test_tail_bytes_cap_bounds_transcript_scan(self, tmp_path, monkeypatch):
        """Reconciliation reads only the last _TRANSCRIPT_TAIL_BYTES of
        the file. Entries beyond that window are not found. This is
        acceptable degradation — Bash commands whose exec_command_end
        sits more than a few MB back are rare, and unbounded scans would
        grow per-hook cost as sessions lengthen."""
        import yoke_core.domain.observe as observe_mod

        # Shrink the tail cap to make the test cheap.
        monkeypatch.setattr(observe_mod, "_TRANSCRIPT_TAIL_BYTES", 256)

        transcript = tmp_path / "rollout.jsonl"
        # Write the target entry first, then pad past the tail window.
        target = self._exec_end_line("call_early", 1, "failed")
        padding = "x" * 4096  # 4KB of garbage pushes target out of tail
        transcript.write_text(
            target + "\n" + padding + "\n",
            encoding="utf-8",
        )

        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": ""},
            "tool_use_id": "call_early",
            "transcript_path": str(transcript),
        }
        rec = parse_hook_event(payload, hook_event="PostToolUse")
        assert rec is not None
        # Target entry was beyond the tail window; classification stays
        # unreconciled (the degradation we accept).
        assert rec.is_failure is False
        assert rec.exit_code == 0
