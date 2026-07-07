"""Tests for yoke_core.tools.transcript_reflection_audit (AC-21 verification path)."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from yoke_core.tools import transcript_reflection_audit as audit


VALID_BLOCK = (
    "---REFLECTION-START---\n"
    "---BEGIN ENTRY---\n"
    "timestamp: 2026-05-22T00:00:00Z\n"
    "agent: engineer\n"
    "context: YOK-1832\n"
    "category: friction\n"
    "Body of the entry under audit.\n"
    "---END ENTRY---\n"
    "---REFLECTION-END---"
)

# Canonical framing is shape A's territory; the generic-freeform fallback
# skips canonical-framed blocks so a malformed canonical entry (no
# ``category`` field, no ``observation`` fallback, body is a novel
# unparseable sequence) is the only legitimate unrecognized class once the
# permissive parsers landed.
UNRECOGNIZED_BLOCK = (
    "---REFLECTION-START---\n"
    "---BEGIN ENTRY---\n"
    "????? completely novel shape with no parser ?????\n"
    "---END ENTRY---\n"
    "---REFLECTION-END---"
)


def _write_transcript(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for field in fields:
            f.write(json.dumps({"assistant_text": field}) + "\n")


def test_returns_zero_unrecognized_for_canonical_block(tmp_path):
    transcript = tmp_path / "session-a" / "transcript.jsonl"
    _write_transcript(transcript, [VALID_BLOCK])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["transcripts_scanned"] == 1
    assert totals["blocks_seen"] == 1
    assert totals["blocks_parsed_successfully"] == 1
    assert totals["blocks_unrecognized"] == 0
    assert totals["entries_extracted"] == 1


def test_records_unrecognized_block(tmp_path):
    transcript = tmp_path / "session-b" / "transcript.jsonl"
    _write_transcript(transcript, [UNRECOGNIZED_BLOCK])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["blocks_unrecognized"] == 1
    assert totals["unrecognized_examples"]
    assert "completely novel" in totals["unrecognized_examples"][0]["excerpt"]


def test_expect_zero_unrecognized_returns_nonzero_when_unhandled(tmp_path, capsys):
    transcript = tmp_path / "session-c" / "transcript.jsonl"
    _write_transcript(transcript, [UNRECOGNIZED_BLOCK])
    rc = audit.main([
        "--transcripts", str(tmp_path),
        "--expect-zero-unrecognized",
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err


def test_expect_zero_unrecognized_returns_zero_on_clean_corpus(tmp_path):
    transcript = tmp_path / "session-d" / "transcript.jsonl"
    _write_transcript(transcript, [VALID_BLOCK])
    rc = audit.main([
        "--transcripts", str(tmp_path),
        "--expect-zero-unrecognized",
    ])
    assert rc == 0


def test_json_output(tmp_path, capsys):
    transcript = tmp_path / "session-e" / "transcript.jsonl"
    _write_transcript(transcript, [VALID_BLOCK])
    rc = audit.main([
        "--transcripts", str(tmp_path),
        "--json",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["transcripts_scanned"] == 1
    assert parsed["blocks_parsed_successfully"] == 1


def test_no_reflection_text_is_skipped(tmp_path):
    transcript = tmp_path / "session-f" / "transcript.jsonl"
    _write_transcript(transcript, ["just normal output without delimiters"])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["blocks_seen"] == 0
    assert totals["blocks_unrecognized"] == 0


def test_missing_root_returns_empty(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    totals, transcripts = audit._aggregate(nonexistent)
    assert totals["transcripts_scanned"] == 0
    assert transcripts == []


def _write_codex_transcript(path: Path, payload_content_blocks: list[str]) -> None:
    """Write a Codex-shape JSONL with `{timestamp, type, payload}` envelope.

    Each entry in *payload_content_blocks* becomes one ``response_item`` line
    whose ``payload.content`` is a list of ``{type: "input_text", text: ...}``
    dicts — the exact shape Codex emits in its rollout JSONLs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for body in payload_content_blocks:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-04-03T18:52:01.331Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "input_text", "text": body}],
                        },
                    }
                )
                + "\n"
            )


def test_codex_envelope_payload_content_is_walked(tmp_path):
    """The walker must descend into ``payload.content`` for Codex JSONLs."""
    transcript = tmp_path / "2026" / "04" / "03" / "rollout-test.jsonl"
    _write_codex_transcript(transcript, [VALID_BLOCK])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["transcripts_scanned"] == 1
    assert totals["blocks_seen"] == 1
    assert totals["blocks_parsed_successfully"] == 1
    assert totals["blocks_unrecognized"] == 0
    assert totals["entries_extracted"] == 1


def test_codex_envelope_unrecognized_block_classified(tmp_path):
    transcript = tmp_path / "rollout-codex.jsonl"
    _write_codex_transcript(transcript, [UNRECOGNIZED_BLOCK])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["blocks_unrecognized"] == 1
    assert "completely novel" in totals["unrecognized_examples"][0]["excerpt"]


def _write_codex_function_call_output(path: Path, output_bodies: list[str]) -> None:
    """Write Codex ``function_call_output`` rows where text lands in ``payload.output``.

    Codex stores captured stdout from a sub-process invocation (e.g., the
    operator pasting a `cat` of a docs file that contains the reflection
    contract teaching) under ``payload.output``, not under
    ``payload.content``. The walker must recognise this field.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for body in output_bodies:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-05-13T04:29:26.853Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call_test",
                            "output": body,
                        },
                    }
                )
                + "\n"
            )


def test_codex_function_call_output_payload_is_walked(tmp_path):
    """``payload.output`` (Codex function_call_output) must be walked."""
    transcript = tmp_path / "rollout-fco.jsonl"
    _write_codex_function_call_output(transcript, [VALID_BLOCK])
    totals, _ = audit._aggregate(tmp_path)
    assert totals["transcripts_scanned"] == 1
    assert totals["blocks_seen"] == 1
    assert totals["blocks_parsed_successfully"] == 1


def test_codex_session_meta_envelope_without_content_is_safe(tmp_path):
    """``session_meta`` lines lack the ``content`` list — must not crash."""
    transcript = tmp_path / "rollout-meta.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": "2026-04-03T18:52:01.331Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "019d54b0",
                        "cwd": "/some/path",
                        "originator": "Codex Desktop",
                    },
                }
            )
            + "\n"
        )
    totals, _ = audit._aggregate(tmp_path)
    assert totals["transcripts_scanned"] == 1
    assert totals["blocks_seen"] == 0
