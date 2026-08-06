"""Project install-bundle rendering — server side of ``yoke install``.

``GET /v1/projects/{project_id}/install-bundle`` serves :func:`build_bundle`:
the project-local product layer a Yoke-managed repo needs, rendered
deterministically from the server's OWN code tree plus the ``projects`` row.
The bundle carries:

* **Skills** — the full Yoke skill tree copied verbatim from
  ``.agents/skills/yoke/`` into that same canonical project path plus both
  harness discovery dirs (``.claude/skills/yoke/<rel>`` and
  ``.codex/skills/yoke/<rel>``). Skill-to-skill references therefore resolve
  identically in the Yoke source repo and every installed managed project.
* **Agent adapters** — the rendered subagent bodies the lifecycle dispatch
  needs: ``.claude/agents/yoke-*.md`` (plus the ``references/`` tree) and
  ``.codex/agents/yoke-*.toml`` plus ``.cursor/agents/yoke-*.md``, copied
  from the server tree's committed ``runtime/harness/<harness>/agents/``
  adapters.
* **Session rules** — the shared Claude session rules
  (``.claude/rules/`` from ``runtime/harness/claude/rules``) that the
  lifecycle skills assume are installed.
* **Hooks** — the exact ``hooks`` subtrees a project's ``.claude/settings.json``,
  ``.codex/hooks.json``, and ``.cursor/hooks.json`` need, rendered from the
  canonical hook chain that the committed harness settings files also use
  (``yoke hook evaluate``).
* **Project contract files** — the seed-if-missing ``.yoke`` contract
  (``project_contract_files``), rendered by
  :mod:`yoke_core.domain.project_contract`. Shipped separately from ``files``
  because contract files are project-owned the moment they are seeded.

Determinism: files are sorted by bundle path and no timestamps are embedded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_contracts.engine_version import (
    UNRESOLVED_SCM_FALLBACK_VERSION,
    installed_engine_version,
)
from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_contracts.packs import PACKS_SOURCE

# Server-tree source dirs (relative to the tree root).
SKILLS_SOURCE = ".agents/skills/yoke"
CLAUDE_AGENTS_SOURCE = "runtime/harness/claude/agents"
CODEX_AGENTS_SOURCE = "runtime/harness/codex/agents"
CURSOR_AGENTS_SOURCE = "runtime/harness/cursor/agents"
CLAUDE_RULES_SOURCE = "runtime/harness/claude/rules"
DOCS_SOURCE = ".yoke/docs"
# Pack source uses the same :func:`server_tree_root` resolver, so product
# wheels package it alongside the install-bundle sources.

# Repo-root source dirs the packaged install-bundle tree snapshots — the one
# truth shared by the snapshot materializer (:mod:`install_bundle_tree_sync`),
# its drift check (``HC-install-bundle-drift``), and the bundle invariant
# tests. Order matches the ``pyproject.toml`` package-data globs.
INSTALL_BUNDLE_SOURCE_DIRS = (
    SKILLS_SOURCE,
    CLAUDE_AGENTS_SOURCE,
    CLAUDE_RULES_SOURCE,
    CODEX_AGENTS_SOURCE,
    CURSOR_AGENTS_SOURCE,
    PACKS_SOURCE,
    DOCS_SOURCE,
)

# Machine-generated cache droppings excluded from every bundle enumeration.
# Pack sources include importable Python, so any test or tool that imports
# them compiles __pycache__ bytecode next to the sources; those artifacts
# must never ship in bundles, the packaged snapshot, or drift comparisons.
_JUNK_DIR_NAMES = frozenset({"__pycache__"})
_JUNK_FILE_NAMES = frozenset({".DS_Store"})
_JUNK_FILE_SUFFIXES = (".pyc", ".pyo")


def is_bundle_junk_path(path: Path) -> bool:
    """True for cache/junk artifacts every bundle surface must skip."""

    if any(part in _JUNK_DIR_NAMES for part in path.parts):
        return True
    if path.name in _JUNK_FILE_NAMES:
        return True
    return path.name.endswith(_JUNK_FILE_SUFFIXES)


# Project-repo destination dirs.
CANONICAL_SKILLS_DEST = SKILLS_SOURCE
CLAUDE_SKILLS_DEST = ".claude/skills/yoke"
CODEX_SKILLS_DEST = ".codex/skills/yoke"
CLAUDE_AGENTS_DEST = ".claude/agents"
CODEX_AGENTS_DEST = ".codex/agents"
CURSOR_AGENTS_DEST = ".cursor/agents"
CLAUDE_RULES_DEST = ".claude/rules"


class InstallBundleError(RuntimeError):
    """The install bundle cannot be rendered; message names the repair."""


class ProjectNotFoundError(InstallBundleError):
    """The requested project id has no ``projects`` row."""


def yoke_version() -> str:
    """Installed engine version, or the shared unresolved-source fallback."""
    return installed_engine_version() or UNRESOLVED_SCM_FALLBACK_VERSION


def server_tree_root() -> Path:
    """Root of the install-bundle source tree.

    ``YOKE_SERVER_TREE_ROOT`` wins when set — containers COPY the repo-root bundle sources
    (``packs/``, ``.agents/``, rendered agent adapters) to a declared
    tree and point this env var at it. Set-but-invalid fails loudly rather
    than silently falling back to a site-packages parent that lacks the
    sources.

    Source checkouts resolve from the root ``runtime`` package location,
    never from cwd — the API process may run anywhere. Product wheels do
    not ship that root package, so local mode falls back to the packaged
    bundle-source tree inside ``yoke_core``.
    """
    import os

    declared = os.environ.get("YOKE_SERVER_TREE_ROOT", "").strip()
    if declared:
        root = Path(declared)
        if not root.is_dir():
            raise InstallBundleError(
                f"YOKE_SERVER_TREE_ROOT is set but is not a directory: {declared}"
            )
        return root
    try:
        import runtime

        return Path(runtime.__file__).resolve().parent.parent
    except ModuleNotFoundError:
        return _packaged_tree_root()


def _packaged_tree_root() -> Path:
    from importlib import resources

    root = resources.files("yoke_core.install_bundle_tree")
    try:
        path = Path(root)
    except TypeError as exc:
        raise InstallBundleError(
            "packaged install-bundle source tree is not filesystem-backed"
        ) from exc
    if not path.is_dir():
        raise InstallBundleError(
            f"packaged install-bundle source tree is missing: {path}"
        )
    return path


def _read_text(path: Path) -> Optional[str]:
    """Return the file's UTF-8 text, or ``None`` for non-text/binary files."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _skill_files(root: Path) -> List[Dict[str, str]]:
    """Emit the full skill tree under its canonical and discovery paths.

    Every file under ``.agents/skills/yoke/`` is emitted as a real file entry
    at the same canonical path and at both harness discovery paths. The three
    copies are byte-identical: the canonical copy makes absolute intra-skill
    references portable, while the harness copies make the root skill
    discoverable without relying on symlink support in installed projects.
    """
    source = root / SKILLS_SOURCE
    if not source.is_dir():
        raise InstallBundleError(
            f"skills source dir is missing from the server tree: {source}"
        )
    files: List[Dict[str, str]] = []
    for path in sorted(
        p for p in source.rglob("*") if p.is_file() and not is_bundle_junk_path(p)
    ):
        content = _read_text(path)
        if content is None:
            raise InstallBundleError(f"skill source is missing or non-text: {path}")
        rel = path.relative_to(source).as_posix()
        files.append({"path": f"{CANONICAL_SKILLS_DEST}/{rel}", "content": content})
        files.append({"path": f"{CLAUDE_SKILLS_DEST}/{rel}", "content": content})
        files.append({"path": f"{CODEX_SKILLS_DEST}/{rel}", "content": content})
    return files


