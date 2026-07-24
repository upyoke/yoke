"""Render the field-note directive into generated-block marker files.

Build-time mechanism that propagates the canonical text from
:mod:`yoke_contracts.field_note_text` into every read-raw markdown
surface (skill bodies, operator docs, the long-form
``runtime/agents/_shared/ouroboros-field-note.md``). Drift is
structurally impossible: the :data:`INVENTORY` tuple is the contract, and
``--check`` mode runs in the pre-commit hook + the
``HC-field-note-coherence`` doctor HC.

Markers — content between is REPLACED on every run:

    <!-- BEGIN GENERATED: field-note-directive -->
    <!-- END GENERATED: field-note-directive -->

CLI: ``python3 -m yoke_core.tools.render_field_note_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
from typing import Sequence

from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_contracts import field_note_text as rft
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


BEGIN_MARKER: str = "<!-- BEGIN GENERATED: field-note-directive -->"
END_MARKER: str = "<!-- END GENERATED: field-note-directive -->"

# The long-form file carries directive + worked-mode catalog + help pointer.
# Every other inventory file carries only the short FOOTER.
_SHARED_LONG_FORM_PATH: str = "runtime/agents/_shared/ouroboros-field-note.md"


# Inventory of every file that participates in the generated-block render.
# Tasks 011 (skill body insertion) and 014 (HC-field-note-coherence)
# import this tuple as their authoritative source of truth.
INVENTORY: tuple[str, ...] = (
    ".agents/skills/yoke/advance/SKILL.md",
    ".agents/skills/yoke/amend/SKILL.md",
    ".agents/skills/yoke/approve/SKILL.md",
    ".agents/skills/yoke/block/SKILL.md",
    ".agents/skills/yoke/charge/SKILL.md",
    ".agents/skills/yoke/conduct/SKILL.md",
    ".agents/skills/yoke/curate/SKILL.md",
    ".agents/skills/yoke/do/SKILL.md",
    ".agents/skills/yoke/doctor/SKILL.md",
    ".agents/skills/yoke/feed/SKILL.md",
    ".agents/skills/yoke/freeze/SKILL.md",
    ".agents/skills/yoke/help/SKILL.md",
    ".agents/skills/yoke/idea/SKILL.md",
    ".agents/skills/yoke/merge/SKILL.md",
    ".agents/skills/yoke/plan/SKILL.md",
    ".agents/skills/yoke/polish/SKILL.md",
    ".agents/skills/yoke/refine/SKILL.md",
    ".agents/skills/yoke/resync/SKILL.md",
    ".agents/skills/yoke/shepherd/SKILL.md",
    ".agents/skills/yoke/simulate/SKILL.md",
    ".agents/skills/yoke/strategize/SKILL.md",
    ".agents/skills/yoke/thaw/SKILL.md",
    ".agents/skills/yoke/unblock/SKILL.md",
    ".agents/skills/yoke/usher/SKILL.md",
    ".agents/skills/yoke/wrapup/SKILL.md",
    "README.md",
    "AGENTS.md",
    "docs/OVERVIEW.md",
    ".yoke/docs/commands.md",
    "docs/prompt-philosophy.md",
    ".yoke/docs/lifecycle.md",
    "docs/local-setup.md",
    ".yoke/strategy/FUTURE-NOTES.md",
    "runtime/harness/claude/rules/session.md",
    _SHARED_LONG_FORM_PATH,
)


@dataclasses.dataclass(frozen=True)
class FileRenderOutcome:
    """One inventory file's render result."""

    path: str  # repo-relative
    state: str  # "rendered" | "unchanged" | "missing_markers" | "missing_file"


@dataclasses.dataclass(frozen=True)
class RenderResult:
    """Aggregate render result returned by :func:`render`."""

    changed: tuple[FileRenderOutcome, ...]
    unchanged: tuple[FileRenderOutcome, ...]
    missing_markers: tuple[FileRenderOutcome, ...]
    missing_files: tuple[FileRenderOutcome, ...]
    orphan_marker_errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        # Orphan markers (BEGIN without END, multiple pairs in one file) are
        # the only hard-fail class. Inventory files lacking marker pairs
        # entirely are advisory — they participate by enumeration but their
        # marker insertion may land in a later slice (Task 011 / Task 014).
        return not self.orphan_marker_errors


def _build_short_block() -> str:
    return rft.FOOTER + "\n"


def _build_long_block() -> str:
    """Long form: directive + copy-paste + worked-mode catalog + help pointer.

    Generated programmatically from FAILURE_MODES so adding or dropping a
    mode in field_note_text re-renders here automatically.
    """
    lines: list[str] = [
        rft.DIRECTIVE,
        "",
        "Copy-paste recipe:",
        "",
        "    " + rft.BASIC_RECIPE,
        "",
        "## Failure modes",
        "",
    ]
    for mode in rft.FAILURE_MODES:
        lines.append(f"### {mode.title} (`--kind {mode.kind}`)")
        lines.append("")
        lines.append(f"**When to fire:** {mode.when_to_fire}")
        lines.append("")
        lines.append(f"**Example evidence:** {mode.example_evidence}")
        lines.append("")
    lines.append(rft.HELP_POINTER)
    lines.append("")
    return "\n".join(lines)


