"""Internal constants for the stale-string audit gate.

Underscore-prefixed because this is not the public surface — callers
import these names from ``yoke_core.domain.stale_string_audit``,
which re-exports them. Owned here so sibling modules can import without
forming a cycle through the public entry-point.
"""

from __future__ import annotations


# Fallback test directories when project config has nothing.
DEFAULT_TEST_DIRS = ["e2e/", "__tests__/", "test/", "src/test/", "tests/"]

# File extensions to include in grep — covers spec, helper, fixture, mock.
TEST_FILE_GLOBS = ["*.ts", "*.tsx", "*.js", "*.jsx", "*.py"]

# Directories to always exclude from grep.
EXCLUDE_DIRS = [
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "__pycache__",
    ".worktrees",
    ".playwright-cache",
]

TEXT_SENSITIVE_KEYWORDS = (
    "theme",
    "copy",
    "button label",
    "button labels",
    "heading",
    "title text",
    "ui text",
    "user-visible",
    "text-sensitive",
    "error message",
    "empty state",
    "route-specific page wording",
)

FILE_LIKE_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".css",
    ".html",
)

GENERIC_QUOTED_STRINGS = {
    "defaults",
    "default",
    "unknown",
    "invalid",
    "warning",
    "pass",
    "fail",
    "none",
    "none configured",
}
