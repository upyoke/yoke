"""Refresh/check Windows expectations or report durable machine QA receipts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess

from yoke_cli.windows_evidence_ledger import (
    FIELDS, LEDGER_PATH, expected_rows, load_rows, validate_rows,
)
from yoke_cli.windows_evidence_report import report


def refresh(*, target_root: Path) -> None:
    from yoke_core.domain.workspace_authority import assert_target_under_session_work_authority

    directory = target_root / LEDGER_PATH
    assert_target_under_session_work_authority(directory)
    existing = {row["row_id"]: row for row in load_rows(target_root)}
    rows = [existing.get(row["row_id"], row) for row in expected_rows(target_root)]
    validate_rows(rows, expected_rows(target_root))
    directory.mkdir(parents=True, exist_ok=True)
    # Bounded shards keep reviewed data within the authored-file line limit.
    for shard in range(64):
        path = directory / f"{shard:02x}.csv"
        if path.is_symlink():
            raise ValueError(f"windows_ledger_symlink: remove symlink {path} and refresh")
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(row for row in rows if int(row["row_id"][-2:], 16) % 64 == shard)


def read_receipts(project: str) -> list[dict]:
    """Read every page through the registered CLI; never use database access."""
    receipts, offset = [], 0
    while True:
        command = ["yoke", "qa", "run", "list", "--project", project,
                   "--limit", "500", "--offset", str(offset), "--json"]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        if completed.returncode:
            raise ValueError("windows_receipts_unavailable: repair the connection and rerun; " + completed.stderr.strip())
        envelope = json.loads(completed.stdout)
        if not envelope.get("success"):
            raise ValueError("windows_receipts_unavailable: repair the QA run read refusal and rerun")
        result = envelope["result"]
        receipts.extend(result["rows"])
        next_offset = result.get("next_offset")
        if next_offset is None:
            return receipts
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("windows_receipts_pagination_invalid: repair qa run list pagination and rerun")
        offset = next_offset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refresh", "check", "report"))
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--receipts", type=Path, help="JSON array of exported qa run list rows")
    parser.add_argument("--project", help="read all durable QA runs for this project")
    parser.add_argument("--yoke-release", help="exact release whose native proof is requested")
    args = parser.parse_args(argv)
    try:
        if args.action == "refresh":
            refresh(target_root=args.target_root.resolve())
            return 0
        rows = load_rows(args.target_root)
        validate_rows(rows, expected_rows(args.target_root))
        if args.action == "check":
            print(f"Windows expectations valid: {len(rows)} rows")
            return 0
        if not args.yoke_release or bool(args.receipts) == bool(args.project):
            parser.error("report requires --yoke-release and exactly one of --receipts or --project")
        receipts = (json.loads(args.receipts.read_text(encoding="utf-8"))
                    if args.receipts else read_receipts(args.project))
        if not isinstance(receipts, list) or any(not isinstance(row, dict) for row in receipts):
            raise ValueError("windows_receipts_invalid: export QA run rows as a JSON array and rerun")
        print(json.dumps(report(rows, receipts, yoke_release=args.yoke_release), indent=2))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"windows_evidence_unavailable: {exc}; repair the named input and rerun\n")


if __name__ == "__main__":
    raise SystemExit(main())
