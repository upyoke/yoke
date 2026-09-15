"""Emit live item-ref scanner findings for baseline maintenance.

With no flags this reports the prefix-literal counts the baseline ratchet
tracks. ``--message-text`` reports the prose scan instead, which has no baseline:
every hit is a bare ``items.id`` standing where a reference belongs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from yoke_core.domain.lint_item_ref_construction import counts_by_relpath, scan
from yoke_core.domain.lint_item_ref_message_text import scan_message_text_item_ids


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--message-text"]
    root = Path(argv[0]) if argv else Path.cwd()
    if "--message-text" in sys.argv[1:]:
        hits = scan_message_text_item_ids(root)
        for hit in hits:
            print(f"{hit.path.relative_to(root.resolve())}:{hit.line}: {hit.snippet}")
        print(f"message-text hits={len(hits)}")
        return 0
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
