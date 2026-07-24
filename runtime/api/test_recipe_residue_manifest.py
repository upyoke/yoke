"""Recipe-residue manifest test — Yoke-functions epic.

Scans live guidance surfaces for every banned literal in
:data:`yoke_core.domain.lint_structured_field_transform_shell_messages.RECIPE_RESIDUE_PATTERNS`
and asserts zero hits outside the allowlist. This is the test-side mirror of
:mod:`yoke_core.engines.doctor_hc_terminal_recipe_residue` — both consume the
same canonical pattern list so the two surfaces cannot drift.

Allowlist (per the spec's `## Cleanup and Removal`):

* ``docs/archive/**`` — historical decision records and removed surfaces.
* ``.yoke/docs/db-reference/**`` — operator CLI reference with sanctioned adapter
  examples.
* ``runtime/api/**/test_*.py`` — test fixtures including the deliberate
  regression-guard fixture exercised by ``test_fixture_residue_is_detected``.

Scanned surfaces:

* ``.agents/skills/yoke/**``
* ``runtime/agents/**``
* ``runtime/harness/{claude,codex}/agents/**``
* ``docs/**``
* ``AGENTS.md``, ``CLAUDE.md``, ``CODEX.md``

The fixture-residue regression test (AC-15.3) injects a fresh hit of one
canonical pattern into a temporary fixture path and asserts the scanner
flags it; this protects the assertion class from silently regressing into a
no-op when the scan globs are tightened.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import List, Tuple

from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    RECIPE_RESIDUE_PATTERNS,
)


# Repo root resolution: two parents up from ``runtime/api/test_*.py`` lands at
# the worktree root. This module never reads the DB or hits the network.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_PATH_ALLOWLIST: Tuple[str, ...] = (
    "docs/archive/",
    ".yoke/docs/db-reference/",
)

_TEST_FILE_RE = re.compile(r"runtime/api/.*test_.*\.py$")


def _is_allowlisted(rel_path: str) -> bool:
    if rel_path.startswith(_PATH_ALLOWLIST):
        return True
    if _TEST_FILE_RE.search(rel_path):
        return True
    # The canonical pattern list lives in these modules by definition —
    # they cannot fail the residue scan against their own source-of-truth
    # vocabulary.
    canonical_sources = (
        "runtime/api/domain/lint_structured_field_transform_shell_messages.py",
        "runtime/api/engines/doctor_hc_terminal_recipe_residue.py",
        "runtime/api/engines/doctor_hc_terminal_recipe_residue_scan.py",
        "runtime/api/domain/lint_shell_quoted_function_payload.py",
        "runtime/api/domain/lint_shell_quoted_function_payload_messages.py",
    )
    return rel_path in canonical_sources


def _iter_live_guidance_paths(repo_root: Path) -> List[Path]:
    """Yield every live guidance surface the residue scan should cover."""
    paths: List[Path] = []
    for top_level in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        candidate = repo_root / top_level
        if candidate.is_file():
            paths.append(candidate)
    for directory in (
        ".agents/skills/yoke",
        "runtime/agents",
        "runtime/harness/claude/agents",
        "runtime/harness/codex/agents",
        "docs",
    ):
        base = repo_root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            paths.append(path)
    return paths


def _scan_patterns_in_paths(
    paths: List[Path],
    *,
    repo_root: Path,
    patterns: Tuple[str, ...] = RECIPE_RESIDUE_PATTERNS,
) -> List[Tuple[str, int, str, str]]:
    """Return ``[(rel_path, lineno, pattern, snippet)]`` for every banned hit."""
    findings: List[Tuple[str, int, str, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = path
        rel_str = str(rel).replace("\\", "/")
        if _is_allowlisted(rel_str):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in patterns:
                if pat in line:
                    findings.append((rel_str, lineno, pat, line.rstrip()[:160]))
                    break
    return findings


def test_recipe_residue_patterns_constant_exists() -> None:
    """AC-15.4: the manifest test is keyed on a single canonical constant.

    The assertion class for this entire suite is the
    :data:`RECIPE_RESIDUE_PATTERNS` constant from
    ``lint_structured_field_transform_shell_messages``. If the constant moves
    or renames, both this test and the Doctor HC need to be updated in lock-
    step — this assertion documents the dependency.
    """
    assert RECIPE_RESIDUE_PATTERNS, (
        "RECIPE_RESIDUE_PATTERNS must be a non-empty tuple of substring "
        "patterns. Update both this test and "
        "yoke_core.engines.doctor_hc_terminal_recipe_residue together "
        "when the canonical vocabulary changes."
    )
    # The canonical residue classes named in the messages module docstring
    # must each contribute at least one pattern. This guards the constant
    # from shrinking into a no-op without an intentional shape change.
    joined = " | ".join(RECIPE_RESIDUE_PATTERNS)
    expected_classes = (
        # Hand-quoted JSON payload to service_client.
        "service_client functions-call --payload",
        # Capability probe via shell status / redirection choreography.
        "has-capability yoke ephemeral-env",
        # Raw sqlite3 against the control-plane DB.
        "sqlite3",
        # items.get piped into in-line Python for transform.
        "items get ${ITEM} spec | python3 -c",
        # Progress Log mktemp + read-then-upsert.
        "mktemp /tmp/yoke-progress",
    )
    for class_marker in expected_classes:
        assert class_marker in joined, (
            f"RECIPE_RESIDUE_PATTERNS lost coverage for {class_marker!r}. "
            "Restore the pattern or update both the messages module and "
            "this test together."
        )


def test_no_recipe_residue_in_live_guidance() -> None:
    """AC-15.2: the manifest scan finds zero hits outside the allowlist."""
    paths = _iter_live_guidance_paths(_REPO_ROOT)
    findings = _scan_patterns_in_paths(paths, repo_root=_REPO_ROOT)
    assert not findings, (
        "Recipe-residue manifest scan found banned terminal-soup recipe "
        "patterns in live guidance surfaces. Each entry below names the "
        "file:line, the matched pattern, and a short snippet. The "
        "function-call surface (yoke_function_dispatch + adapter "
        "--json) replaces these shapes. Allowlisted surfaces are "
        "docs/archive/**, .yoke/docs/db-reference/**, and "
        "runtime/api/**/test_*.py.\n\n"
        + "\n".join(
            f"  {rel}:{lineno}: [{pat}] {snippet}"
            for rel, lineno, pat, snippet in findings[:40]
        )
    )


def test_fixture_residue_is_detected() -> None:
    """AC-15.3: a deliberate single-line regression in a fixture is caught.

    Writes one ``mktemp /tmp/yoke-progress`` line into a temporary skill-
    shaped fixture path, runs the scanner against the fixture path only, and
    asserts at least one finding. This proves the scanner is not a silent
    no-op when the patterns constant or the scan globs are tightened.
    """
    with tempfile.TemporaryDirectory(prefix="yoke-residue-fixture-") as tmp:
        fixture_root = Path(tmp)
        # Synthetic skill-doc fixture path; the scanner does not require
        # the file to live under a real ``.agents/`` directory because we
        # pass the path list explicitly.
        fixture_file = fixture_root / "stale_progress_log_recipe.md"
        fixture_file.write_text(
            "# Synthetic stale-recipe fixture\n"
            "_tmp=$(mktemp /tmp/yoke-progress.XXXXXX)\n",
            encoding="utf-8",
        )
        findings = _scan_patterns_in_paths(
            [fixture_file], repo_root=fixture_root,
        )
        assert findings, (
            "Recipe-residue scanner failed to detect a deliberately-"
            "injected ``mktemp /tmp/yoke-progress`` line. The scanner "
            "must remain sensitive to every pattern in "
            "RECIPE_RESIDUE_PATTERNS — a no-op scanner silently lets "
            "live regressions land."
        )
        matched_patterns = {pat for _, _, pat, _ in findings}
        assert "mktemp /tmp/yoke-progress" in matched_patterns, (
            "Fixture residue matched a different pattern than expected; "
            "investigate which RECIPE_RESIDUE_PATTERNS entry fired."
        )


def test_scan_paths_cover_required_surfaces() -> None:
    """AC-15.5 (partial): the scan globs cover every live guidance surface.

    The amendment ACs (15.5-15.8) require the manifest test to consume the
    inventory classifier task 16 will produce. Until that classifier lands,
    we still assert the scan globs cover every live guidance directory
    named in the task spec; this prevents a future glob tightening from
    silently skipping a surface.
    """
    paths = _iter_live_guidance_paths(_REPO_ROOT)
    rels = {
        str(p.resolve().relative_to(_REPO_ROOT.resolve())).replace("\\", "/")
        for p in paths
    }
    # AGENTS.md is the canonical top-level rules surface that must be
    # covered. CLAUDE.md and CODEX.md may be symlinks to AGENTS.md (Yoke
    # ships CLAUDE.md as a symlink today); we only require the canonical
    # AGENTS.md to be in scope.
    assert "AGENTS.md" in rels, (
        "Recipe-residue scan must include AGENTS.md; the live-rules "
        "surface is where false-teacher recipes most commonly survive."
    )
    # At least one skill-doc file must be present.
    assert any(r.startswith(".agents/skills/yoke/") for r in rels), (
        "Recipe-residue scan must include .agents/skills/yoke/** "
        "skill prose. Without it the False-Teacher Eradication Contract "
        "has no coverage of the primary teaching surface."
    )
    # At least one canonical-agent file must be present.
    assert any(r.startswith("runtime/agents/") for r in rels), (
        "Recipe-residue scan must include runtime/agents/** canonical "
        "prompt prose. Generated harness agents inherit from these "
        "canonicals, so the residue check must cover them."
    )
    # At least one generated harness agent surface must be present.
    has_generated = any(
        r.startswith(("runtime/harness/claude/agents/",
                      "runtime/harness/codex/agents/"))
        for r in rels
    )
    assert has_generated, (
        "Recipe-residue scan must include the generated harness agent "
        "outputs under runtime/harness/{claude,codex}/agents/**. These "
        "are the live surfaces agents actually read."
    )
