"""CLI entrypoint for the product-wheel no-checkout CLI smoke.

Usage:

    python3 -m yoke_core.tools.product_cli_no_checkout_smoke run \
        [--api-url URL] [--online] [--keep-work-dir]

Builds the current checkout's wheel into a fresh venv and proves the
installed ``yoke`` CLI works from an empty directory with no Yoke
checkout — loud typed failures included. Offline by default: the live
relay-denial step runs only with ``--online``. Prints the report as
JSON and exits non-zero when any step fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools.product_cli_no_checkout_smoke_core import (
    DEFAULT_API_URL,
    run_smoke,
)
from yoke_core.tools.checkout_clean_room_smoke_helpers import SmokeError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.product_cli_no_checkout_smoke",
        description="Run the product-wheel no-checkout CLI smoke.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run", help="Build the wheel, install it cold, drive the smoke steps.",
    )
    run_parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="HTTPS relay base URL the smoke envs point at "
             f"(default: {DEFAULT_API_URL}).",
    )
    run_parser.add_argument(
        "--online",
        action="store_true",
        help="Also exercise the live relay-denial step against --api-url.",
    )
    run_parser.add_argument(
        "--source-root",
        default=None,
        help="Yoke checkout to wheel-build (default: this repo root).",
    )
    run_parser.add_argument("--python", default=sys.executable)
    run_parser.add_argument(
        "--work-dir",
        default=None,
        help="Existing or new scratch directory for wheel/venv/home/project.",
    )
    run_parser.add_argument("--keep-work-dir", action="store_true")
    run_parser.add_argument("--json-output", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_smoke(
            source_root=_source_root(args.source_root),
            api_url=args.api_url,
            online=args.online,
            python=Path(args.python).expanduser(),
            work_dir=(Path(args.work_dir).expanduser() if args.work_dir else None),
            keep_work_dir=args.keep_work_dir,
        )
    except SmokeError as exc:
        print(f"product-cli-no-checkout-smoke: {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        Path(args.json_output).expanduser().write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


def _source_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser()
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


if __name__ == "__main__":
    raise SystemExit(main())
