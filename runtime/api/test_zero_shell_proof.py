from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Tuple

from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    RECIPE_RESIDUE_PATTERNS,
)
from runtime.api.test_zero_shell_proof_test_helpers import (
    AGENTS_DOC,
    CODEX_DOC,
    HOOK_PARITY_DOC,
    REPO_ROOT,
    TEST_INVENTORY_DOC,
    _DIRECT_SH_ALLOWLIST,
    _HELPER_WRAPPER_NAMES,
    _RETIRED_SCRIPT_NAMES,
    _iter_offenders,
    _python_sources,
    _read,
    _relative,
)


def test_repo_has_no_tracked_shell_files() -> None:
    result = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_public_installer_is_only_tracked_shell_script() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    shell_scripts: list[str] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        rel = raw_path.decode("utf-8")
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if rel.endswith(".tmpl"):
            continue
        try:
            first_line = path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).splitlines()[0]
        except IndexError:
            continue
        if first_line in {"#!/bin/sh", "#!/usr/bin/env sh"}:
            shell_scripts.append(rel)

    assert shell_scripts == ["packaging/public-installer/install"]


def test_operator_docs_point_at_python_entrypoints() -> None:
    doctrine = _read(AGENTS_DOC)
    assert "Prefer Python over shell for stateful work." in doctrine
    assert "python3 -m yoke_core.tools.run_tests" in doctrine
    for retired in (
        "yoke-db.sh",
        "backlog-registry.sh",
        "rebuild-board.sh",
        "preview-board-art.sh",
        "doctor.sh",
        "observe-tool.sh",
    ):
        assert retired not in doctrine

    codex = _read(CODEX_DOC)
    assert "python3 -m runtime.harness.codex.codex_entry bootstrap" in codex

    hook_parity = _read(HOOK_PARITY_DOC)
    assert "python3 -m runtime.harness.codex.codex_entry bootstrap" in hook_parity
    assert "git-root-stable" not in hook_parity
    assert "PYTHONPATH=\"$(git rev-parse --show-toplevel)" not in hook_parity
    assert "yoke hook evaluate PreToolUse" in hook_parity
    assert "yoke hook evaluate UserPromptSubmit" in hook_parity

    test_inventory = _read(TEST_INVENTORY_DOC)
    assert "python3 -m pytest runtime/harness/codex/test_codex_entry.py" in test_inventory
    assert "test-codex-entry.sh" not in test_inventory
    assert "test-codex-hooks.sh" not in test_inventory
    assert "test-harness-routing.sh" not in test_inventory


# ---------------------------------------------------------------------------
# Phase D: production-Python shell-dispatch regression guard
# ---------------------------------------------------------------------------


