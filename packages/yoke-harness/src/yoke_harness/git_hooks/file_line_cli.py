"""CLI renderer for the product-safe file-line checker."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Optional, Sequence

from yoke_harness.git_hooks import file_line_check as flc


def _entry_to_dict(entry: flc.FileEntry) -> dict:
    return {
        "path": entry.path,
        "line_count": entry.line_count,
        "classification": entry.classification.value,
    }


def _change_to_dict(change: flc.ChangedFile) -> dict:
    return {
        "path": change.path,
        "classification": change.classification.value,
        "old_line_count": change.old_line_count,
        "new_line_count": change.new_line_count,
        "delta": change.delta,
    }


def print_report(
    entries: list[flc.FileEntry], *, limit: int, as_json: bool
) -> None:
    if as_json:
        payload = {
            "limit": limit,
            "entries": [_entry_to_dict(e) for e in entries],
        }
        print(json.dumps(payload, indent=2))
        return
    print(f"# file_line_check report - limit={limit} - {len(entries)} file(s)")
    print(f"{'lines':>6}  {'classification':<22}  path")
    for entry in entries:
        print(
            f"{entry.line_count:>6}  {entry.classification.value:<22}  "
            f"{entry.path}"
        )


def print_verdict(verdict: flc.CheckVerdict, *, as_json: bool) -> None:
    if as_json:
        payload = {
            "ok": verdict.ok,
            "hard_fails": [_change_to_dict(c) for c in verdict.hard_fails],
            "warnings": [_change_to_dict(c) for c in verdict.warnings],
            "summary": verdict.summary,
        }
        print(json.dumps(payload, indent=2))
        return
    print(f"file_line_check: {verdict.summary}")
    for change in verdict.hard_fails:
        print(
            f"  HARD-FAIL  {change.path}  {change.old_line_count} -> "
            f"{change.new_line_count} (delta {change.delta:+d})"
        )
    for change in verdict.warnings:
        print(
            f"  WARN       {change.path}  {change.old_line_count} -> "
            f"{change.new_line_count} (delta {change.delta:+d})"
        )
    if not verdict.ok:
        print(
            "Fix the offending file(s) or bypass pre-commit with "
            "`git commit --no-verify`."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yoke check file-line")
    sub = parser.add_subparsers(dest="cmd", required=True)
    report = sub.add_parser("report")
    report.add_argument("--json", action="store_true")
    report.add_argument("--repo", default=None)
    check = sub.add_parser("check")
    mode = check.add_mutually_exclusive_group()
    mode.add_argument("--base", default=None)
    mode.add_argument("--staged", action="store_true")
    check.add_argument("--json", action="store_true")
    check.add_argument("--repo", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    repo_root = pathlib.Path(args.repo).resolve() if args.repo else pathlib.Path.cwd()
    policy = flc.resolved_policy(repo_root)
    if args.cmd == "report":
        print_report(
            flc.inventory(repo_root=repo_root),
            limit=policy.limit,
            as_json=args.json,
        )
        return 0
    verdict = flc.changed_files_check(
        repo_root=repo_root,
        base=args.base,
        staged=args.staged,
    )
    print_verdict(verdict, as_json=args.json)
    return 0 if verdict.ok else 1


__all__ = ["build_parser", "main", "print_report", "print_verdict"]
