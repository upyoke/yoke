from __future__ import annotations

import re
import subprocess
from typing import List, Tuple

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
    code_home = _read(REPO_ROOT / "docs/public/agents/rules/code-and-cli.md")
    assert "Write stateful helpers and hooks in Python" in code_home
    assert "docs/source-dev-doctrine.md" in doctrine
    source = _read(REPO_ROOT / "docs/source-dev-doctrine.md")
    assert "python3 -m yoke_core.tools.run_tests" in source
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
    assert "python3 -m yoke_core.hooks.bootstrap render-full" in codex

    hook_parity = _read(HOOK_PARITY_DOC)
    assert "harness-bootstrap.md" in hook_parity
    bootstrap = _read(REPO_ROOT / "docs/harness-bootstrap.md")
    assert "`yoke_core.hooks.bootstrap` renderer" in bootstrap
    assert "`render_full` is a deliberate complete read" in bootstrap
    assert "git-root-stable" not in hook_parity
    assert 'PYTHONPATH="$(git rev-parse --show-toplevel)' not in hook_parity
    assert "yoke hook evaluate <event>" in hook_parity
    assert "`PreToolUse@Bash`" in hook_parity
    assert "`UserPromptSubmit`" in hook_parity
    hook_config = _read(REPO_ROOT / "runtime/harness/codex/hooks.json")
    assert "yoke hook evaluate PreToolUse" in hook_config
    assert "yoke hook evaluate UserPromptSubmit" in hook_config

    test_inventory = _read(TEST_INVENTORY_DOC)
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
        _python_sources(),
        pattern,
        allowlist=_DIRECT_SH_ALLOWLIST,
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
                r"[\"'](" + retired_alt + r")[\"']",
                line,
            )
            if not quoted:
                continue
            # The line must also be inside a subprocess call context.
            # We look at a small window around the line to avoid false
            # positives from plain string assignments. If ``subprocess.``
            # appears within 3 lines before this line we flag it.
            start_lineno = max(1, lineno - 3)
            window = "\n".join(text.splitlines()[start_lineno - 1 : lineno])
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
