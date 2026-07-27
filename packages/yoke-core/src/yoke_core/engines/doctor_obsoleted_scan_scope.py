"""Repository scan roots for the obsoleted-term health check."""

from __future__ import annotations

# Scan operator-facing prose plus live runtime Python, so stale retired
# hook/module references in doctor code cannot reach main unnoticed.
# JSON/TOML/YAML stay out of scope by design because they are generated
# from Python/TypeScript inputs.
SCAN_DIRS_BY_EXT: dict[str, tuple[str, ...]] = {
    ".md": (
        "docs",
        ".agents",
        ".claude",
        "packs",
        "projects",
        ".yoke/strategy",
    ),
    ".py": (
        "packages",
        "runtime",
    ),
}

SCAN_ROOT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
)


def needs_slash_normalization(pattern_src: str) -> bool:
    """Return whether a dotted module pattern should also scan slash paths."""
    return pattern_src.startswith((r"runtime\.", r"yoke_"))


__all__ = ["SCAN_DIRS_BY_EXT", "SCAN_ROOT_FILES", "needs_slash_normalization"]
