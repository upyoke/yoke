"""Shared AC presence gate.

Python owner for ``.agents/skills/yoke/scripts/check-ac-presence.sh``.

Checks whether a backlog item has acceptance criteria checkboxes in its
spec (structured field first, body fallback). Two forms are accepted:

1. Canonical ``- [ ] AC-N: description`` anywhere in the content.
2. Unlabeled ``- [ ] description`` lines inside an ``## Acceptance Criteria``
   section. Unlabeled ACs trigger a stderr advisory but still satisfy the
   gate.

CLI contract::

    python3 -m yoke_core.domain.check_ac_presence <item-id>

Exit codes:
    0 — ACs present (count printed to stdout)
    1 — no ACs found
    2 — usage error / item not found
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Optional, Tuple

from yoke_core.domain import db_backend


CANONICAL_AC_RE = re.compile(r"(?m)^[ \t]*- \[ \] AC-\d+")
UNLABELED_CHECKBOX_RE = re.compile(r"(?m)^[ \t]*- \[ \] ")


def _normalize_item_id(raw: str) -> Optional[int]:
    stripped = raw.strip()
    if stripped.upper().startswith("YOK-"):
        stripped = stripped[4:]
    stripped = stripped.lstrip("0")
    if stripped == "":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def extract_ac_section(text: str) -> str:
    """Return the body of the ``## Acceptance Criteria`` section, if any.

    Leading whitespace on the heading line is ignored so that
    uniformly indented specs — a common artifact of heredoc authoring —
    still resolve a bounded section.
    """
    lines = text.split("\n")
    collecting = False
    collected: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("## Acceptance Criteria"):
            collecting = True
            continue
        if collecting and stripped.startswith("## "):
            break
        if collecting:
            collected.append(line)
    return "\n".join(collected)


def count_acs(text: str) -> Tuple[int, int]:
    """Return ``(canonical_count, unlabeled_count)`` for *text*.

    * canonical — matches anywhere in the text.
    * unlabeled — only counted inside the ``## Acceptance Criteria`` section
      when no canonical matches exist (empty string otherwise).
    """
    canonical = len(CANONICAL_AC_RE.findall(text))
    if canonical > 0:
        return canonical, 0
    ac_section = extract_ac_section(text)
    if not ac_section:
        return 0, 0
    unlabeled = len(UNLABELED_CHECKBOX_RE.findall(ac_section))
    return 0, unlabeled


def _fetch_item_row(item_id: int) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """Return ``(title, spec, body)`` for *item_id*, or ``None`` when missing."""
    try:
        from yoke_core.domain import db_helpers
    except Exception:
        return None
    try:
        with db_helpers.connect() as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = db_helpers.query_one(
                conn,
                f"SELECT title, spec FROM items WHERE id = {p}",
                (item_id,),
            )
            if row is None:
                return None
            # render body on demand instead of reading stored column
            from yoke_core.domain.render_body import build_body
            rendered = build_body(conn, item_id)
    except Exception:
        return None
    return (row["title"], row["spec"], rendered)


def evaluate_item(item_id: int) -> Tuple[int, int, Optional[str]]:
    """Inspect an item in the DB.

    Returns ``(canonical_count, unlabeled_count, title)``. ``title`` is
    ``None`` when the item cannot be found.
    """
    fetched = _fetch_item_row(item_id)
    if fetched is None:
        return 0, 0, None
    title, spec, body = fetched
    if not title:
        return 0, 0, None
    text = spec if spec else (body or "")
    canonical, unlabeled = count_acs(text)
    return canonical, unlabeled, title


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="check-ac-presence")
    parser.add_argument("item_id", help="Item ID (YOK-N, N, or padded form)")
    args = parser.parse_args(argv)

    number = _normalize_item_id(args.item_id)
    if number is None:
        print("Error: invalid item ID: %s" % args.item_id, file=sys.stderr)
        return 2

    canonical, unlabeled, title = evaluate_item(number)
    if title is None:
        print("Error: item YOK-%d not found" % number, file=sys.stderr)
        return 2

    if canonical > 0:
        print(canonical)
        return 0
    if unlabeled > 0:
        print(unlabeled)
        print(
            "Warning: YOK-%d has %d unlabeled checkbox AC(s) under ## Acceptance Criteria."
            % (number, unlabeled),
            file=sys.stderr,
        )
        print(
            "Canonical format is: - [ ] AC-N: {description}",
            file=sys.stderr,
        )
        print(
            "Run /yoke shepherd YOK-%d or normalize manually to canonical AC-N labels."
            % number,
            file=sys.stderr,
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
