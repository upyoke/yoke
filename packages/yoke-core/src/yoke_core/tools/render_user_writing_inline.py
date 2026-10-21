"""Render the user-writing rules into generated-block marker files.

Build-time mechanism that propagates :data:`yoke_contracts.user_writing_rules.RULES`
into every markdown surface that teaches an agent how to write to its user:
the project rules file and the user-level ``yoke-global`` skill, which serves
sessions outside every project. Drift is structurally impossible: the
:data:`INVENTORY` tuple is the contract, and ``--check`` mode runs in the
CI contract. The marker mechanics live in
:mod:`yoke_core.tools.generated_block_render`.

Markers — content between is REPLACED on every run:

    <!-- BEGIN GENERATED: user-writing -->
    <!-- END GENERATED: user-writing -->

CLI: ``python3 -m yoke_core.tools.render_user_writing_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence

from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_contracts.user_writing_rules import RULES
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

SLUG: str = "user-writing"
BEGIN_MARKER: str = begin_marker(SLUG)
END_MARKER: str = end_marker(SLUG)
REPAIR_COMMAND: str = "python3 -m yoke_core.tools.render_user_writing_inline"

# One entry per surface where an agent learns how to write to its user.
INVENTORY: tuple[str, ...] = (
    "AGENTS.md",
    "packages/yoke-contracts/src/yoke_contracts/global_skill/SKILL.md",
)


def _content_for_path(_rel_path: str) -> str:
    return RULES + "\n"


def render(
    target_root: pathlib.Path,
    *,
    check: bool = False,
) -> RenderResult:
    """Render the user-writing rules into every inventory file."""
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
        family_label="user-writing",
        repair_command=REPAIR_COMMAND,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_user_writing_inline",
        description=(
            "Render the user-writing rules into every generated-block "
            "marker file. Use --check in CI to fail on drift."
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