def _agent_files(root: Path) -> List[Dict[str, str]]:
    """The rendered subagent adapters the lifecycle dispatch needs.

    Reads the server tree's committed adapters (kept in sync with the
    canonical agent bodies by ``yoke agents render`` + its drift HC) and
    emits ``.claude/agents/yoke-*.md`` (plus the ``references/`` tree) and
    ``.codex/agents/yoke-*.toml``, and ``.cursor/agents/yoke-*.md``.
    """
    files: List[Dict[str, str]] = []
    claude_dir = root / CLAUDE_AGENTS_SOURCE
    if not claude_dir.is_dir():
        raise InstallBundleError(
            f"claude agents source dir is missing from the server tree: {claude_dir}"
        )
    for path in sorted(claude_dir.glob("yoke-*.md")):
        files.append(_agent_entry(path, f"{CLAUDE_AGENTS_DEST}/{path.name}"))
    references = claude_dir / "references"
    if references.is_dir():
        for path in sorted(
            p
            for p in references.rglob("*")
            if p.is_file() and not is_bundle_junk_path(p)
        ):
            rel = path.relative_to(references).as_posix()
            files.append(_agent_entry(path, f"{CLAUDE_AGENTS_DEST}/references/{rel}"))
    codex_dir = root / CODEX_AGENTS_SOURCE
    if not codex_dir.is_dir():
        raise InstallBundleError(
            f"codex agents source dir is missing from the server tree: {codex_dir}"
        )
    for path in sorted(codex_dir.glob("yoke-*.toml")):
        files.append(_agent_entry(path, f"{CODEX_AGENTS_DEST}/{path.name}"))
    cursor_dir = root / CURSOR_AGENTS_SOURCE
    if not cursor_dir.is_dir():
        raise InstallBundleError(
            f"cursor agents source dir is missing from the server tree: {cursor_dir}"
        )
    for path in sorted(cursor_dir.glob("yoke-*.md")):
        files.append(_agent_entry(path, f"{CURSOR_AGENTS_DEST}/{path.name}"))
    return files


