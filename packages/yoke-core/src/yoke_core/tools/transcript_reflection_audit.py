"""Re-walk local harness transcripts and benchmark the production parser.

Operator/debug tool that consumes the JSONL transcripts under
``~/.claude/projects/`` (or any directory passed via ``--transcripts``,
including Codex's ``~/.codex/sessions/`` and
``~/.codex/archived_sessions/`` trees) and runs the production
multi-shape parser
(:func:`yoke_core.domain.reflection_capture_shapes.parse_text`)
against each reflection-bounded block. Both Yoke-supported harnesses
produce JSONL session storage; the walker recognises both envelopes
(Claude's top-level ``content`` / ``message`` fields and Codex's
``{timestamp, type, payload}`` envelope with nested ``payload.content``
lists).

Reports the structured CaptureResult counts:

* ``blocks_seen`` — total reflection-bounded blocks detected.
* ``blocks_parsed_successfully`` — blocks the multi-shape parser
  recognized and extracted entries from.
* ``blocks_skipped_known_falsepositive`` — blocks classified into one of
  the six documented false-positive patterns.
* ``blocks_unrecognized`` — **must be 0** for the parser to be complete.
* ``blocks_partial_no_end_marker`` — start marker without a closing end
  marker (mid-emission truncation).

Exits non-zero when ``--expect-zero-unrecognized`` is passed AND
``blocks_unrecognized > 0``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Tuple


DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"


def _iter_transcripts(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    yield from sorted(root.rglob("*.jsonl"))


def _yield_from_object(obj: dict) -> Iterable[str]:
    """Yield text-shaped fields from a single JSONL dict (Claude or Codex shape).

    Recognised field shapes:

    * **Top-level string fields**: ``assistant_text``, ``tool_result_str``,
      ``text``, ``output`` (Codex ``function_call_output`` payloads store
      their captured stdout under ``output``).
    * **``content``** as a string OR a list of ``{type, text}`` dicts /
      bare strings.
    * **``message.content``** as a string OR a list of ``{type, text}``
      dicts — Claude tool-result envelope.
    """
    for field in ("assistant_text", "tool_result_str", "text", "output"):
        val = obj.get(field)
        if isinstance(val, str) and val:
            yield val
    content = obj.get("content")
    if isinstance(content, str) and content:
        yield content
    elif isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                v = c.get("text")
                if isinstance(v, str) and v:
                    yield v
            elif isinstance(c, str) and c:
                yield c
    msg = obj.get("message")
    if isinstance(msg, dict):
        mc = msg.get("content")
        if isinstance(mc, str) and mc:
            yield mc
        elif isinstance(mc, list):
            for c in mc:
                if isinstance(c, dict):
                    v = c.get("text")
                    if isinstance(v, str) and v:
                        yield v


def _iter_text_fields(jsonl_path: Path) -> Iterable[str]:
    """Yield every text-shaped field from each line of a transcript JSONL.

    Handles two envelope shapes:

    * **Claude Code**: top-level keys like ``assistant_text``,
      ``content`` (str/list), ``message.content``.
    * **Codex**: ``{timestamp, type, payload}`` envelope where the
      semantic content lives under ``payload`` (notably ``payload.content``
      as a list of ``{type, text}`` dicts inside ``response_item``
      rows). Descended into recursively against the same field set.
    """
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                yield from _yield_from_object(obj)
                payload = obj.get("payload")
                if isinstance(payload, dict):
                    yield from _yield_from_object(payload)
    except OSError:
        return


def _aggregate(root: Path) -> Tuple[dict, list[Path]]:
    """Walk *root* and run the production parser against every text field."""
    from yoke_core.domain.reflection_capture_shapes import parse_text

    totals = {
        "transcripts_scanned": 0,
        "fields_scanned": 0,
        "blocks_seen": 0,
        "blocks_parsed_successfully": 0,
        "blocks_skipped_known_falsepositive": 0,
        "blocks_unrecognized": 0,
        "blocks_partial_no_end_marker": 0,
        "entries_extracted": 0,
        "unrecognized_examples": [],
    }
    transcripts: list[Path] = []
    for transcript in _iter_transcripts(root):
        transcripts.append(transcript)
        totals["transcripts_scanned"] += 1
        for text in _iter_text_fields(transcript):
            totals["fields_scanned"] += 1
            if "REFLECTION-START" not in text and "REFLECTION-END" not in text:
                continue
            entries, result = parse_text(text, default_agent="unknown")
            totals["blocks_seen"] += result.blocks_seen
            totals["blocks_parsed_successfully"] += result.blocks_parsed_successfully
            totals["blocks_skipped_known_falsepositive"] += (
                result.blocks_skipped_known_falsepositive
            )
            totals["blocks_unrecognized"] += result.blocks_unrecognized
            totals["blocks_partial_no_end_marker"] += result.blocks_partial_no_end_marker
            totals["entries_extracted"] += len(entries)
            for ex in result.unrecognized_block_examples[:3]:
                totals["unrecognized_examples"].append({
                    "transcript": str(transcript),
                    "excerpt": ex.get("excerpt", "")[:200],
                })
    return totals, transcripts


def _format_report(totals: dict) -> str:
    lines = [
        "Transcript reflection audit",
        "---------------------------",
        f"Transcripts scanned:       {totals['transcripts_scanned']}",
        f"Text fields scanned:       {totals['fields_scanned']}",
        f"Blocks seen:               {totals['blocks_seen']}",
        f"Blocks parsed:             {totals['blocks_parsed_successfully']}",
        f"Blocks false-positive:     {totals['blocks_skipped_known_falsepositive']}",
        f"Blocks unrecognized:       {totals['blocks_unrecognized']}  "
        f"{'(PASS)' if totals['blocks_unrecognized'] == 0 else '(NEEDS PARSER EXTENSION)'}",
        f"Blocks partial (no end):   {totals['blocks_partial_no_end_marker']}",
        f"Entries extracted:         {totals['entries_extracted']}",
    ]
    if totals["unrecognized_examples"]:
        lines.append("")
        lines.append("Unrecognized examples (first 10):")
        for ex in totals["unrecognized_examples"][:10]:
            lines.append(f"- {ex['transcript']}")
            lines.append(f"  {ex['excerpt']!r}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Walk local Claude Code transcripts and benchmark the "
            "production reflection parser."
        ),
    )
    ap.add_argument(
        "--transcripts",
        type=Path,
        default=DEFAULT_TRANSCRIPT_ROOT,
        help=f"Transcript root (default: {DEFAULT_TRANSCRIPT_ROOT})",
    )
    ap.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help=(
            "Optional: path to a scratch-backed backfill artifacts dir. Reserved for "
            "future diff-against-discovery-walker output."
        ),
    )
    ap.add_argument(
        "--expect-zero-unrecognized",
        action="store_true",
        help=(
            "Exit non-zero when blocks_unrecognized > 0"
        ),
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit the raw totals as JSON instead of the human report",
    )
    args = ap.parse_args(argv)

    totals, _ = _aggregate(args.transcripts)
    if args.json:
        print(json.dumps(totals, indent=2))
    else:
        print(_format_report(totals))

    if args.expect_zero_unrecognized and totals["blocks_unrecognized"] > 0:
        print(
            f"\nFAIL: blocks_unrecognized={totals['blocks_unrecognized']} > 0. "
            "Extend the parser in yoke_core.domain.reflection_capture_shape_parsers "
            "or add a false-positive classifier in "
            "yoke_core.domain.reflection_capture_shapes.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
