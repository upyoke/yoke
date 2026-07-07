"""Client-safe project contract install policy constants."""

from __future__ import annotations

# Per-entry install policy: write only when the file is absent; never
# overwrite on refresh. The only policy this CLI generation understands.
SEED_IF_MISSING = "seed_if_missing"

# Generated/machine-state names inside .yoke/ that must never track.
# Rendered into the seeded `.yoke/.gitignore` so ignore policy for the
# contract tree rides the tree itself.
YOKE_TREE_IGNORED_NAMES = (
    "BOARD.md",
    "BOARD.md.ts",
    "BOARD.md.lock/",
    "BOARD.md.board.*",
    "BOARD.md.reg_*",
    "backups/",
    "strategy/",
    ".github-retry.log",
    ".merge-lock",
    "install-manifest.json",
)

# Surfaces a bundle must never name as contract files: generated board
# views, the retired static art example, runtime/state directories,
# machine-level config, and rendered strategy views.
FORBIDDEN_CONTRACT_RELATIVE_PATHS = (
    ".yoke/BOARD.md",
    ".yoke/BOARD.md.ts",
    ".yoke/board-art.example",
    ".yoke/install.json",
    ".yoke/generated",
    ".yoke/qa-artifacts",
    ".yoke/scratch",
    ".yoke/sessions",
    ".yoke/backups",
    ".yoke/strategy",
    ".codex/config.toml",
)

__all__ = [
    "FORBIDDEN_CONTRACT_RELATIVE_PATHS",
    "SEED_IF_MISSING",
    "YOKE_TREE_IGNORED_NAMES",
]
