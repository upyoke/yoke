"""Install-bundle surfaces must not carry this repo's own specifics.

`.agents/skills/yoke`, the Claude harness rules, and the rendered agent
adapters are copied verbatim into every project Yoke installs into. Anything
in them that names this repo's paths or its work-item prefix teaches a target
project something false about itself, and the copy is silent — the drift only
shows up when an agent in that project runs a path that does not exist or
types an item ref with the wrong prefix.

Repo-specific teaching belongs in AGENTS.md below the managed-block marker,
which stays local to this repository.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain.agents_render_project_install import write_project_install

REPO = Path(__file__).resolve().parents[2]

# Mirrors install_bundle.INSTALL_BUNDLE_SOURCE_DIRS plus the canonical agent
# bodies those adapters render from — every tree copied into a target project.
SHIPPED_ROOTS = (
    REPO / ".agents" / "skills" / "yoke",
    REPO / ".yoke" / "docs",
    REPO / "runtime" / "agents",
    REPO / "runtime" / "harness" / "claude" / "rules",
    REPO / "runtime" / "harness" / "claude" / "agents",
    REPO / "runtime" / "harness" / "codex" / "agents",
    REPO / "runtime" / "harness" / "cursor" / "agents",
)
# Agent sidecar JSON carries the description shown in the agent-type listing,
# so it reaches a target project the same way the prose does.
SHIPPED_SUFFIXES = {".md", ".toml", ".json"}

REPO_LAYOUT_PATTERNS = (
    ("runtime/api/", re.compile(r"runtime/api/")),
    ("packages/yoke-", re.compile(r"packages/yoke-")),
    ("top-level tests/", re.compile(r"(?<![A-Za-z0-9_./-])tests/")),
    ("runtime.* package", re.compile(r"\bruntime\.[A-Za-z_][A-Za-z0-9_.]*")),
)
SOURCE_REPO_ONLY_LABEL = "yoke source repo only"
REPO_ITEM_PREFIX = "YOK-"
GENERIC_ITEM_PLACEHOLDER = "PREFIX-"


def _shipped_files():
    for root in SHIPPED_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in SHIPPED_SUFFIXES:
                yield path


def _offenders(token: str) -> list[str]:
    hits = []
    for path in _shipped_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if token in text:
            count = text.count(token)
            hits.append(f"{path.relative_to(REPO)} ({count})")
    return hits


def _repo_layout_offenders() -> list[str]:
    """Return unlabelled source-tree references in installed copy surfaces."""
    offenders = []
    for path in _shipped_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            if SOURCE_REPO_ONLY_LABEL in line.casefold():
                continue
            matched = [
                name for name, pattern in REPO_LAYOUT_PATTERNS
                if pattern.search(line)
            ]
            if matched:
                offenders.append(
                    f"{path.relative_to(REPO)}:{line_number} ({', '.join(matched)})"
                )
    return offenders


def test_shipped_surfaces_annotate_or_avoid_repo_layout_paths() -> None:
    """Installed instructions cannot assume this repository's source layout."""
    offenders = _repo_layout_offenders()
    assert offenders == [], (
        "unlabelled source-repo layout paths found in install-bundle surfaces: "
        f"{offenders}. Use portable module or command names, or label a "
        "necessary implementation detail 'Yoke source repo only'."
    )


def test_rendered_adapters_do_not_name_canonical_agent_sources() -> None:
    """Installed adapters must point to materialized references, never sources."""
    adapter_roots = (
        REPO / "runtime" / "harness" / "claude" / "agents",
        REPO / "runtime" / "harness" / "codex" / "agents",
        REPO / "runtime" / "harness" / "cursor" / "agents",
    )
    offenders = []
    for root in adapter_roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".toml"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "runtime/agents/" in text:
                    offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"rendered adapters name runtime/agents/: {offenders}"


def test_conditional_agent_reference_resolves_in_an_installed_project(
    tmp_path: Path,
) -> None:
    """A rendered agent's conditional reference is copied into its target path."""
    target = tmp_path / "project"
    target.mkdir()
    write_project_install(target_root=target)

    prompt = (target / ".claude" / "agents" / "yoke-engineer.md").read_text()
    reference = (
        target
        / ".claude"
        / "agents"
        / "references"
        / "engineer"
        / "migration-protocol.md"
    )
    assert ".claude/agents/references/engineer/migration-protocol.md" in prompt
    assert reference.is_file()


def test_shipped_surfaces_use_the_generic_item_prefix() -> None:
    """Command examples must not hardcode this repo's item prefix.

    Every project carries its own `public_item_prefix`, and the installer
    copies these files without substitution, so a literal ``YOK-`` reaches
    projects whose items are ``PLAT-`` or ``EXT-``.
    """
    offenders = _offenders(REPO_ITEM_PREFIX)
    assert offenders == [], (
        f"repo item prefix {REPO_ITEM_PREFIX!r} found in install-bundle "
        f"surfaces: {offenders}. Use {GENERIC_ITEM_PLACEHOLDER!r} in shipped "
        "command examples; a real item reference belongs in a repo-local "
        "surface, not in a file copied into other projects."
    )


MANAGED_BLOCK_FILES = (REPO / "AGENTS.md", REPO / "CODEX.md")
BLOCK_BEGIN = "<!-- BEGIN YOKE MANAGED BLOCK -->"
BLOCK_END = "<!-- END YOKE MANAGED BLOCK -->"

# A health-check id that happens to contain the lowercase prefix. It is a
# runtime identifier, not an item reference, so it ships verbatim.
MANAGED_BLOCK_ALLOWED = ("HC-historical-yok-n-cruft",)


def _managed_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    begin = text.index(BLOCK_BEGIN)
    end = text.index(BLOCK_END)
    return text[begin:end]


def test_managed_blocks_use_the_generic_item_prefix() -> None:
    """`yoke project install` copies these blocks into every project.

    Content below the END marker is repo-local and may name this repo's
    items freely; content inside the block may not.
    """
    offenders = []
    for path in MANAGED_BLOCK_FILES:
        if not path.is_file():
            continue
        block = _managed_block(path)
        for allowed in MANAGED_BLOCK_ALLOWED:
            block = block.replace(allowed, "")
        if REPO_ITEM_PREFIX in block:
            offenders.append(
                f"{path.name} ({block.count(REPO_ITEM_PREFIX)})"
            )
    assert offenders == [], (
        f"repo item prefix {REPO_ITEM_PREFIX!r} inside a managed block: "
        f"{offenders}. The block is copied verbatim into every installed "
        "project; move repo-specific examples below the END marker or use "
        f"{GENERIC_ITEM_PLACEHOLDER!r}."
    )


def test_the_generic_placeholder_is_actually_in_use() -> None:
    """Guard against the prefix check passing because examples vanished."""
    users = [
        path.relative_to(REPO)
        for path in _shipped_files()
        if GENERIC_ITEM_PLACEHOLDER
        in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert users, (
        "no shipped surface uses "
        f"{GENERIC_ITEM_PLACEHOLDER!r}; the item-prefix check would pass "
        "vacuously if the command examples were removed instead of "
        "genericized."
    )