def _agent_entry(path: Path, dest: str) -> Dict[str, str]:
    content = _read_text(path)
    if content is None:
        raise InstallBundleError(f"agent adapter source is missing or non-text: {path}")
    return {"path": dest, "content": content}


def _rules_files(root: Path) -> List[Dict[str, str]]:
    """The shared Claude session rules a managed project needs.

    Copies the server tree's ``runtime/harness/claude/rules`` tree to
    ``.claude/rules`` — the harness session rules (worktree/commit/lint
    discipline etc.) that the lifecycle skills assume are present.
    """
    files: List[Dict[str, str]] = []
    source = root / CLAUDE_RULES_SOURCE
    if not source.is_dir():
        raise InstallBundleError(
            f"claude rules source dir is missing from the server tree: {source}"
        )
    for path in sorted(
        p for p in source.rglob("*") if p.is_file() and not is_bundle_junk_path(p)
    ):
        rel = path.relative_to(source).as_posix()
        files.append(_agent_entry(path, f"{CLAUDE_RULES_DEST}/{rel}"))
    return files


def _hooks_block() -> Dict[str, Any]:
    # Canonical owner: agents_render_hooks renders the committed
    # committed Claude, Codex, and Cursor hook files from the universal hook
    # ordering chains. Calling the renderer (instead of reading the committed
    # files) keeps the bundle drift-proof by construction.
    from yoke_core.domain.agents_render_hooks import (
        render_claude_hooks_block,
        render_codex_hooks_block,
        render_cursor_hooks_block,
    )

    return {
        "claude_settings_hooks": render_claude_hooks_block(),
        "codex_hooks": render_codex_hooks_block(),
        "cursor_hooks": render_cursor_hooks_block()["hooks"],
    }


def build_bundle(project_id: int, conn) -> Dict[str, Any]:
    """Render the deterministic project-bound install bundle."""
    from yoke_core.domain.install_bundle_project import build_project_bundle

    return build_project_bundle(project_id, conn)


__all__ = [
    "BUNDLE_SCHEMA",
    "INSTALL_BUNDLE_SOURCE_DIRS",
    "is_bundle_junk_path",
    "InstallBundleError",
    "ProjectNotFoundError",
    "build_bundle",
    "server_tree_root",
    "yoke_version",
]
