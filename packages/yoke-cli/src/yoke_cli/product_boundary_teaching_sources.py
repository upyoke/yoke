"""Source selection and generated help recipes for teaching audits."""

from __future__ import annotations

from typing import Sequence, Tuple


TEACHING_GLOBS: Tuple[str, ...] = (
    ".agents/skills/yoke/**/*.md",
    "runtime/agents/*.md",
    "runtime/harness/claude/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
    "packages/yoke-core/src/yoke_core/domain/schema_api_context*.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc*.py",
    "runtime/api/domain/lint_*.py",
    "AGENTS.md",
    "CODEX.md",
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
    return any(
        any(marker in token for marker in metacharacters)
        for token in argv[:3]
    )


__all__ = ["TEACHING_GLOBS", "command_path_is_template", "help_usage_recipes"]
