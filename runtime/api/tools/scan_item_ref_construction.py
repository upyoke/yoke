"""Emit live item-ref-construction scanner counts for baseline maintenance."""

from __future__ import annotations

import sys
from pathlib import Path

from yoke_core.domain.lint_item_ref_construction import counts_by_relpath, scan


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    prefixes = ["YOK", "PLAT", "BUZ", "EXT"]
    hits = scan(root, prefixes)
    counts = counts_by_relpath(root, hits)
    total = sum(counts.values())
    print(f"files={len(counts)} total={total}")
    for rel, count in sorted(counts.items()):
        print(f"{rel}:{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
