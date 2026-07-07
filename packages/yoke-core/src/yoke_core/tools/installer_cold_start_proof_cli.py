"""Argparse driver for the public-installer cold-start proof tool.

The matrix / probe-script generation and the shared proof helpers live in
``installer_cold_start_proof`` and ``installer_cold_start_proof_core``; this
module only wires those surfaces to the ``matrix`` / ``prepare`` / ``scan-log``
/ ``aws-preflight`` subcommands.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from yoke_core.tools.installer_cold_start_proof import (
    linux_proof_cells,
    prepare_evidence_dir,
)
from yoke_core.tools.installer_cold_start_proof_core import (
    DEFAULT_AWS_PROJECT,
    DEFAULT_REGION,
    aws_identity_preflight,
    scan_log_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_cold_start_proof",
        description="Prepare public-installer cold-start acceptance evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    matrix_parser = subparsers.add_parser(
        "matrix",
        help="Print the Linux EC2 proof matrix.",
    )
    matrix_parser.add_argument("--json", action="store_true")

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Create an evidence directory with Linux probe scripts.",
    )
    prepare_parser.add_argument("--evidence-dir", required=True, type=Path)
    prepare_parser.add_argument(
        "--run-id",
        default=None,
        help="Acceptance run id. Defaults to a generated e2e-* id.",
    )
    prepare_parser.add_argument("--commit-sha", required=True)
    prepare_parser.add_argument("--json", action="store_true")

    scan_parser = subparsers.add_parser(
        "scan-log",
        help="Fail when a log contains raw Yoke/GitHub token markers.",
    )
    scan_parser.add_argument("path", type=Path)
    scan_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser(
        "aws-preflight",
        help=(
            "Verify AWS CLI identity using the project aws-admin capability "
            "(run from a local-postgres source-dev/admin env such as "
            "YOKE_ENV=prod-db-admin)."
        ),
    )
    preflight_parser.add_argument("--project", default=DEFAULT_AWS_PROJECT)
    preflight_parser.add_argument("--region", default=DEFAULT_REGION)
    preflight_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "matrix":
            cells = [asdict(cell) for cell in linux_proof_cells()]
            return _emit(
                {"linux_cells": cells},
                args.json,
                _matrix_text(),
            )
        if args.command == "prepare":
            run_id = args.run_id or f"e2e-{uuid.uuid4().hex[:12]}"
            manifest = prepare_evidence_dir(
                args.evidence_dir.expanduser(),
                run_id=run_id,
                commit_sha=args.commit_sha,
            )
            return _emit(
                manifest,
                args.json,
                "Prepared installer acceptance evidence: "
                f"{args.evidence_dir}\nRun id: {manifest['run_id']}\n"
                f"Linux scripts: {len(manifest['script_paths'])}",
            )
        if args.command == "scan-log":
            found = scan_log_file(args.path.expanduser())
            report = {"ok": not found, "path": str(args.path), "markers": found}
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            elif found:
                print(
                    f"ERROR: secret markers found in {args.path}: "
                    + ", ".join(found),
                    file=sys.stderr,
                )
            else:
                print(f"PASS: no secret markers found in {args.path}")
            return 1 if found else 0
        if args.command == "aws-preflight":
            report = aws_identity_preflight(project=args.project, region=args.region)
            return _emit(
                report,
                args.json,
                "PASS aws-admin identity "
                f"project={report['project']} region={report['region']} "
                f"account={report['account']}",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _emit(payload: dict[str, object], as_json: bool, text: str) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(text)
    return 0


def _matrix_text() -> str:
    lines = []
    for cell in linux_proof_cells():
        lines.append(
            f"{cell.label}: {cell.base_url} "
            f"{cell.channel} python={','.join(cell.targets)}"
        )
    return "\n".join(lines)
