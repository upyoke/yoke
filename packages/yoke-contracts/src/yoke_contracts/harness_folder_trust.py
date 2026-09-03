"""Where each harness records that a folder is trusted to work in.

Approval posture and folder trust are different gates, and a machine that has
one still stops on the other: a Codex session with ``approval_policy =
"never"`` still asks about the directory before it asks about anything in it.
So Yoke answers both, for every checkout it registers and every lane it
creates.

Grounded against the builds this repository supports:

* ``codex`` — ``$CODEX_HOME/config.toml``: ``[projects."<path>"]
  trust_level = "trusted"``.
* ``claude-code`` — ``~/.claude.json``: ``projects.<path>
  .hasTrustDialogAccepted = true``.
* ``cursor`` — ``~/.cursor/projects/<slug>/.workspace-trusted``, a small JSON
  file naming the path and when it was trusted. The slug is the absolute
  path with dots dropped and every run of non-alphanumerics collapsed to a
  dash; :func:`cursor_project_slug` reproduces it, verified against the
  entries Cursor itself wrote on a machine that had visited each path.

Trust is path-keyed in all three, with no evidence any of them treats a
parent's entry as covering a subdirectory — the same shape Codex hook trust
already has, which is why Yoke mirrors that per lane too. So a linked
worktree gets its own entry rather than inheriting the checkout's.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_contracts.harness_unattended_posture import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
)

#: Claude records folder trust in its CLI state file, keyed by absolute path.
CLAUDE_STATE_PATH = "~/.claude.json"
CLAUDE_PROJECTS_KEY = "projects"
CLAUDE_TRUST_KEY = "hasTrustDialogAccepted"

#: Cursor keeps one directory of state per workspace it has opened.
CURSOR_PROJECTS_ROOT = "~/.cursor/projects"
CURSOR_TRUST_FILENAME = ".workspace-trusted"

#: Codex's trust table lives in the same config file as its approval posture,
#: so the key names are re-exported from there rather than restated.
TRUSTED_HARNESSES = (CLAUDE_FAMILY, CODEX_FAMILY, CURSOR_FAMILY)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def claude_state_path() -> Path:
    """Resolve the Claude CLI state file this machine records trust in."""
    return Path(CLAUDE_STATE_PATH).expanduser()


def cursor_projects_root() -> Path:
    """Resolve the directory Cursor keeps its per-workspace state under."""
    return Path(CURSOR_PROJECTS_ROOT).expanduser()


def cursor_project_slug(checkout: str | Path) -> str:
    """Return the directory name Cursor uses for one workspace path."""
    absolute = str(Path(checkout).expanduser())
    return _NON_ALNUM.sub("-", absolute.lstrip("/").replace(".", "")).strip("-")


def cursor_trust_file(checkout: str | Path) -> Path:
    """Return the file whose presence marks one workspace trusted."""
    return cursor_projects_root() / cursor_project_slug(checkout) / (
        CURSOR_TRUST_FILENAME
    )


def trust_key(checkout: str | Path) -> str:
    """Return the absolute path every harness keys folder trust by."""
    return str(Path(checkout).expanduser())


__all__ = [
    "CLAUDE_PROJECTS_KEY",
    "CLAUDE_STATE_PATH",
    "CLAUDE_TRUST_KEY",
    "CURSOR_PROJECTS_ROOT",
    "CURSOR_TRUST_FILENAME",
    "TRUSTED_HARNESSES",
    "claude_state_path",
    "cursor_project_slug",
    "cursor_projects_root",
    "cursor_trust_file",
    "trust_key",
]
