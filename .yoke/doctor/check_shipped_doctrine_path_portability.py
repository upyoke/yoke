"""HC-shipped-doctrine-path-portability: shipped doctrine cites reachable paths.

``yoke project install`` ships two doctrine surfaces into every managed
project verbatim: the managed block of each repo-root doctrine file, and the
Claude session rules tree. A repo path named inside either surface only means
something to its reader if the install bundle puts a file there. Citing a Yoke
source path the bundle does not ship — an ``docs/archive/`` decision record, an
in-tree tool module — reads as a dangling reference in every managed project,
which is how project-specific material re-enters the shipped block unnoticed.

A cited path gets one of three answers:

* **Shipped** — it is an install destination whose rendering source exists in
  this tree, or an exact file the bundle writes. Fine.
* **Yoke-only** — it is tracked in this repo but the bundle ships nothing at
  that path. FAIL: move the material outside the managed markers (into the
  repo-internals section), or cite the shipped path instead.
* **Not a repo path** — untracked (a generated view every project rebuilds for
  itself), a ``<placeholder>``, a bare directory convention, or a home-relative
  path. Skipped; this check is about portability, not spelling.

PASS — every cited repo path resolves in a managed project's layout.
FAIL — the detail names each surface, path, and which answer it got.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

from yoke_contracts.packs import PACK_RECEIPT_REL
from yoke_contracts.project_contract.managed_block import extract_block_body
from yoke_core.domain.file_line_check_helpers import run_git
from yoke_core.domain.install_bundle import (
    CANONICAL_SKILLS_DEST,
    CLAUDE_AGENTS_DEST,
    CLAUDE_AGENTS_SOURCE,
    CLAUDE_RULES_DEST,
    CLAUDE_RULES_SOURCE,
    CLAUDE_SKILLS_DEST,
    CODEX_AGENTS_DEST,
    CODEX_AGENTS_SOURCE,
    CODEX_SKILLS_DEST,
    CURSOR_AGENTS_DEST,
    CURSOR_AGENTS_SOURCE,
    DOCS_DEST,
    DOCS_SOURCE,
    SKILLS_SOURCE,
    is_bundle_junk_path,
)
from yoke_core.domain.install_bundle_managed import INSTALL_BUNDLE_SOURCE_FILES
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

_HC_NAME = "HC-shipped-doctrine-path-portability"
_HC_DESC = "Shipped doctrine cites only paths a managed project has"

# The repo-root file whose managed block carries the shared doctrine every
# managed project installs into its own AGENTS.md / CLAUDE.md.
_DOCTRINE_SOURCE = "AGENTS.md"

# Where the bundle writes each source dir in an installed project. A cited
# path under one of these prefixes is rendered from the paired source dir, so
# the citation resolves exactly when that source file exists here.
_INSTALL_DESTINATIONS: Tuple[Tuple[str, str], ...] = (
    (CANONICAL_SKILLS_DEST, SKILLS_SOURCE),
    (CLAUDE_SKILLS_DEST, SKILLS_SOURCE),
    (CODEX_SKILLS_DEST, SKILLS_SOURCE),
    (CLAUDE_AGENTS_DEST, CLAUDE_AGENTS_SOURCE),
    (CODEX_AGENTS_DEST, CODEX_AGENTS_SOURCE),
    (CURSOR_AGENTS_DEST, CURSOR_AGENTS_SOURCE),
    (CLAUDE_RULES_DEST, CLAUDE_RULES_SOURCE),
    (DOCS_DEST, DOCS_SOURCE),
)

_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")

# A path spelled with any of these is teaching a shape, not naming a file.
_PLACEHOLDER_CHARS = frozenset("<>{}*$|")
_LEADING_TRIM = "`'\"(["
_TRAILING_TRIM = "`'\")],;:."


def _exact_installed_paths() -> Set[str]:
    """Paths the bundle writes as whole files rather than as a dest tree."""
    from yoke_core.domain import project_contract
    from yoke_core.domain.agents_render_manifests import (
        CLAUDE_MANIFEST,
        CODEX_MANIFEST,
        CURSOR_MANIFEST,
    )

    # The display name only fills scaffold prose; the path set is invariant.
    paths = {
        entry["path"]
        for entry in project_contract.bundle_contract_files("Project")
    }
    # Created in the target project by `yoke pack install`, not by the bundle.
    paths.add(PACK_RECEIPT_REL)
    paths.update(INSTALL_BUNDLE_SOURCE_FILES)
    # The doctrine block installs into AGENTS.md and its auto-load twin.
    paths.add("CLAUDE.md")
    for manifest in (CLAUDE_MANIFEST, CODEX_MANIFEST, CURSOR_MANIFEST):
        config = manifest.get("worktree_hook_enablement", {}).get("config_path")
        if config:
            paths.add(config)
    return paths


def _shipped_surfaces(root: Path) -> List[Tuple[str, str]]:
    """``(label, text)`` for each shared-doctrine surface shipped verbatim.

    The doctrine block and the session rules are the two surfaces that teach
    project-agnostic rules. ``CODEX.md`` / ``CURSOR.md`` carry harness shells
    rather than shared doctrine and are audited on their own track, so they
    are outside this scan.
    """
    surfaces: List[Tuple[str, str]] = []
    doctrine = root / _DOCTRINE_SOURCE
    if doctrine.is_file():
        body = extract_block_body(doctrine.read_text(encoding="utf-8", errors="replace"))
        if body:
            surfaces.append((f"{_DOCTRINE_SOURCE} (managed block)", body))
    rules = root / CLAUDE_RULES_SOURCE
    if rules.is_dir():
        for path in sorted(
            p for p in rules.rglob("*") if p.is_file() and not is_bundle_junk_path(p)
        ):
            surfaces.append((
                f"{CLAUDE_RULES_DEST}/{path.relative_to(rules).as_posix()}",
                path.read_text(encoding="utf-8", errors="replace"),
            ))
    return surfaces


def cited_paths(text: str) -> List[str]:
    """Repo-path-shaped tokens named in inline code spans and link targets."""
    found: List[str] = []
    seen: Set[str] = set()
    spans = _INLINE_CODE.findall(text) + _LINK_TARGET.findall(text)
    for span in spans:
        for word in span.split():
            candidate = word.lstrip(_LEADING_TRIM).rstrip(_TRAILING_TRIM)
            if not _looks_like_repo_path(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
    return found


def _looks_like_repo_path(word: str) -> bool:
    if "/" not in word or word.endswith("/"):
        return False
    if any(char in _PLACEHOLDER_CHARS for char in word):
        return False
    if word.startswith(("~", "/", ".../")) or ".." in word or "://" in word:
        return False
    return True


def _verdict(path: str, root: Path, tracked: Set[str], installed: Set[str]) -> Optional[str]:
    """Reason this citation fails a managed project's reader, or ``None``."""
    for dest, source_dir in _INSTALL_DESTINATIONS:
        if path == dest:
            # The install root itself, named as a directory.
            return None
        prefix = f"{dest}/"
        if not path.startswith(prefix):
            continue
        source = f"{source_dir}/{path[len(prefix):]}"
        if (root / source).is_file():
            return None
        return f"installs from {source}, which does not exist in this tree"
    if path in installed:
        return None
    if path in tracked:
        return "tracked here but the install bundle ships nothing at that path"
    return None


