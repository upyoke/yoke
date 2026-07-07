"""Project-local Yoke install rendering and drift checks.

The normal substrate renderer owns files inside the Yoke source checkout
(``runtime/harness/...``). Project repos such as Buzz receive an installed
layer instead: ``.claude/``, ``.codex/``, and ``.agents/skills/yoke``.
This module compares and writes that installed shape from the current Yoke
source tree.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.agents_render_claude import render_claude_settings_json
from yoke_core.domain.agents_render_codex import (
    render_codex_agent,
    render_codex_hooks_json,
)
from yoke_core.domain.agents_render_subagent_hooks import (
    CANONICAL_DIR,
    render_claude_agent,
)
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


_CLAUDE_SKILL_LINK = Path(".claude") / "skills" / "yoke"
_CODEX_SKILL_LINK = Path(".codex") / "skills" / "yoke"
_SKILL_LINK_TARGET = "../../.agents/skills/yoke"


def is_project_install_root(target_root: Path) -> bool:
    """True when *target_root* looks like a project-local install target."""
    root = Path(target_root)
    if (root / CANONICAL_DIR).exists():
        return False
    return any((root / p).exists() for p in (".claude", ".codex", ".agents"))


def detect_project_install_drift(
    *,
    target_root: Path,
    source_root: Path | None = None,
) -> list[str]:
    """Compare a project-local installed layer against current Yoke source."""
    root = Path(target_root)
    drift: list[str] = []
    for rel_path, rendered in _project_install_outputs(source_root):
        out_path = root / rel_path
        if not out_path.exists():
            drift.append(f"missing: {rel_path}")
            continue
        if out_path.read_text(encoding="utf-8") != rendered:
            drift.append(f"drift: {rel_path}")
    for link_path in (_CLAUDE_SKILL_LINK, _CODEX_SKILL_LINK):
        full = root / link_path
        if not full.is_symlink():
            drift.append(f"missing: {link_path}")
        elif full.readlink().as_posix() != _SKILL_LINK_TARGET:
            drift.append(f"drift: {link_path}")
    return drift


def write_project_install(
    *,
    target_root: Path,
    dry_run: bool = False,
    source_root: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """Write the project-local installed layer into *target_root*."""
    root = Path(target_root)
    results: dict[str, tuple[str, str]] = {}
    for rel_path, rendered in _project_install_outputs(source_root):
        out_path = root / rel_path
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        action = "skip" if existing == rendered else "would-write" if dry_run else "write"
        if action == "write":
            assert_target_under_session_work_authority(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding="utf-8")
        results[str(rel_path)] = (action, rendered)
    for link_path in (_CLAUDE_SKILL_LINK, _CODEX_SKILL_LINK):
        action = _ensure_skill_link(root / link_path, dry_run=dry_run)
        results[str(link_path)] = (action, _SKILL_LINK_TARGET)
    return results


def write_if_applicable(
    *,
    target_root: Path,
    dry_run: bool = False,
) -> dict[str, tuple[str, str]] | None:
    """Return project-install write results when *target_root* is that layout."""
    root = Path(target_root)
    if not is_project_install_root(root):
        return None
    return write_project_install(target_root=root, dry_run=dry_run)


def drift_if_applicable(*, target_root: Path) -> list[str] | None:
    """Return project-install drift when *target_root* is that layout."""
    root = Path(target_root)
    if not is_project_install_root(root):
        return None
    return detect_project_install_drift(target_root=root)


def _project_install_outputs(
    source_root: Path | None,
) -> list[tuple[Path, str]]:
    root = Path(source_root) if source_root is not None else _source_root_from_module()
    outputs: list[tuple[Path, str]] = []
    for agent in _agents():
        outputs.append(
            (
                Path(".claude") / "agents" / f"yoke-{agent}.md",
                render_claude_agent(agent, target_root=root),
            )
        )
    outputs.extend(_copied_tree_outputs(
        root / "runtime" / "harness" / "claude" / "agents" / "references",
        Path(".claude") / "agents" / "references",
    ))
    outputs.append((Path(".claude") / "settings.json", render_claude_settings_json()))
    outputs.extend(_copied_tree_outputs(
        root / "runtime" / "harness" / "claude" / "rules",
        Path(".claude") / "rules",
    ))
    for agent in _agents():
        outputs.append(
            (
                Path(".codex") / "agents" / f"yoke-{agent}.toml",
                render_codex_agent(root / CANONICAL_DIR, agent),
            )
        )
    outputs.append((Path(".codex") / "hooks.json", render_codex_hooks_json()))
    outputs.extend(_copied_tree_outputs(
        root / ".agents" / "skills" / "yoke",
        Path(".agents") / "skills" / "yoke",
    ))
    return outputs


def _copied_tree_outputs(source_dir: Path, target_dir: Path) -> list[tuple[Path, str]]:
    outputs: list[tuple[Path, str]] = []
    if not source_dir.is_dir():
        return outputs
    for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
        outputs.append((
            target_dir / path.relative_to(source_dir),
            path.read_text(encoding="utf-8"),
        ))
    return outputs


def _ensure_skill_link(link_path: Path, *, dry_run: bool) -> str:
    if link_path.is_symlink() and link_path.readlink().as_posix() == _SKILL_LINK_TARGET:
        return "skip"
    if dry_run:
        return "would-write"
    assert_target_under_session_work_authority(link_path)
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(_SKILL_LINK_TARGET)
    return "write"


def _source_root_from_module() -> Path:
    path = Path(__file__).resolve()
    for candidate in (path, *path.parents):
        if (candidate / CANONICAL_DIR).is_dir():
            return candidate
    raise RuntimeError("Cannot find Yoke source root for project install render")


def _agents() -> list[str]:
    from yoke_core.domain.agents_render import AGENTS

    return list(AGENTS)


__all__ = [
    "detect_project_install_drift",
    "drift_if_applicable",
    "is_project_install_root",
    "write_if_applicable",
    "write_project_install",
]
