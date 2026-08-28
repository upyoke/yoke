"""Render the field-note directive into generated-block marker files.

Build-time mechanism that propagates the canonical text from
:mod:`yoke_contracts.field_note_text` into every read-raw markdown
surface (skill bodies, operator docs, the long-form
``runtime/agents/_shared/ouroboros-field-note.md``). Drift is
structurally impossible: the :data:`INVENTORY` tuple is the contract, and
``--check`` mode runs in the pre-commit hook + the
``HC-field-note-coherence`` doctor HC. The marker mechanics themselves
live in :mod:`yoke_core.tools.generated_block_render`, shared with the
harness wake-capability family.

Markers — content between is REPLACED on every run:

    <!-- BEGIN GENERATED: field-note-directive -->
    <!-- END GENERATED: field-note-directive -->

CLI: ``python3 -m yoke_core.tools.render_field_note_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence

from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_contracts import field_note_text as rft
from yoke_core.tools.generated_block_render import (
    RenderResult,
    begin_marker,
    end_marker,
    format_drift_summary,
    render_blocks,
)


SLUG: str = "field-note-directive"
BEGIN_MARKER: str = begin_marker(SLUG)
END_MARKER: str = end_marker(SLUG)
REPAIR_COMMAND: str = "python3 -m yoke_core.tools.render_field_note_inline"

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
    ".agents/skills/yoke/charge/SKILL.md",
    ".agents/skills/yoke/conduct/SKILL.md",
    ".agents/skills/yoke/curate/SKILL.md",
    ".agents/skills/yoke/do/SKILL.md",
    ".agents/skills/yoke/doctor/SKILL.md",
    ".agents/skills/yoke/feed/SKILL.md",
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
    ".agents/skills/yoke/usher/SKILL.md",
    ".agents/skills/yoke/wrapup/SKILL.md",
    "README.md",
    "AGENTS.md",
    "docs/OVERVIEW.md",
    ".yoke/docs/reference/commands.md",
    "docs/prompt-philosophy.md",
    ".yoke/docs/reference/lifecycle.md",
    "docs/local-setup.md",
    ".yoke/strategy/FUTURE-NOTES.md",
    "runtime/harness/claude/rules/session.md",
    _SHARED_LONG_FORM_PATH,
)


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


def render(
    target_root: pathlib.Path,
    *,
    check: bool = False,
) -> RenderResult:
    """Render the field-note directive into every inventory file."""
    return render_blocks(
        target_root,
        slug=SLUG,
        inventory=INVENTORY,
        content_for_path=_content_for_path,
        check=check,
    )


def _format_drift_summary(result: RenderResult, *, check: bool) -> str:
    return format_drift_summary(
        result,
        check=check,
        family_label="field-note",
        repair_command=REPAIR_COMMAND,
    )


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
