"""Retained command-shaped surface registry.

Holds the canonical list of intentionally command-shaped boundaries
that skill prose, agent prompts, packets, and lint denial messages may
reference without tripping the "function-call surface first" doctrine.

Live consumers: ``doctor_hc_tier_cli_shape_bleed`` and its tests, plus
``test_ticket_creation_teaching``. The wider Atlas surface inventory
lives in ``yoke_core.tools.atlas_*`` and is driven from the operation
tracker + subcommand registry directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class RetainedBoundary:
    """One intentionally command-shaped surface."""

    surface: str
    category: str
    owner: str
    rationale: str
    allowed_path_globs: Tuple[str, ...]


# AGENTS.md ``## Code Conventions`` allowlist: project test commands,
# grep/discovery, git inspection, package managers, and harness boundary
# launchers. External tooling (gh, browser engines) sits in its own bucket.
RETAINED_TERMINAL_BOUNDARIES: Tuple[RetainedBoundary, ...] = (
    RetainedBoundary(
        surface="git porcelain (status/diff/log/show)",
        category="git_porcelain",
        owner="Yoke agent harness",
        rationale="Read-only git inspection is a substrate primitive; Yoke wraps it for telemetry, not authority.",
        allowed_path_globs=("**/*",),
    ),
    RetainedBoundary(
        surface="ripgrep / grep / find",
        category="external_tooling",
        owner="Yoke agent harness",
        rationale="Discovery only; Yoke owns no read-side substitute for whole-tree text search.",
        allowed_path_globs=("**/*",),
    ),
    RetainedBoundary(
        surface="project test commands (pytest, npm test, etc.)",
        category="project_test",
        owner="Project Structure command_definitions family",
        rationale="Per-project test invocations are operator-configurable; Yoke reads from project_structure rather than embedding a runner.",
        allowed_path_globs=(
            "packages/yoke-core/src/yoke_core/domain/command_definitions.py",
        ),
    ),
    RetainedBoundary(
        surface="package managers (pip, npm, brew, uv)",
        category="package_manager",
        owner="Operator/devbox",
        rationale="Outside Yoke's control plane; install workflows remain operator-driven.",
        allowed_path_globs=("**/*",),
    ),
    RetainedBoundary(
        surface="python3 -m yoke_core.cli.db_router (read-only paths)",
        category="operator_debug",
        owner="yoke_core.cli.db_router",
        rationale="Operator/debug adapter over the function registry. Machine callers prefer the typed function call; humans keep CLI ergonomics.",
        allowed_path_globs=("runtime/api/cli/db_router.py",),
    ),
    RetainedBoundary(
        surface="docs/archive/** historical recipes",
        category="archive_only",
        owner="docs/archive",
        rationale="Decision records and retired-design prose may legitimately quote pre-API terminal recipes as historical context.",
        allowed_path_globs=("docs/archive/**",),
    ),
    RetainedBoundary(
        surface="runtime/api/**/test_*.py fixtures",
        category="test_only",
        owner="Yoke test suite",
        rationale="Negative-example fixtures, parity matrices, and lint tests legitimately embed legacy recipe strings.",
        allowed_path_globs=("runtime/api/**/test_*.py",),
    ),
)


__all__ = [
    "RetainedBoundary",
    "RETAINED_TERMINAL_BOUNDARIES",
]
