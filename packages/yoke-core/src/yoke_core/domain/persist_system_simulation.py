"""Persist system-wide simulation reports under ``ouroboros/health/``.

Creates the parent directory on first run so a clean checkout does not
need a prior doctor or simulate pass to leave the path behind.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

RELATIVE_HEALTH_DIR = Path("ouroboros") / "health"
REPORT_NAME_TEMPLATE = "simulation-system-{stamp}.md"


def default_report_path(repo_root: Path, *, day: date | None = None) -> Path:
    """Return the dated system-simulation report path under ``repo_root``."""
    stamp = (day or date.today()).strftime("%Y%m%d")
    return repo_root / RELATIVE_HEALTH_DIR / REPORT_NAME_TEMPLATE.format(stamp=stamp)


def persist_system_simulation_report(
    content: str,
    *,
    repo_root: Path | None = None,
    path: Path | None = None,
    day: date | None = None,
) -> Path:
    """Write a system-simulation report, creating ``ouroboros/health`` if needed."""
    if path is None:
        root = Path.cwd() if repo_root is None else Path(repo_root)
        path = default_report_path(root, day=day)
    else:
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.persist_system_simulation",
        description=(
            "Persist a system-wide simulation report under ouroboros/health/, "
            "creating the parent directory when missing."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Checkout root (default: cwd)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Explicit report path (skips dated default under ouroboros/health/)",
    )
    args = parser.parse_args(argv)
    if sys.stdin.isatty():
        print("Error: report body must be piped to stdin.", file=sys.stderr)
        return 2
    out = persist_system_simulation_report(
        sys.stdin.read(),
        repo_root=args.repo_root,
        path=args.path,
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
