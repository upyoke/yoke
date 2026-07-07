"""CLI entrypoint for the checkout clean-room smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools.checkout_clean_room_smoke_core import (
    _write_machine_files,
    build_machine_config,
    run_smoke,
)
from yoke_core.tools.checkout_clean_room_smoke_helpers import (
    DEFAULT_ENV,
    DEFAULT_PROJECT_ID,
    SmokeError,
    assert_clean_clone_shape as _assert_clean_clone_shape,
    isolated_env as _isolated_env,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.checkout_clean_room_smoke",
        description="Run the checkout clean-room smoke.",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Yoke checkout to clone from (default: this repo root).",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Existing or new scratch directory for clone/home/venv.",
    )
    parser.add_argument(
        "--dsn-file",
        required=True,
        help=(
            "Path to an already-provisioned Postgres DSN file. The smoke copies "
            "its contents into the isolated ~/.yoke tree."
        ),
    )
    parser.add_argument("--env", default=DEFAULT_ENV)
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--keep-work-dir", action="store_true")
    parser.add_argument("--json-output", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_smoke(
            source_root=_source_root(args.source_root),
            dsn_file=Path(args.dsn_file).expanduser(),
            env_name=args.env,
            project_id=args.project_id,
            python=Path(args.python).expanduser(),
            work_dir=(Path(args.work_dir).expanduser() if args.work_dir else None),
            keep_work_dir=args.keep_work_dir,
        )
    except SmokeError as exc:
        print(f"checkout-clean-room-smoke: {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        Path(args.json_output).expanduser().write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _source_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser()
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


if __name__ == "__main__":
    raise SystemExit(main())
