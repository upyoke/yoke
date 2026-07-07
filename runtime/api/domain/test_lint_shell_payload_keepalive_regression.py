"""Forward-guard against /yoke do keepalive reintroduction.

The background keepalive loop and its shell-PID kill pattern were
removed by the keepalive-elimination change. This test ensures no future
PR reintroduces the shape — neither the ``--keepalive`` CLI mode on
``service-client session-heartbeat`` nor the ``YOKE_HEARTBEAT_PID=$!`` /
``kill <YOKE_HEARTBEAT_PID>`` choreography in skill prose.

The regression file replaces the prior coverage that asserted the
keepalive lint shape **passed** the shell-payload lint. With the
shape eliminated, the new coverage asserts the absence of every live
mention of the eliminated surface.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]

# Mention patterns the rule refuses to see in live source. Each pattern
# is searched line-by-line so a single offending line is reported with
# its file path.
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("keepalive_cli_flag", r"--keepalive\b"),
    ("keepalive_env", r"YOKE_HEARTBEAT_PID"),
    ("keepalive_function", r"run_keepalive\b"),
    ("keepalive_module", r"service_client_sessions_keepalive\b"),
)


# Directories and files that are not "live source" for this rule:
# build artifacts, vendored deps, virtualenvs, the linked-worktree
# subtrees (production claims live at the main checkout), and this
# regression file itself (it must mention the pattern in prose).
_SKIP_DIR_NAMES = {
    ".git",
    ".worktrees",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".yoke",
    "validation",
    "data",
}

_SCAN_EXTENSIONS = {".py", ".md", ".sh", ".json", ".toml", ".yml", ".yaml"}


def _iter_live_files():
    """Yield repo-tree files this guard treats as "live source".

    Test files are excluded — assertions of absence (e.g.,
    ``assert "--keepalive" not in text``) are legitimate and must not
    trip the guard. The guard's purpose is to catch source-code
    reintroduction, not to police assertions.
    """
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for filename in filenames:
            if not any(filename.endswith(ext) for ext in _SCAN_EXTENSIONS):
                continue
            if filename.startswith("test_") or filename.endswith("_test.py"):
                continue
            full = Path(dirpath) / filename
            if full.resolve() == Path(__file__).resolve():
                continue
            yield full


@pytest.mark.parametrize("pattern_name,pattern", _FORBIDDEN_PATTERNS)
def test_no_live_mention_of_keepalive_pattern(pattern_name: str, pattern: str):
    regex = re.compile(pattern)
    offenders: list[str] = []
    for path in _iter_live_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()[:200]}")
    assert not offenders, (
        f"Forbidden /yoke do keepalive pattern '{pattern_name}' "
        "reintroduced in live source. Each occurrence below must be "
        "removed — the background keepalive loop and PID-kill pattern "
        "were eliminated:\n  " + "\n  ".join(offenders[:50])
    )


def test_service_client_sessions_keepalive_module_deleted():
    """The whole keepalive module was deleted by FR-1(c)."""
    candidate = (
        _REPO_ROOT
        / "runtime"
        / "api"
        / "service_client_sessions_keepalive.py"
    )
    assert not candidate.exists(), (
        f"{candidate} must remain deleted (FR-1(c))."
    )


def test_session_heartbeat_no_longer_accepts_keepalive():
    """``service-client session-heartbeat --keepalive`` exits non-zero.

    The argument was removed from the parser by FR-1(c); argparse
    refuses the unknown flag.
    """
    from yoke_core.api.service_client_sessions_lifecycle_touch import (
        cmd_session_heartbeat,
    )

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = cmd_session_heartbeat(["--keepalive", "--interval", "60"])
    assert rc != 0
