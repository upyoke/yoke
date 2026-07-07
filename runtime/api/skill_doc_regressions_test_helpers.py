"""Shared path constants and doc-bundle readers for ``test_skill_doc_regressions*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the path constants (``REPO``, ``SKILLS``, ``AGENTS``) and the
``_read*`` helpers, then defines its own ``@pytest.fixture`` shims as needed.
This keeps fixtures local to their consumer files (so future moves do not pull
surprise dependencies) while sharing the repo-root resolver and the dispatch /
refine / polish doc bundle assemblers.
"""

from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    """Return the Yoke repo root (either the main checkout or a worktree)."""
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()
SKILLS = REPO / ".agents" / "skills" / "yoke"
AGENTS = REPO / ".claude" / "agents"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def _read_bundle(*paths: Path) -> str:
    return "\n\n".join(_read(path) for path in paths)


def _read_dispatch_context(path: Path) -> str:
    conduct_dir = path.parent
    return _read_bundle(
        path,
        conduct_dir / "dispatch-context-project.md",
        conduct_dir / "dispatch-context-rehydrate.md",
        conduct_dir / "dispatch-context-dispatch.md",
        conduct_dir / "dispatch-context-artifacts.md",
        conduct_dir / "dispatch-context-gates.md",
        conduct_dir / "dispatch-context-ephemeral.md",
        conduct_dir / "dispatch-context-prompts.md",
        conduct_dir / "dispatch-context-prompts-minimal.md",
        conduct_dir / "dispatch-context-verify.md",
    )


def _read_refine_skill(path: Path) -> str:
    return _read_bundle(path, path.parent / "update-protocol.md")


def _read_polish_skill(path: Path) -> str:
    phases = ("parse-and-claim.md", "context.md", "review.md", "fixes.md", "verify-and-commit.md", "advance.md")
    return _read_bundle(path, *(path.parent / phase for phase in phases))


def _count_invocations(text: str, module_name: str) -> tuple[int, int]:
    """Return (total_invocations, unscoped_invocations) for a Python-owner module.

    An invocation is a line that actually *runs* the module (``python3 -m
    yoke_core.domain.<module>`` or ``if python3 -m yoke_core.domain.<module>``)
    at the start of the line, optionally preceded by whitespace. A prose mention
    where the module name appears inside a code span or descriptive sentence does
    not count. An invocation is "unscoped" if it lacks the ``--gate-point`` flag.
    Accepts the dotted module name (e.g. ``check_hard_blocks``).
    """
    total = 0
    unscoped = 0
    pattern = re.compile(
        rf"^\s*(?:if\s+)?python3\s+-m\s+yoke\.api\.domain\.{re.escape(module_name)}\b"
    )
    for line in text.splitlines():
        if pattern.search(line):
            total += 1
            if "--gate-point" not in line:
                unscoped += 1
    return total, unscoped


__all__ = [
    "REPO",
    "SKILLS",
    "AGENTS",
    "Path",
    "_read",
    "_read_bundle",
    "_read_dispatch_context",
    "_read_refine_skill",
    "_read_polish_skill",
    "_count_invocations",
]
