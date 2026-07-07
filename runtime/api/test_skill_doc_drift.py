"""Doc-drift regression suite for `.agents/skills/yoke/**/*.md`.

Two complementary scans:

* **Token regressions** — explicit regex rules per known-drifted shape.
* **Write-shape lint validation** — fenced ``bash`` blocks containing
  ``items update --stdin`` (the YOK-1748 drift class) are validated
  against ``lint_shell_quoted_function_payload`` and
  ``lint_structured_field_transform_shell``.

Suppression: append ``# doc-drift-allow:<reason>`` (or the inline
HTML-comment form ``<!-- doc-drift-allow:<reason> -->``) to a line to
record an intentional negative example.

Pre-existing drift in files claimed by other live tickets is
grandfathered via ``_KNOWN_LEGACY_OFFENDERS``; drain the allowlist as
the owning tickets land.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Pattern, Tuple

import pytest

from yoke_core.domain.lint_shell_quoted_function_payload import (
    evaluate_command as _lint_shell_quoted_function_payload,
)
from yoke_core.domain.lint_structured_field_transform_shell import (
    evaluate_command as _lint_structured_field_transform_shell,
)
from runtime.api.skill_doc_regressions_test_helpers import SKILLS


SUPPRESSION_MARKER = "# doc-drift-allow:"
# Accept either the bash-style ``# doc-drift-allow:<reason>`` comment or
# the HTML-comment form ``<!-- doc-drift-allow:<reason> -->`` (the natural
# fit for inline markdown prose where a bash comment would be visible).
_SUPPRESSION_SIGIL = "doc-drift-allow:"


# Pre-existing drift in files claimed by other live tickets. Each entry
# is ``(rule_label, "<relative-path>:<line>")``. Drain the allowlist as
# the owning tickets land.
_KNOWN_LEGACY_OFFENDERS: frozenset = frozenset(
    {
        # merge/post-merge.md — no active sibling claim, but file is part
        # of the sub-issue 14a packet teaching slice (not YOK-1748's scope).
        ("lifecycle.transition envelope without .execute",
         ".agents/skills/yoke/merge/post-merge.md:48"),
    }
)


# ---------------------------------------------------------------------------
# Token regressions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenRule:
    """One drifted-shape rule applied to every Yoke skill markdown file."""

    label: str
    pattern: Pattern[str]
    canonical: str


_TOKEN_RULES: Tuple[TokenRule, ...] = (
    TokenRule(
        label="normalize_ac_labels --item",
        pattern=re.compile(r"normalize_ac_labels[^\n`]*--item\b"),
        canonical="normalize_ac_labels reads from stdin or `--file FILE`",
    ),
    TokenRule(
        label="section-upsert --heading",
        pattern=re.compile(r"sections?\s+upsert[^\n`]*--heading\b"),
        canonical="`sections upsert <item-id> <section-name> --content-file ...`",
    ),
    TokenRule(
        label="path-claim-widen --item",
        pattern=re.compile(r"path-claim-widen[^\n`]*--item\b"),
        canonical="positional `claim_id` plus comma-separated `--paths`",
    ),
    TokenRule(
        label="path-claim-widen --path",
        pattern=re.compile(r"path-claim-widen[^\n`]*\s--path\b"),
        canonical="plural `--paths file1.py,file2.py`",
    ),
    TokenRule(
        label="lifecycle.transition envelope without .execute",
        # Match `"function": "lifecycle.transition"` (or single-quoted)
        # but NOT `.execute`, `.completed`, or sibling registry names.
        pattern=re.compile(
            r'"function"\s*:\s*"lifecycle\.transition"|'
            r"'function'\s*:\s*'lifecycle\.transition'"
        ),
        canonical='`"function": "lifecycle.transition.execute"`',
    ),
    TokenRule(
        label="lifecycle payload {from, to}",
        pattern=re.compile(
            r'"payload"\s*:\s*\{[^}]*?"from"\s*:\s*"[^"]*"\s*,\s*"to"\s*:\s*"[^"]*"'
        ),
        canonical='`payload.target_status` + optional `payload.source_status`',
    ),
    TokenRule(
        label="dependency-add source=agent",
        pattern=re.compile(r"dependency-add[^\n`]*\sagent\b"),
        canonical=(
            "valid sources: conduct | feed | idea | migration | operator | "
            "refine | shepherd"
        ),
    ),
    TokenRule(
        label="sleep <60>s && tail polling",
        pattern=re.compile(
            r"\bsleep\s+(?:[1-9]|[1-5]\d)\b[^\n]*?(?:&&|;)\s*(?:tail|head|cat)\b"
        ),
        canonical=(
            "use `Bash(run_in_background=true)` + `Monitor`, or the fallback "
            "cadence floor (60s)"
        ),
    ),
)


def _iter_markdown_files() -> Iterable[Path]:
    """Yield every `.md` file under `.agents/skills/yoke/`."""
    for path in sorted(SKILLS.rglob("*.md")):
        if path.is_file():
            yield path


def _line_has_suppression(line: str) -> bool:
    return _SUPPRESSION_SIGIL in line


def _scan_lines(text: str, rule: TokenRule) -> List[Tuple[int, str]]:
    """Return (line_number, line_text) hits that lack a suppression marker."""
    hits: List[Tuple[int, str]] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        if not rule.pattern.search(raw_line):
            continue
        if _line_has_suppression(raw_line):
            continue
        hits.append((index, raw_line.rstrip()))
    return hits


class TestSkillDocTokenRegressions:
    """Each known-drifted token must not reappear without suppression."""

    @pytest.mark.parametrize(
        "rule",
        _TOKEN_RULES,
        ids=lambda rule: rule.label,
    )
    def test_token_rule(self, rule: TokenRule) -> None:
        offenders: List[str] = []
        for md_path in _iter_markdown_files():
            text = md_path.read_text(encoding="utf-8")
            for line_number, line_text in _scan_lines(text, rule):
                rel = md_path.relative_to(SKILLS.parent.parent.parent)
                location = f"{rel}:{line_number}"
                if (rule.label, location) in _KNOWN_LEGACY_OFFENDERS:
                    continue
                offenders.append(f"{location}: {line_text}")
        assert not offenders, (
            f"Drifted shape ``{rule.label}`` detected — canonical: "
            f"{rule.canonical}. Add ``{SUPPRESSION_MARKER}<reason>`` to "
            "the line to record an intentional negative example, or "
            "register a pre-existing offender in _KNOWN_LEGACY_OFFENDERS "
            "(rare — prefer fixing in scope when claim allows).\n"
            + "\n".join(offenders)
        )


# ---------------------------------------------------------------------------
# Fenced-block lint validation
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(
    r"^```(?P<lang>bash|sh|shell)\s*\n(?P<body>.*?)(?<=\n)```",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class _FencedCommand:
    md_path: Path
    line_number: int
    command: str


def _strip_continuations(block: str) -> List[Tuple[int, str]]:
    """Collapse ``\\``-continuation lines into ``(offset, command)`` pairs."""
    logical: List[Tuple[int, str]] = []
    buffer: List[str] = []
    start_offset = 0
    for offset, raw_line in enumerate(block.splitlines(), start=1):
        if not buffer:
            start_offset = offset
        stripped = raw_line.rstrip()
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1])
            continue
        buffer.append(stripped)
        logical.append((start_offset, " ".join(p.strip() for p in buffer if p.strip())))
        buffer = []
    if buffer:
        logical.append((start_offset, " ".join(p.strip() for p in buffer if p.strip())))
    return [(line_no, cmd) for line_no, cmd in logical if cmd]


def _is_skippable(command: str) -> bool:
    stripped = command.strip()
    if not stripped or stripped.startswith("#"):
        return True
    if stripped.startswith(("{", "<")) and stripped.endswith(("}", ">")):
        return True
    return False


def _iter_fenced_commands() -> Iterable[_FencedCommand]:
    for md_path in _iter_markdown_files():
        text = md_path.read_text(encoding="utf-8")
        line_index = text.splitlines()
        prefix_offsets: List[int] = [0]
        running = 0
        for line in line_index:
            running += len(line) + 1
            prefix_offsets.append(running)
        for match in _FENCE_RE.finditer(text):
            block_start_char = match.start("body")
            block_line = next(
                idx
                for idx, offset in enumerate(prefix_offsets, start=1)
                if offset > block_start_char
            )
            body = match.group("body")
            for inner_offset, command in _strip_continuations(body):
                if _is_skippable(command):
                    continue
                if SUPPRESSION_MARKER in command:
                    continue
                yield _FencedCommand(
                    md_path=md_path,
                    line_number=block_line + inner_offset - 1,
                    command=command,
                )


_ITEMS_UPDATE_STDIN_RE = re.compile(r"\bitems\s+update\b[^\n;|&]*--stdin\b")

_FENCED_LINTS = (
    (
        "shell_quoted_function_payload",
        _lint_shell_quoted_function_payload,
        "Switch to the Write-tool tempfile + bare ``< /tmp/...`` redirect",
    ),
    (
        "structured_field_transform_shell",
        _lint_structured_field_transform_shell,
        "Use ``items.structured_field.section_upsert`` / "
        "``items.progress_log.append`` instead of read-modify-write choreography",
    ),
)


class TestSkillDocFencedCommandLint:
    """Fenced ``items update --stdin`` examples must pass the YOK-1748 lints.

    Narrow scope: only commands matching the YOK-1748 drift class are
    pushed through the lints. Other write-shape adapters
    (``qa requirement-add-batch --json-file``, ``epic simulation-upsert``,
    etc.) are governed by their own tickets.
    """

    @pytest.mark.parametrize(
        "lint_name,lint_fn,remediation",
        _FENCED_LINTS,
        ids=[name for name, _, _ in _FENCED_LINTS],
    )
    def test_fenced_command_lint(self, lint_name, lint_fn, remediation) -> None:
        offenders: List[str] = []
        for fenced in _iter_fenced_commands():
            if not _ITEMS_UPDATE_STDIN_RE.search(fenced.command):
                continue
            if lint_fn(fenced.command) is None:
                continue
            rel = fenced.md_path.relative_to(SKILLS.parent.parent.parent)
            offenders.append(
                f"{rel}:{fenced.line_number}: {fenced.command[:120]}"
            )
        assert not offenders, (
            f"Fenced ``items update --stdin`` example matched {lint_name}. "
            f"{remediation}, or append ``{SUPPRESSION_MARKER}<reason>`` to "
            "the command line for an intentional negative example.\n"
            + "\n".join(offenders)
        )
