"""Permanent doc-hygiene regression guards.

Locks the cleaned-up topology against regressions. Each test greps active
repo surfaces (runtime/, docs/ excluding archive, .agents/, .claude/,
templates/, README.md) for a retired or forbidden pattern.

These tests do NOT touch the database, git, or any network.
They are permanent guards owned by the doc-hygiene subsystem.

The Yoke-functions epic adds a recipe-residue check
that consumes :data:`RECIPE_RESIDUE_PATTERNS` directly so the assertion
class cannot drift from the canonical vocabulary.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    RECIPE_RESIDUE_PATTERNS,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Cannot locate repo root")


REPO = _repo_root()

# Active surfaces to scan — archive is excluded from all of these
_ACTIVE_DIRS = [
    REPO / "runtime",
    REPO / "docs",  # archive subdirectory filtered per-test
    REPO / ".agents",
    REPO / ".claude",
    REPO / "templates",
]
_ACTIVE_FILES = [REPO / "README.md"]


_SELF = Path(__file__).resolve()


def _grep_active(
    pattern: str,
    *,
    extensions: tuple[str, ...] = (".py", ".md", ".json", ".sh"),
    exclude_archive: bool = True,
    exclude_strategy: bool = False,
) -> list[str]:
    """Return lines from active surfaces matching *pattern*."""
    hits: list[str] = []
    candidates: list[Path] = list(_ACTIVE_FILES)
    for d in _ACTIVE_DIRS:
        if not d.exists():
            continue
        for ext in extensions:
            for f in d.rglob(f"*{ext}"):
                if f.resolve() == _SELF:
                    continue  # never scan this file against its own patterns
                if "worktrees" in f.parts:
                    # Nested git-worktree checkouts (e.g. the Claude harness's
                    # .claude/worktrees/<branch>/) are full repo copies governed
                    # by their own branch — not authored active surfaces on main.
                    continue
                if exclude_archive and "archive" in f.parts:
                    continue
                if exclude_strategy and "strategy" in f.parts:
                    continue
                candidates.append(f)

    compiled = re.compile(pattern)
    for f in candidates:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                hits.append(f"{f.relative_to(REPO)}:{i}: {line.rstrip()}")
    return hits


# ---------------------------------------------------------------------------
# Retired path patterns
# ---------------------------------------------------------------------------


def test_no_yoke_yoke_db_in_active_surfaces():
    """No active file should reference the retired yoke/yoke.db path."""
    hits = _grep_active(
        r"yoke/yoke\.db",
        exclude_archive=True,
        exclude_strategy=True,
    )
    assert not hits, (
        "Active surfaces must not reference yoke/yoke.db (retired path).\n"
        + "\n".join(hits[:20])
    )


def test_no_yoke_api_path_prefix_in_active_surfaces():
    """yoke/api/ as a file path must not appear in active surfaces."""
    hits = _grep_active(
        r"yoke/api/",
        exclude_archive=True,
        exclude_strategy=True,
    )
    assert not hits, (
        "Active surfaces must not reference yoke/api/ (retired path prefix).\n"
        + "\n".join(hits[:20])
    )


# ---------------------------------------------------------------------------
# Retired shell wrappers
# ---------------------------------------------------------------------------


def test_no_install_sh_in_active_md_docs():
    """install.sh is retired; human-facing markdown docs must not reference it.

    Python source may legitimately name the retired script in docstrings or
    shell-inventory tracking. Only markdown surfaces are checked here. Third-party
    installer URLs are not Yoke wrapper references.
    """
    hits = _grep_active(
        r"\binstall\.sh\b",
        extensions=(".md",),
        exclude_archive=True,
        exclude_strategy=True,
    )
    hits = [
        hit for hit in hits
        if "https://claude.ai/install.sh" not in hit
    ]
    assert not hits, (
        "Active markdown docs must not reference install.sh (retired shell wrapper).\n"
        + "\n".join(hits[:20])
    )


def test_no_restart_api_sh_in_active_md_docs():
    """restart-api.sh is retired; human-facing markdown docs must not reference it."""
    hits = _grep_active(
        r"\brestart-api\.sh\b",
        extensions=(".md",),
        exclude_archive=True,
        exclude_strategy=True,
    )
    assert not hits, (
        "Active markdown docs must not reference restart-api.sh (retired shell wrapper).\n"
        + "\n".join(hits[:20])
    )


def test_no_start_api_sh_in_active_md_docs():
    """start-api.sh is retired; human-facing markdown docs must not reference it."""
    hits = _grep_active(
        r"\bstart-api\.sh\b",
        extensions=(".md",),
        exclude_archive=True,
        exclude_strategy=True,
    )
    assert not hits, (
        "Active markdown docs must not reference start-api.sh (retired shell wrapper).\n"
        + "\n".join(hits[:20])
    )


# ---------------------------------------------------------------------------
# Retired DB columns and other obsoleted surface names are enforced by
# HC-obsoleted-terms (see runtime/api/engines/doctor_hc_obsoleted_terms.py and
# the matching test module). This file keeps only the per-script retired-path
# guards that predate the generic HC.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test-file guardrails
# ---------------------------------------------------------------------------


def test_no_yoke_dry_run_env_var_in_test_files():
    """Tests must not set YOKE_DRY_RUN via env patches; mock _is_dry_run instead."""
    hits: list[str] = []
    test_globs = [
        REPO / "runtime" / "api",
        REPO / "runtime" / "harness",
    ]
    compiled = re.compile(r"YOKE_DRY_RUN")
    for base in test_globs:
        if not base.exists():
            continue
        for f in base.rglob("test_*.py"):
            if f.resolve() == _SELF:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    hits.append(f"{f.relative_to(REPO)}:{i}: {line.rstrip()}")
    assert not hits, (
        "Test files must not reference YOKE_DRY_RUN directly.\n"
        + "Mock `_is_dry_run` or `_dry_run` on the module instead.\n"
        + "\n".join(hits[:20])
    )


def test_no_hardcoded_yok42_in_test_files():
    """Test files must not add NEW literal "YOK-42" occurrences — IDs drift over time.

    Baseline: 244 legacy hits remain as of the "YOK-1445" initial pass.
    This count must not increase. Reduce toward zero via.
    Use TEST_ITEM_ID / TEST_ITEM_REF pattern when fixing each file.
    """
    # Baseline established during an earlier AC-8 pass; reduce to 0 via.
    LEGACY_BASELINE = 244
    hits: list[str] = []
    test_globs = [
        REPO / "runtime" / "api",
        REPO / "runtime" / "harness",
    ]
    compiled = re.compile(r"\bYOK-42\b")
    for base in test_globs:
        if not base.exists():
            continue
        for f in base.rglob("test_*.py"):
            if f.resolve() == _SELF:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    hits.append(f"{f.relative_to(REPO)}:{i}: {line.rstrip()}")
    assert len(hits) <= LEGACY_BASELINE, (
        f"YOK-42 hit count ({len(hits)}) exceeds baseline ({LEGACY_BASELINE}).\n"
        "Test files must not add new literal YOK-42 (drifts over time).\n"
        "Use TEST_ITEM_ID / TEST_ITEM_REF pattern instead.\n"
        "Reduce LEGACY_BASELINE as files are cleaned (target: 0, tracked in YOK-1446).\n"
        + "\n".join(hits[:20])
    )


# ---------------------------------------------------------------------------
# Archived-active-path checks — fully retired docs must have no active stubs
# ---------------------------------------------------------------------------


class TestArchivedDocNoActiveStubs:
    """Active paths for fully archived docs must be absent from active surfaces.

    These are permanent regression guards — if any of these files reappear at
    their old active path, a migration or merge conflict has silently undone
    the cleanup.
    """

    _ARCHIVED = [
        "docs/1246-proof.md",
        "docs/dedup.md",
        "docs/events-incident-followup.md",
        "docs/service-migration.md",
        "docs/template-drift-audit.md",
        "docs/worktree-lifecycle.md",
        "docs/zero-shell-subprocess-audit.md",
    ]

    def test_archived_docs_absent_from_active_path(self):
        for rel in self._ARCHIVED:
            active = REPO / rel
            assert not active.exists(), (
                f"{rel} was archived to docs/archive/ but the active path still exists. "
                "The archive move must fully delete the old active path."
            )

    def test_archived_docs_present_in_archive(self):
        for rel in self._ARCHIVED:
            fname = Path(rel).name
            archived = REPO / "docs" / "archive" / fname
            assert archived.exists(), (
                f"docs/archive/{fname} is missing — archive copy was not created."
            )

    def test_no_non_archive_links_to_retired_docs(self):
        """Active surfaces must not link to the retired active docs/ paths.

        Links that include archive/ in the path (docs/archive/...) are fine.
        Only bare docs/FILENAME.md links — without archive/ — are forbidden.
        """
        retired_names = [Path(r).name for r in self._ARCHIVED]
        # Match docs/FILENAME without archive in between
        pattern = r"docs/(?!archive/)(" + "|".join(re.escape(n) for n in retired_names) + r")"
        hits = _grep_active(
            pattern,
            extensions=(".md",),
            exclude_archive=True,
            exclude_strategy=True,
        )
        assert not hits, (
            "Active docs must not reference the retired active paths for archived docs.\n"
            "Update links to point to docs/archive/ or remove the reference.\n"
            + "\n".join(hits[:20])
        )


# recipe-residue regression keyed on the canonical
# RECIPE_RESIDUE_PATTERNS constant — single source of truth shared with
# HC-terminal-recipe-residue and test_recipe_residue_manifest.


def test_no_recipe_residue_patterns_in_active_md_docs():
    """Active markdown docs must contain zero banned residue patterns.
    Allowlist: docs/archive/**, docs/db-reference/**, and
    ``runtime/api/**/test_fixtures/**`` (intentional regression fixtures).
    """
    findings: list[str] = []
    for pat in RECIPE_RESIDUE_PATTERNS:
        hits = _grep_active(
            re.escape(pat), extensions=(".md",), exclude_archive=True,
        )
        for hit in hits:
            if "docs/db-reference/" in hit or "/test_fixtures/" in hit:
                continue
            findings.append(f"[{pat}] {hit}")
    assert not findings, (
        "Active markdown contains banned terminal-soup recipe patterns "
        "from RECIPE_RESIDUE_PATTERNS (YOK-1665). Allowed surfaces: "
        "docs/archive/**, docs/db-reference/**, "
        "runtime/api/**/test_fixtures/**.\n" + "\n".join(findings[:20])
    )
