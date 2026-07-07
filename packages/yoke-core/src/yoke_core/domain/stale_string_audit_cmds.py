"""CLI subcommand bodies for the stale-string audit gate.

Owns ``cmd_discover_surfaces``, ``cmd_preflight``, ``cmd_verify``, and
``cmd_grep`` — the four leaf subcommands wired into the parser in
``stale_string_audit.main()``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from yoke_core.domain.stale_string_audit_discover import (
    _normalize_item_id,
    discover_test_surfaces,
)
from yoke_core.domain.stale_string_audit_grep import grep_surfaces
from yoke_core.domain.stale_string_audit_summary import build_audit_summary


def cmd_discover_surfaces(args: argparse.Namespace) -> int:
    item_id = _normalize_item_id(args.item_id)
    if item_id is None:
        print("Error: invalid item ID: %s" % args.item_id, file=sys.stderr)
        return 2

    result = discover_test_surfaces(item_id)
    print(json.dumps(result, indent=2))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    item_id = _normalize_item_id(args.item_id)
    if item_id is None:
        print("Error: invalid item ID: %s" % args.item_id, file=sys.stderr)
        return 2
    if not os.path.isdir(args.search_root):
        print("Error: search root not a directory: %s" % args.search_root, file=sys.stderr)
        return 2

    print(json.dumps(build_audit_summary(item_id, args.search_root), indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    item_id = _normalize_item_id(args.item_id)
    if item_id is None:
        print("Error: invalid item ID: %s" % args.item_id, file=sys.stderr)
        return 2
    if not os.path.isdir(args.search_root):
        print("Error: search root not a directory: %s" % args.search_root, file=sys.stderr)
        return 2

    summary = build_audit_summary(item_id, args.search_root)
    print(json.dumps(summary, indent=2))

    verdict = summary["verdict"]
    if verdict == "matches_found":
        unique_files = sorted(set(m["file"] for m in summary["matches"]))
        print(
            "\nStale strings found in %d file(s):" % len(unique_files),
            file=sys.stderr,
        )
        for f in unique_files:
            file_matches = [m for m in summary["matches"] if m["file"] == f]
            lines = sorted(set(m["line"] for m in file_matches))
            print("  %s:%s" % (f, ",".join(str(ln) for ln in lines)), file=sys.stderr)
        return 1
    if verdict == "missing_candidate_strings":
        print(
            "Error: item appears text-sensitive but no candidate strings were extracted from the spec/body.",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_grep(args: argparse.Namespace) -> int:
    search_root = args.search_root
    if not os.path.isdir(search_root):
        print("Error: search root not a directory: %s" % search_root, file=sys.stderr)
        return 2

    candidate_strings = args.strings
    test_surfaces = args.surfaces

    if not candidate_strings:
        print("Error: --strings required", file=sys.stderr)
        return 2
    if not test_surfaces:
        print("Error: --surfaces required", file=sys.stderr)
        return 2

    matches = grep_surfaces(search_root, candidate_strings, test_surfaces)

    if matches:
        print(json.dumps(matches, indent=2))
        # Emit human-readable summary to stderr
        unique_files = sorted(set(m["file"] for m in matches))
        print(
            "\nStale strings found in %d file(s):" % len(unique_files),
            file=sys.stderr,
        )
        for f in unique_files:
            file_matches = [m for m in matches if m["file"] == f]
            lines = sorted(set(m["line"] for m in file_matches))
            print("  %s:%s" % (f, ",".join(str(ln) for ln in lines)), file=sys.stderr)
        return 1  # Matches found — blocking

    print("[]")
    print("No stale strings found.", file=sys.stderr)
    return 0