def test_no_direct_sh_subprocess_in_production_python() -> None:
    """``subprocess.run(["sh", ...])`` / ``subprocess.Popen(["sh", ...])``
    is banned in production Python outside the tiny allowlist."""
    # Match ``subprocess.run(["sh"`` and ``subprocess.Popen(["sh"`` — the
    # pattern is intentionally strict so it does not trip on ``sh`` as a
    # substring inside identifiers or comments.
    pattern = re.compile(r"subprocess\.(?:run|Popen)\(\s*\[\s*[\"']sh[\"']")
    offenders = _iter_offenders(
        _python_sources(), pattern, allowlist=_DIRECT_SH_ALLOWLIST,
    )
    assert not offenders, (
        "Direct ``subprocess.run(['sh', ...])`` / ``subprocess.Popen(['sh', ...])`` "
        "is banned in production Python (YOK-1373). Route the call through the "
        "Python domain owner instead, or add the file to "
        "_DIRECT_SH_ALLOWLIST if it is a legitimate user-command surface.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_no_retired_shell_script_name_as_subprocess_arg() -> None:
    """``subprocess.run([..., "foo.sh", ...])`` with a retired Yoke
    shell script name is banned even if the first argv entry is not
    ``sh`` (guards the ``sys.executable -m ... foo.sh`` hybrid too)."""
    # Match quoted retired script names anywhere inside a ``subprocess.``
    # call. We scan line-by-line and only flag lines that contain both
    # ``subprocess.`` and one of the retired names in the same line or in
    # the next few lines, to keep the guard cheap.
    retired_alt = "|".join(re.escape(n) for n in _RETIRED_SCRIPT_NAMES)
    # Match "foo.sh" in a quoted string anywhere — the subprocess call
    # may be multi-line, so we do a per-file scan rather than per-line.
    offenders: List[Tuple[str, int, str]] = []
    for src in _python_sources():
        rel = _relative(src)
        if rel in _DIRECT_SH_ALLOWLIST:
            # executors.py and merge_worktree.py forward user-supplied
            # commands; they must not reference retired script names
            # by string literal, but if they do the allowlist for the
            # direct-sh test already covers it.
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Check if the file even uses subprocess. Cheap fast path.
        if "subprocess" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not re.search(retired_alt, line):
                continue
            # Skip comments and docstrings — only flag string literals
            # inside actual call sites. A line that contains both a
            # retired script name and ``subprocess`` / helper call is
            # a strong signal.
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # The retired name must appear as a quoted string literal
            # (``"foo.sh"`` or ``'foo.sh'``), not as a bare word inside
            # a comment or docstring. Require adjacent quote.
            quoted = re.search(
                r"[\"'](" + retired_alt + r")[\"']", line,
            )
            if not quoted:
                continue
            # The line must also be inside a subprocess call context.
            # We look at a small window around the line to avoid false
            # positives from plain string assignments. If ``subprocess.``
            # appears within 3 lines before this line we flag it.
            start_lineno = max(1, lineno - 3)
            window = "\n".join(text.splitlines()[start_lineno - 1:lineno])
            if "subprocess." in window or "Popen" in window:
                offenders.append((rel, lineno, stripped))
    assert not offenders, (
        "Retired Yoke shell script name passed to ``subprocess.*`` in "
        "production Python (YOK-1373). Route the call through the Python "
        "domain owner instead.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_no_helper_wrapped_shell_dispatch_in_production_python() -> None:
    """Helper wrappers that dispatch to Yoke shell scripts are banned.

    The production-Python surface must not reintroduce ``_run_shell``,
    ``delegate_shell``, or ``_run_yoke_db`` helpers that target
    retired Yoke script names.
    """
    # Build a single combined pattern that matches any helper-wrapper
    # name followed by an open paren. The guard is intentionally
    # strict: ``_run_shell(`` anywhere in production Python is a
    # regression, regardless of what it forwards to, because the
    # helper itself was the invariant the spec called out.
    helper_alt = "|".join(re.escape(n) for n in _HELPER_WRAPPER_NAMES)
    pattern = re.compile(r"\b(" + helper_alt + r")\s*\(")
    offenders: List[Tuple[str, int, str]] = []
    for src in _python_sources():
        rel = _relative(src)
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if not match:
                continue
            stripped = line.lstrip()
            # Skip comments.
            if stripped.startswith("#"):
                continue
            # Skip docstring-ish references: lines whose first non-
            # whitespace character is a backtick or ``"`` indicator
            # and that do not contain ``(`` used as a call. We already
            # matched an open paren via the pattern, but docstring
            # examples wrap the name in backticks: ``\`_run_shell(\```.
            # If the match is inside a backtick run, skip it.
            before = line[: match.start()]
            if before.endswith("`"):
                continue
            offenders.append((rel, lineno, stripped))
    assert not offenders, (
        "Helper-wrapped shell dispatch (``_run_shell`` / ``delegate_shell`` / "
        "``_run_yoke_db``) is banned in production Python (YOK-1373). "
        "Route the call through the Python domain owner directly.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


# ---------------------------------------------------------------------------
# Yoke-functions epic: recipe-residue keyed on the
# canonical RECIPE_RESIDUE_PATTERNS constant — single source of truth for
# what counts as banned terminal-soup residue in live guidance surfaces.
# AC-15.4: this test and the Doctor HC consume the same constant.
# AC-15.1: this assertion is part of the zero-shell-proof suite.
# ---------------------------------------------------------------------------


_RESIDUE_PATH_ALLOWLIST: Tuple[str, ...] = (
    "docs/archive/",
    ".yoke/docs/db-reference/",
)

_RESIDUE_TEST_FILE_RE = re.compile(r"runtime/api/.*test_.*\.py$")

# Modules that define or scan the canonical pattern vocabulary itself.
# Their source text necessarily contains the banned literals; allowlist
# them out so the constant cannot fail its own residue check.
_RESIDUE_CANONICAL_SOURCES: Tuple[str, ...] = (
    "runtime/api/domain/lint_structured_field_transform_shell_messages.py",
    "runtime/api/engines/doctor_hc_terminal_recipe_residue.py",
    "runtime/api/engines/doctor_hc_terminal_recipe_residue_scan.py",
    "runtime/api/domain/lint_shell_quoted_function_payload.py",
    "runtime/api/domain/lint_shell_quoted_function_payload_messages.py",
)


def _residue_is_allowlisted(rel_path: str) -> bool:
    if rel_path.startswith(_RESIDUE_PATH_ALLOWLIST):
        return True
    if _RESIDUE_TEST_FILE_RE.search(rel_path):
        return True
    return rel_path in _RESIDUE_CANONICAL_SOURCES


def _iter_residue_scan_paths() -> List[Path]:
    """Live guidance surfaces mirrored from
    ``test_recipe_residue_manifest._iter_live_guidance_paths``."""
    paths: List[Path] = []
    for top_level in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        candidate = REPO_ROOT / top_level
        if candidate.is_file():
            paths.append(candidate)
    for directory in (
        ".agents/skills/yoke",
        "runtime/agents",
        "runtime/harness/claude/agents",
        "runtime/harness/codex/agents",
        "docs",
    ):
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            paths.append(path)
    return paths


def test_zero_shell_proof_includes_recipe_residue_patterns() -> None:
    """The zero-shell proof asserts no live skill/doc surface contains a
    banned terminal-soup recipe from :data:`RECIPE_RESIDUE_PATTERNS`.

    AC-15.1 / AC-15.4: keyed on the same canonical constant as the
    Doctor HC and the recipe-residue manifest test so the three surfaces
    cannot drift. ``test_no_recipe_residue_in_live_guidance`` (in
    ``test_recipe_residue_manifest``) is the dedicated manifest test;
    this assertion makes the zero-shell-proof suite explicitly cover the
    same invariant so a run of just this file catches any regression.
    """
    findings: List[Tuple[str, int, str, str]] = []
    for path in _iter_residue_scan_paths():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            rel = path
        rel_str = str(rel).replace("\\", "/")
        if _residue_is_allowlisted(rel_str):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in RECIPE_RESIDUE_PATTERNS:
                if pat in line:
                    findings.append(
                        (rel_str, lineno, pat, line.rstrip()[:160])
                    )
                    break
    assert not findings, (
        "Zero-shell-proof recipe-residue scan found banned terminal-soup "
        "recipes in live guidance. Keyed on "
        "``RECIPE_RESIDUE_PATTERNS`` from "
        "``lint_structured_field_transform_shell_messages``; matching the "
        "Doctor HC ``HC-terminal-recipe-residue`` and the dedicated "
        "manifest test. Allowed surfaces are docs/archive/**, "
        ".yoke/docs/db-reference/**, and runtime/api/**/test_*.py.\n\n"
        + "\n".join(
            f"  {rel}:{lineno}: [{pat}] {snippet}"
            for rel, lineno, pat, snippet in findings[:40]
        )
    )
