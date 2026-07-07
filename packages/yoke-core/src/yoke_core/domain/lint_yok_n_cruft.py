"""Linter for historical ``YOK-N`` cruft in live prose surfaces.

Policy (``AGENTS.md`` "Code Conventions"): inline ``YOK-N`` references are
reserved for *active state* — a current bug ID, a pending migration, a
``TODO`` tied to an open item, or a gate/guard keyed on the ticket.
Historical provenance ("we added this in YOK-X") belongs in commit messages,
not in code or docs.

This linter flags residue. It runs at ``severity=warn`` for the first release
so owners can sweep on their schedule without blocking unrelated work. The
companion health check ``HC-historical-yok-n-cruft`` wires this into
``python3 -m yoke_core.engines.doctor`` and ``yoke_core.tools.run_tests``.

CLI usage::

    python3 -m yoke_core.domain.lint_yok_n_cruft [PATH ...]
    python3 -m yoke_core.domain.lint_yok_n_cruft --json

The scanner core (scope rules, exemptions, ticket-status lookup,
allowed-context predicate, and :func:`scan` itself) lives in
:mod:`yoke_core.domain.lint_yok_n_cruft_scan`. This module owns the CLI
parser, output formatter, and the public re-export of the data classes /
``scan`` so callers can keep importing
``yoke_core.domain.lint_yok_n_cruft.scan``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_yok_n_cruft_scan import (
    CruftHit,
    LintResult,
    scan,
)

__all__ = ["CruftHit", "LintResult", "scan", "main"]


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()


def _emit_json(result: LintResult, repo_root: Path) -> None:
    payload = {
        "scanned_files": result.scanned_files,
        "ticket_lookups": result.ticket_lookups,
        "unknown_tickets": sorted(result.unknown_tickets),
        "hits": [
            {
                "path": str(h.path.resolve().relative_to(repo_root.resolve()))
                if h.path.resolve().is_relative_to(repo_root.resolve())
                else str(h.path),
                "line": h.line,
                "ticket": h.ticket,
                "status": h.status,
                "context": h.context,
            }
            for h in result.hits
        ],
    }
    print(json.dumps(payload))


def _emit_human(result: LintResult, repo_root: Path, *, quiet_pass: bool) -> None:
    if not result.hits:
        if not quiet_pass:
            print(
                f"PASS: no historical YOK-N cruft found "
                f"({result.scanned_files} files scanned)."
            )
        return

    for hit in result.hits:
        try:
            rel = hit.path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = hit.path
        print(f"{rel}:{hit.line}: {hit.ticket} (status={hit.status}) — {hit.context}")
    summary = (
        f"\n{len(result.hits)} cruft reference(s) across {len({h.path for h in result.hits})} "
        f"file(s). Scanned {result.scanned_files} file(s)."
    )
    print(append_field_note_footer(summary, rule_id="lint-yok-n-cruft"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.lint_yok_n_cruft",
        description=(
            "Flag historical YOK-N references in live prose surfaces whose "
            "referenced ticket is done and whose context is not an allowed "
            "exemption."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional extra paths (files or directories) to scan beyond the default set.",
    )
    parser.add_argument("--json", action="store_true", help="Emit results as JSON.")
    parser.add_argument(
        "--quiet-pass",
        action="store_true",
        help="Suppress the summary line when there are zero hits.",
    )
    args = parser.parse_args(argv)

    repo_root = _resolve_repo_root()
    extra_paths = [Path(p) for p in args.paths]

    db_path = os.environ.get("YOKE_DB") or None
    result = scan(repo_root, db_path=db_path, extra_paths=extra_paths)

    if args.json:
        _emit_json(result, repo_root)
        return 0

    _emit_human(result, repo_root, quiet_pass=args.quiet_pass)
    return 0  # warn-only posture for the first release


if __name__ == "__main__":
    sys.exit(main())