def hc_shipped_doctrine_path_portability(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "repo root not resolvable (git rev-parse failed); "
            "shipped-doctrine path scan skipped",
        )
        return

    root = Path(repo_root)
    surfaces = _shipped_surfaces(root)
    if not surfaces:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "no managed doctrine block or session rules in this checkout; "
            "nothing ships from here",
        )
        return

    listed = run_git(["ls-files"], repo_root=root)
    if listed.returncode != 0:
        rec.record(
            _HC_NAME, _HC_DESC, "FAIL",
            f"could not list tracked files: {listed.stderr.strip()}",
        )
        return
    tracked = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
    installed = _exact_installed_paths()

    findings: List[str] = []
    for label, text in surfaces:
        for path in cited_paths(text):
            reason = _verdict(path, root, tracked, installed)
            if reason:
                findings.append(f"- {label}: `{path}` — {reason}")

    if findings:
        detail = ["shipped doctrine cites paths a managed project does not have:"]
        detail.extend(findings)
        detail.append(
            "Move the material outside the managed markers, or cite a shipped path."
        )
        rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(detail))
        return
    rec.record(
        _HC_NAME, _HC_DESC, "PASS",
        f"every repo path cited across {len(surfaces)} shipped surface(s) "
        "resolves in an installed project",
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "shipped-doctrine-path-portability",
        _HC_DESC,
        hc_shipped_doctrine_path_portability,
    ),
)
