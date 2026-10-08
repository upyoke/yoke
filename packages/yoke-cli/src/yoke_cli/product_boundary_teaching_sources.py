"""Source selection and generated help recipes for teaching audits."""

from __future__ import annotations

from typing import Sequence, Tuple


# Every place a reader is taught a command. The packaged snapshot under
# ``install_bundle_tree`` is deliberately absent: the bundle sync derives
# it byte-for-byte from these same sources and a drift test enforces the
# equality, so scanning it would only duplicate each finding.
TEACHING_GLOBS: Tuple[str, ...] = (
    ".agents/skills/yoke/**/*.md",
    "runtime/agents/*.md",
    "runtime/harness/*/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
    "runtime/harness/*/rules/*.md",
    "packages/yoke-core/src/yoke_core/domain/schema_api_context*.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc*.py",
    "runtime/api/domain/lint_*.py",
    "AGENTS.md",
    "docs/public/guides/codex-harness.md",
    "docs/public/guides/cursor-harness.md",
    ".yoke/docs/**/*.md",
    "docs/**/*.md",
)


def help_usage_recipes() -> tuple[str, ...]:
    """Return the deduplicated usage lines rendered by live CLI help."""
    from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_USAGE

    return tuple(sorted(set(ADAPTER_USAGE.values()) | set(TOOL_SHAPED_USAGE.values())))


def command_path_is_template(argv: Sequence[str]) -> bool:
    """Recognize namespace examples that intentionally contain metavariables."""
    metacharacters = ("<", "{", "|", "*", "…")
    return any(any(marker in token for marker in metacharacters) for token in argv[:3])


__all__ = ["TEACHING_GLOBS", "command_path_is_template", "help_usage_recipes"]
