"""Render the narrow-read recipe into generated-block marker files.

Build-time mechanism that propagates the canonical text from
:mod:`yoke_contracts.adapter_read_recipes` into the read-raw markdown
surfaces an agent reads *while deciding how to invoke a command* — the
root rules file, the CLI deep home, the Claude session rules, and the
Engineer's large-output reference. Drift is structurally impossible: the
:data:`INVENTORY` tuple is the contract, and ``--check`` mode runs in the
pre-commit hook. The marker mechanics live in
:mod:`yoke_core.tools.generated_block_render`, shared with the field-note
and harness wake-capability families.

Markers — content between is REPLACED on every run:

    <!-- BEGIN GENERATED: read-recipe -->
    <!-- END GENERATED: read-recipe -->

CLI: ``python3 -m yoke_core.tools.render_read_recipe_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence

from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_contracts import adapter_read_recipes as arr
from yoke_core.tools.generated_block_render import (
    FileRenderOutcome,
    RenderResult,
    begin_marker,
    end_marker,
    format_drift_summary,
    render_blocks,
)


# Re-exported so callers keep one import site for the family's result rows.
__all__ = (
    "INVENTORY",
    "FileRenderOutcome",
    "RenderResult",
    "render",
    "format_drift_summary_for_family",
)

SLUG: str = "read-recipe"
BEGIN_MARKER: str = begin_marker(SLUG)
END_MARKER: str = end_marker(SLUG)
REPAIR_COMMAND: str = "python3 -m yoke_core.tools.render_read_recipe_inline"

# The CLI deep home carries the worked catalog; every other inventory file
# carries the short stanza, which is what fits beside a rule.
_CATALOG_PATH: str = "docs/public/reference/agent-rules/code-and-cli.md"


# Inventory of every file that participates in the generated-block render.
# One entry per surface where a reader is choosing how to invoke a command.
INVENTORY: tuple[str, ...] = (
    "AGENTS.md",
    "docs/public/reference/agent-rules/code-and-cli.md",
    "runtime/harness/claude/rules/session.md",
    "runtime/agents/engineer/large-output.md",
)


def _build_short_block() -> str:
    """Short form: the directive plus the three routine shapes, fenced."""
    lines: list[str] = [arr.DIRECTIVE, "", "```text"]
    width = max(len(recipe) for recipe, _ in arr.COMPACT_RECIPES)
    for recipe, gloss in arr.COMPACT_RECIPES:
        lines.append(f"{recipe.ljust(width)}  # {gloss}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def _build_catalog_block() -> str:
    """Long form: one row per thing a caller is after, and its shape."""
    lines: list[str] = [
        arr.DIRECTIVE,
        "",
        "| What you want | The shape that serves it |",
        "| --- | --- |",
    ]
    for recipe in arr.RECIPES:
        shape = f"`{recipe.recipe}` — {recipe.note}"
        lines.append(f"| {recipe.want} | {shape} |")
    lines.append("")
    return "\n".join(lines)


def _content_for_path(rel_path: str) -> str:
    if rel_path == _CATALOG_PATH:
        return _build_catalog_block()
    return _build_short_block()


def render(
    target_root: pathlib.Path,
    *,
    check: bool = False,
) -> RenderResult:
    """Render the narrow-read recipe into every inventory file."""
    return render_blocks(
        target_root,
        slug=SLUG,
        inventory=INVENTORY,
        content_for_path=_content_for_path,
        check=check,
    )


def format_drift_summary_for_family(result: RenderResult, *, check: bool) -> str:
    """Render this family's drift summary, naming its repair command."""
    return format_drift_summary(
        result,
        check=check,
        family_label="read-recipe",
        repair_command=REPAIR_COMMAND,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_read_recipe_inline",
        description=(
            "Render the narrow-read recipe into every generated-block "
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
        target_root = resolve_target_root_for_cli(args.target_root)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    result = render(target_root, check=args.check)

    summary = format_drift_summary_for_family(result, check=args.check)
    if summary:
        sys.stderr.write(summary)

    if not result.ok:
        return 1
    if args.check and result.changed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
