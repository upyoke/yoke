"""Normalize unlabeled checkbox ACs to canonical ``AC-N`` form.

Python owner for ``.agents/skills/yoke/scripts/normalize-ac-labels.sh``.

Reads text from stdin or ``--file`` and rewrites unlabeled checkbox lines
under ``## Acceptance Criteria`` to the canonical
``- [ ] AC-N: description`` form. Already-labelled AC lines are preserved
and their numbering is respected — new labels continue from the highest
existing number.

Output is written to stdout. A count of normalizations is emitted on
stderr when any were performed.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Optional, Tuple


CANONICAL_AC_RE = re.compile(r"^- \[ \] AC-(\d+)")
UNLABELED_CHECKBOX_PREFIX = "- [ ] "
ACCEPTANCE_HEADING_PREFIX = "## Acceptance Criteria"
SECTION_PREFIX = "## "


def _highest_existing_ac(text: str) -> int:
    highest = 0
    for line in text.splitlines():
        match = CANONICAL_AC_RE.match(line)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if value > highest:
            highest = value
    return highest


def normalize(text: str) -> Tuple[str, int]:
    """Return ``(normalized_text, normalizations_applied)``.

    The returned text always ends with a trailing newline — matching the
    shell implementation's ``printf '%s\\n'`` loop.
    """
    next_ac = _highest_existing_ac(text) + 1
    normalized_count = 0
    in_section = False

    # Work line-by-line while preserving an empty final line if the input
    # ended with one.
    lines = text.split("\n")
    out_lines: list[str] = []

    for line in lines:
        if line.startswith(ACCEPTANCE_HEADING_PREFIX):
            in_section = True
            out_lines.append(line)
            continue
        if line.startswith(SECTION_PREFIX):
            in_section = False
            out_lines.append(line)
            continue

        if in_section:
            if line.startswith("- [ ] AC-"):
                out_lines.append(line)
                continue
            if line.startswith(UNLABELED_CHECKBOX_PREFIX):
                description = line[len(UNLABELED_CHECKBOX_PREFIX):]
                out_lines.append(
                    "- [ ] AC-%d: %s" % (next_ac, description)
                )
                next_ac += 1
                normalized_count += 1
                continue

        out_lines.append(line)

    joined = "\n".join(out_lines)
    if not joined.endswith("\n"):
        joined += "\n"
    return joined, normalized_count


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="normalize-ac-labels")
    parser.add_argument(
        "--file",
        dest="file",
        default=None,
        help="Read input from this file instead of stdin",
    )
    args = parser.parse_args(argv)

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            print("Error: file not found: %s" % args.file, file=sys.stderr)
            return 2
        except OSError as exc:
            print("Error: cannot read %s: %s" % (args.file, exc), file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()

    normalized, count = normalize(text)
    sys.stdout.write(normalized)
    sys.stdout.flush()
    if count > 0:
        print(
            "Normalized %d unlabeled AC(s) to canonical AC-N format." % count,
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
