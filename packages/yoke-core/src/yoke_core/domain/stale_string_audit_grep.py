"""Grep-over-test-surfaces for the stale-string audit gate.

Owns the public ``grep_surfaces()`` entry point plus the ripgrep-first /
Python-fallback executors.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List

from yoke_core.domain._stale_string_audit_constants import (
    EXCLUDE_DIRS,
    TEST_FILE_GLOBS,
)


def grep_surfaces(
    search_root: str,
    candidate_strings: List[str],
    test_surfaces: List[str],
) -> List[Dict[str, Any]]:
    """Grep test surfaces for candidate strings.

    Returns a list of match dicts::

        [{"file": "e2e/auth.spec.ts", "line": 42, "content": "...", "string": "old text"}]
    """
    matches: List[Dict[str, Any]] = []
    if not candidate_strings or not test_surfaces:
        return matches

    for candidate in candidate_strings:
        if not candidate.strip():
            continue
        for surface in test_surfaces:
            surface_path = os.path.join(search_root, surface)
            if not os.path.exists(surface_path):
                continue
            try:
                result = _run_rg(search_root, candidate, surface)
                matches.extend(result)
            except Exception:
                # Fallback to Python-native grep
                result = _python_grep(search_root, candidate, surface)
                matches.extend(result)

    return matches


def _run_rg(
    search_root: str, pattern: str, surface: str,
) -> List[Dict[str, Any]]:
    """Use ripgrep if available."""
    surface_path = os.path.join(search_root, surface)
    exclude_args: List[str] = []
    for d in EXCLUDE_DIRS:
        exclude_args.extend(["--glob", f"!{d}/"])

    glob_args: List[str] = []
    for g in TEST_FILE_GLOBS:
        glob_args.extend(["--glob", g])

    cmd = [
        "rg", "--no-heading", "--line-number", "--fixed-strings",
        *exclude_args, *glob_args,
        pattern, surface_path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise  # Let caller fall back to Python grep

    matches: List[Dict[str, Any]] = []
    if proc.returncode == 0 and proc.stdout.strip():
        for line in proc.stdout.strip().split("\n"):
            # Format: /path/file.ts:42:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                filepath = parts[0]
                try:
                    lineno = int(parts[1])
                except ValueError:
                    lineno = 0
                content = parts[2]
                # Make path relative to search_root
                rel = os.path.relpath(filepath, search_root)
                matches.append({
                    "file": rel,
                    "line": lineno,
                    "content": content.strip(),
                    "string": pattern,
                })
    return matches


def _python_grep(
    search_root: str, pattern: str, surface: str,
) -> List[Dict[str, Any]]:
    """Pure-Python fallback grep."""
    matches: List[Dict[str, Any]] = []
    surface_path = os.path.join(search_root, surface)
    if not os.path.isdir(surface_path):
        return matches

    extensions = {".ts", ".tsx", ".js", ".jsx", ".py"}
    for root, dirs, files in os.walk(surface_path):
        # Prune excluded dirs
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext not in extensions:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if pattern in line:
                            rel = os.path.relpath(fpath, search_root)
                            matches.append({
                                "file": rel,
                                "line": i,
                                "content": line.strip(),
                                "string": pattern,
                            })
            except OSError:
                continue
    return matches
