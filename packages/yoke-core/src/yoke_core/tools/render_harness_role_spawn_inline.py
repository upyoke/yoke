"""Render each harness's role-agent spawn into the skills that dispatch roles.

A dispatching skill must show the exact invocation that starts a Yoke role
agent on every harness; naming a Python descriptor with no CLI behind it lets
a harness skip the installed agent. The invocations come from
:func:`yoke_core.domain.dispatch_descriptors.render_for_harness`; this family
renders them once into the shared role-spawn page that every dispatching
skill points to. The marker
mechanics live in :mod:`yoke_core.tools.generated_block_render`.

Markers — content between is REPLACED on every run::

    <!-- BEGIN GENERATED: harness-role-spawn -->
    <!-- END GENERATED: harness-role-spawn -->

CLI: ``python3 -m yoke_core.tools.render_harness_role_spawn_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence

from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_core.domain.dispatch_descriptors import (
    DispatchDescriptor,
    render_for_harness,
)
from yoke_core.domain.harness_capability_registry import HARNESS_UNIVERSE
from yoke_core.tools.generated_block_render import (
    RenderResult,
    format_drift_summary,
    render_blocks,
)

__all__ = (
    "INVENTORY",
    "ROLE_PLACEHOLDER",
    "build_block",
    "format_drift_summary_for_family",
    "render",
)

SLUG: str = "harness-role-spawn"
CANONICAL_NAME: str = "yoke_core.domain.dispatch_descriptors.render_for_harness"
REPAIR_COMMAND: str = "python3 -m yoke_core.tools.render_harness_role_spawn_inline"

#: The one surface every dispatching skill points to for the spawn form.
INVENTORY: tuple[str, ...] = (".agents/skills/yoke/shared/role-spawn.md",)
ROLE_PLACEHOLDER: str = "yoke-<role>"


def build_block() -> str:
    """Return each harness's role-agent invocation with a role placeholder."""
    # Any valid role renders the shape; its agent name becomes the placeholder.
    descriptor = DispatchDescriptor("engineer")
    lines = [f"Source: `{CANONICAL_NAME}`.", ""]
    for harness_id in HARNESS_UNIVERSE:
        rendered = render_for_harness(descriptor, harness_id).splitlines()
        snippet = " ".join(line.strip() for line in rendered)
        snippet = snippet.replace(descriptor.subagent_type, ROLE_PLACEHOLDER)
        lines.append(f"- `{harness_id}`: `{snippet}`")
    return "\n".join(lines) + "\n"


def _content_for_path(_rel_path: str) -> str:
    return build_block()


def render(target_root: pathlib.Path, *, check: bool = False) -> RenderResult:
    """Render the spawn list into every dispatching surface."""
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
        family_label="harness role spawn",
        repair_command=REPAIR_COMMAND,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_harness_role_spawn_inline",
        description=(
            "Render each harness's role-agent spawn into every dispatching "
            "skill surface. Use --check in CI / pre-commit to fail on drift."
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
    if not result.ok or (args.check and result.changed):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