def _content_for_path(rel_path: str) -> str:
    if rel_path == _SHARED_LONG_FORM_PATH:
        return _build_long_block()
    return _build_short_block()


def _rewrite_between_markers(original: str, replacement: str) -> str | None:
    """Return rewritten content; None when markers missing or ill-formed."""
    begin_idx = original.find(BEGIN_MARKER)
    end_idx = original.find(END_MARKER)
    if begin_idx < 0 or end_idx < 0:
        return None
    if end_idx < begin_idx:
        return None
    next_begin = original.find(BEGIN_MARKER, begin_idx + len(BEGIN_MARKER))
    if 0 <= next_begin < end_idx:
        return None
    head = original[: begin_idx + len(BEGIN_MARKER)]
    tail = original[end_idx:]
    return f"{head}\n{replacement}{tail}"


def _scan_for_orphans(text: str) -> str | None:
    """Return a description of the orphan condition, or None if clean."""
    has_begin = BEGIN_MARKER in text
    has_end = END_MARKER in text
    if has_begin and not has_end:
        return "BEGIN marker without matching END"
    if has_end and not has_begin:
        return "END marker without matching BEGIN"
    if text.count(BEGIN_MARKER) > 1 or text.count(END_MARKER) > 1:
        return "multiple marker pairs in one file (not supported)"
    return None


def render(
    target_root: pathlib.Path,
    *,
    check: bool = False,
) -> RenderResult:
    """Render the field-note directive into every inventory file."""
    changed: list[FileRenderOutcome] = []
    unchanged: list[FileRenderOutcome] = []
    missing_markers: list[FileRenderOutcome] = []
    missing_files: list[FileRenderOutcome] = []
    orphan_errors: list[str] = []

    for rel_path in INVENTORY:
        abs_path = target_root / rel_path
        if not abs_path.exists():
            missing_files.append(
                FileRenderOutcome(path=rel_path, state="missing_file")
            )
            continue

        original = abs_path.read_text(encoding="utf-8")
        replacement_block = _content_for_path(rel_path)

        orphan = _scan_for_orphans(original)
        if orphan is not None:
            orphan_errors.append(f"{rel_path}: {orphan}")
            missing_markers.append(
                FileRenderOutcome(path=rel_path, state="missing_markers")
            )
            continue

        rewritten = _rewrite_between_markers(original, replacement_block)
        if rewritten is None:
            missing_markers.append(
                FileRenderOutcome(path=rel_path, state="missing_markers")
            )
            continue

        if rewritten == original:
            unchanged.append(
                FileRenderOutcome(path=rel_path, state="unchanged")
            )
            continue

        changed.append(FileRenderOutcome(path=rel_path, state="rendered"))
        if not check:
            assert_target_under_session_work_authority(abs_path)
            abs_path.write_text(rewritten, encoding="utf-8")

    return RenderResult(
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        missing_markers=tuple(missing_markers),
        missing_files=tuple(missing_files),
        orphan_marker_errors=tuple(orphan_errors),
    )


def _format_drift_summary(result: RenderResult, *, check: bool) -> str:
    parts: list[str] = []
    if check and result.changed:
        parts.append(
            f"ERROR: field-note renderer would change "
            f"{len(result.changed)} file(s):"
        )
        for outcome in result.changed:
            parts.append(f"  - {outcome.path}")
        parts.append("")
        parts.append(
            "Run `python3 -m yoke_core.tools.render_field_note_inline` "
            "(no flag) and re-stage."
        )
    if result.missing_markers and check:
        # Surface as advisory only (not blocking) so a partial rollout —
        # where Task 002 lands the renderer before Task 011 inserts the
        # skill-body markers — does not break commits.
        parts.append(
            f"NOTE: {len(result.missing_markers)} inventory file(s) lack a "
            f"valid marker pair (advisory):"
        )
        for outcome in result.missing_markers:
            parts.append(f"  - {outcome.path}")
    if result.orphan_marker_errors:
        parts.append("Orphan-marker details:")
        for line in result.orphan_marker_errors:
            parts.append(f"  - {line}")
    if result.missing_files:
        parts.append(
            f"WARNING: {len(result.missing_files)} inventory file(s) missing "
            f"on disk (skipped):"
        )
        for outcome in result.missing_files:
            parts.append(f"  - {outcome.path}")
    return "\n".join(parts) + ("\n" if parts else "")


def _resolve_target_root(arg: str | None) -> pathlib.Path:
    return resolve_target_root_for_cli(arg)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_field_note_inline",
        description=(
            "Render the field-note directive into every generated-block "
            "marker file. Use --check in CI / pre-commit to fail on drift."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: report drift and exit non-zero on any required change.",
    )
    parser.add_argument(
        "--target-root",
        default=None,
        help="Repo root to render against (default: git toplevel or cwd).",
    )
    args = parser.parse_args(argv)

    try:
        target_root = _resolve_target_root(args.target_root)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    result = render(target_root, check=args.check)

    summary = _format_drift_summary(result, check=args.check)
    if summary:
        sys.stderr.write(summary)

    if not result.ok:
        return 1
    if args.check and result.changed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
