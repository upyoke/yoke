"""Refuse teaching that Codex long-command streaming is automatic.

Codex's measured contract is an ``exec_command`` ``session_id`` plus explicit
``write_stdin`` continuation. A sentence that calls that path automatic is
the defect that printed ``__EXIT_CODE__=undefined`` for commands that had
already completed underneath.
"""

from __future__ import annotations

import pathlib
import re
from typing import Sequence

from yoke_contracts.harness_wake_capability import HARNESS_WAKE_CAPABILITIES


CONTINUATION_TOKEN = "write_stdin"
AUTOMATIC_RE = re.compile(r"\bautomatic(?:ally)?\b", re.IGNORECASE)
STREAMING_RE = re.compile(
    r"\b(stream(?:ing)?|PTY|exec_command|long[- ]command)\b",
    re.IGNORECASE,
)

SCAN_SURFACES: tuple[str, ...] = (
    "AGENTS.md",
    "runtime/harness/claude/rules/session.md",
    ".claude/rules/session.md",
    "docs/hook-parity-map.md",
    ".agents/skills/yoke/advance/worktree.md",
)


def explicit_continuation_harnesses() -> tuple[str, ...]:
    """Harness ids whose measured evidence names explicit continuation."""
    return tuple(
        harness_id
        for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items()
        if CONTINUATION_TOKEN in cap.evidence
    )


def continuation_contract_contradictions(
    target_root: pathlib.Path,
) -> tuple[str, ...]:
    """Return lines that call an explicit-continuation harness automatic."""
    harnesses = explicit_continuation_harnesses()
    if not harnesses:
        return ()
    harness_re = re.compile(
        "|".join(re.escape(name) for name in harnesses),
        re.IGNORECASE,
    )
    findings: list[str] = []
    for rel_path in SCAN_SURFACES:
        abs_path = target_root / rel_path
        if not abs_path.exists():
            continue
        for number, line in enumerate(
            abs_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not harness_re.search(line):
                continue
            if not AUTOMATIC_RE.search(line):
                continue
            if not STREAMING_RE.search(line):
                continue
            findings.append(f"{rel_path}:{number}: {line.strip()[:120]}")
    return tuple(findings)


def format_continuation_summary(findings: Sequence[str]) -> str:
    """Render the operator-facing report for continuation-contract drift."""
    if not findings:
        return ""
    harnesses = ", ".join(f"`{name}`" for name in explicit_continuation_harnesses())
    lines = [
        f"ERROR: {len(findings)} teaching line(s) call {harnesses} long-command "
        f"streaming automatic, which contradicts the manifest `{CONTINUATION_TOKEN}` "
        "continuation contract:",
    ]
    lines.extend(f"  - {finding}" for finding in findings)
    lines.append("")
    lines.append(
        f"Teach the explicit `{CONTINUATION_TOKEN}` continuation from the harness "
        "manifest evidence; do not infer streaming from `agent_wake.idle_wake`."
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "CONTINUATION_TOKEN",
    "SCAN_SURFACES",
    "continuation_contract_contradictions",
    "explicit_continuation_harnesses",
    "format_continuation_summary",
]
