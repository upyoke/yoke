"""Stale-string test audit gate.

Provides deterministic test-surface discovery and stale-string verification
utilities for the implementing phase. Replaces the advisory-only text-sensitive
test audit with a structurally enforced gate.

Main entry points:

1. ``discover-surfaces <item-id>`` — Discover test surfaces for an item's
   project using project config (the ``context_routing`` Project Structure
   family's ``testing`` topic plus the ``e2e`` and ``smoke``
   ``command_definitions`` scopes), with fallback to deterministic
   directory scanning.
2. ``preflight <item-id> <search-root>`` — Discover surfaces, extract
   candidate old strings from the item spec/body, and grep before editing.
   Returns a JSON summary and never blocks on matches.
3. ``verify <item-id> <search-root>`` — Re-run the same audit as a blocking
   pre-commit gate. Exits 1 when stale strings remain.
4. ``grep <search-root> --strings <s1> [s2 ...] --surfaces <d1> [d2 ...]`` —
   Raw grep helper for explicit caller-supplied strings and surfaces.

Exit codes:
    0 — success / no blocking matches
    1 — blocking stale strings found
    2 — usage or extraction error

Module layout: this file owns the CLI surface (``main()``, the argparse
parser, and the public re-exports). Implementation lives in sibling
modules — ``stale_string_audit_discover``, ``stale_string_audit_grep``,
``stale_string_audit_summary``, and ``stale_string_audit_cmds``. The
re-exports below preserve the historical import surface so callers
continue using ``yoke_core.domain.stale_string_audit`` unchanged.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from yoke_core.domain._stale_string_audit_constants import (
    DEFAULT_TEST_DIRS,
    EXCLUDE_DIRS,
    FILE_LIKE_SUFFIXES,
    GENERIC_QUOTED_STRINGS,
    TEST_FILE_GLOBS,
    TEXT_SENSITIVE_KEYWORDS,
)
from yoke_core.domain.stale_string_audit_cmds import (
    cmd_discover_surfaces,
    cmd_grep,
    cmd_preflight,
    cmd_verify,
)
from yoke_core.domain.stale_string_audit_discover import (
    _extract_dirs_from_test_command,
    _extract_test_dirs_from_docs,
    _get_item_field,
    _get_project_for_item,
    _looks_like_test_surface,
    _normalize_item_id,
    _scan_test_directories,
    discover_test_surfaces,
)
from yoke_core.domain.stale_string_audit_extract import (
    _collect_diff_strings,
    _normalize_candidate_string,
    extract_candidate_strings,
    extract_candidate_strings_from_git_diff,
    is_text_sensitive_item,
)
from yoke_core.domain.stale_string_audit_grep import (
    _python_grep,
    _run_rg,
    grep_surfaces,
)
from yoke_core.domain.stale_string_audit_summary import build_audit_summary


__all__ = [
    # Constants
    "DEFAULT_TEST_DIRS",
    "EXCLUDE_DIRS",
    "FILE_LIKE_SUFFIXES",
    "GENERIC_QUOTED_STRINGS",
    "TEST_FILE_GLOBS",
    "TEXT_SENSITIVE_KEYWORDS",
    # Public discovery / extraction
    "discover_test_surfaces",
    "extract_candidate_strings",
    "extract_candidate_strings_from_git_diff",
    "is_text_sensitive_item",
    # Public grep + summary
    "build_audit_summary",
    "grep_surfaces",
    # CLI
    "cmd_discover_surfaces",
    "cmd_grep",
    "cmd_preflight",
    "cmd_verify",
    "main",
]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stale-string-audit",
        description="Text-sensitive test audit gate",
    )
    sub = parser.add_subparsers(dest="command")

    # discover-surfaces
    p_discover = sub.add_parser(
        "discover-surfaces",
        help="Discover test surfaces for an item's project",
    )
    p_discover.add_argument("item_id", help="Item ID (YOK-N or N)")

    p_preflight = sub.add_parser(
        "preflight",
        help="Discover surfaces, extract strings, and grep before editing",
    )
    p_preflight.add_argument("item_id", help="Item ID (YOK-N or N)")
    p_preflight.add_argument("search_root", help="Root directory to search under")

    p_verify = sub.add_parser(
        "verify",
        help="Blocking pre-commit stale-string verification for an item",
    )
    p_verify.add_argument("item_id", help="Item ID (YOK-N or N)")
    p_verify.add_argument("search_root", help="Root directory to search under")

    # grep
    p_grep = sub.add_parser(
        "grep",
        help="Grep test surfaces for stale strings",
    )
    p_grep.add_argument("search_root", help="Root directory to search under")
    p_grep.add_argument(
        "--strings", nargs="+", required=True,
        help="Candidate strings to search for",
    )
    p_grep.add_argument(
        "--surfaces", nargs="+", required=True,
        help="Test surface directories (relative to search root)",
    )

    args = parser.parse_args(argv)
    if args.command == "discover-surfaces":
        return cmd_discover_surfaces(args)
    elif args.command == "preflight":
        return cmd_preflight(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "grep":
        return cmd_grep(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
