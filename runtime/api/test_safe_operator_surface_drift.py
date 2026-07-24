"""Drift lock: the typed safe-operator-surface registry vs. the docs.

The 19-command Tier 1 operator surface is enumerated in three markdown
locations (docs/harness-bootstrap.md, .yoke/docs/commands.md, the help SKILL.md),
plus the per-harness compat statement in CODEX.md. The typed source of truth
is :data:`yoke_core.domain.harness_capability_registry.SAFE_OPERATOR_SURFACE`.

These tests catch the drift class that produced the "Codex first slice"
tension: the docs and the typed registry growing apart over time. Each
markdown surface MUST mention every entrypoint declared in the registry, and
CODEX.md MUST name every registry entry that is missing the ``"codex"`` value
in its ``harness_support`` tuple. The Codex-incompatible set may legitimately
be empty (every safe-surface command supports both harnesses); the drift lock
only fires when an incompatible entry exists and CODEX.md fails to name it.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.harness_capability_registry import (
    safe_operator_surface,
    safe_operator_surface_for_harness,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()
DOCS = REPO / "docs"
# Universal docs shipped to managed projects now live under .yoke/docs.
YOKE_DOCS = REPO / ".yoke" / "docs"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def test_harness_bootstrap_lists_full_safe_surface():
    text = _read(DOCS / "harness-bootstrap.md")
    for command in safe_operator_surface():
        assert command.entrypoint in text, (
            f"docs/harness-bootstrap.md missing safe-surface entrypoint "
            f"{command.entrypoint!r}"
        )


def test_commands_md_lists_full_safe_surface():
    text = _read(YOKE_DOCS / "commands.md")
    for command in safe_operator_surface():
        assert command.entrypoint in text, (
            f".yoke/docs/commands.md missing safe-surface entrypoint "
            f"{command.entrypoint!r}"
        )


def test_help_skill_lists_full_safe_surface():
    text = _read(REPO / ".agents" / "skills" / "yoke" / "help" / "SKILL.md")
    for command in safe_operator_surface():
        assert command.entrypoint in text, (
            f"help/SKILL.md missing safe-surface entrypoint "
            f"{command.entrypoint!r}"
        )


def test_board_art_terminal_helper_is_listed_in_human_help_surfaces():
    helper = "yoke board art variant create"
    surfaces = (
        REPO / ".agents" / "skills" / "yoke" / "SKILL.md",
        REPO / ".agents" / "skills" / "yoke" / "help" / "SKILL.md",
        YOKE_DOCS / "commands.md",
    )
    for path in surfaces:
        text = _read(path)
        assert helper in text, f"{path} missing local terminal helper {helper!r}"


def test_codex_md_names_codex_incompatible_commands():
    text = _read(REPO / "CODEX.md")
    codex_compatible = {
        c.entrypoint for c in safe_operator_surface_for_harness("codex")
    }
    all_safe = {c.entrypoint for c in safe_operator_surface()}
    codex_incompatible = all_safe - codex_compatible
    # Empty set is the steady state when every safe-surface command supports
    # both harnesses; the drift lock only fires when a row is missing "codex"
    # AND CODEX.md fails to name it.
    for entrypoint in codex_incompatible:
        assert entrypoint in text, (
            f"CODEX.md must name Codex-incompatible {entrypoint!r} "
            f"so operators know it is not supported"
        )
