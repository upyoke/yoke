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

from pathlib import Path

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
)
# Agent sidecar JSON carries the description shown in the agent-type listing,
# so it reaches a target project the same way the prose does.
SHIPPED_SUFFIXES = {".md", ".toml", ".json"}

REPO_TEST_ANCHORS = "runtime/api/ runtime/harness/ tests/"
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


def test_shipped_surfaces_carry_no_repo_local_test_anchors() -> None:
    """A target project's test layout is its own, not this repo's."""
    offenders = _offenders(REPO_TEST_ANCHORS)
    assert offenders == [], (
        "repo-local test anchors found in install-bundle surfaces: "
        f"{offenders}. Teach anchors in AGENTS.md below the managed-block "
        "marker and keep shipped copy project-neutral."
    )


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
