"""Classify workflow-version digests that were read somewhere else.

The sibling checker reaches into a database itself. This one takes digests a
caller already has -- read from a remote host, pasted by an operator, quoted
in a report -- and answers the only question that matters about them: does the
canon recognize this content, and at which generation.

    python3 -m runtime.api.tools.classify_reported_workflow_digests \\
        --row issue:1:a663bad50366 --row issue:2:3daf973869d8

Digests may be given in full or as any unambiguous leading prefix, because
that is how they arrive from a truncated diagnostic read.
"""

from __future__ import annotations

import argparse
import json
import sys

from yoke_core.domain.builtin_workflow_canon import canon_generations


def _classify(workflow_id: str, version: int, digest: str) -> dict:
    matches = [
        generation
        for generation in canon_generations(workflow_id)
        if generation.digest.startswith(digest)
    ]
    if len(matches) > 1:
        return {
            "workflow_id": workflow_id,
            "version": version,
            "verdict": "ambiguous_prefix",
            "candidates": [g.canon_version for g in matches],
        }
    if not matches:
        return {
            "workflow_id": workflow_id,
            "version": version,
            "verdict": "unrecognized",
        }
    generation = matches[0]
    return {
        "workflow_id": workflow_id,
        "version": version,
        "verdict": "recognized",
        "canon_version": generation.canon_version,
        # A universe numbering a published generation differently is normal:
        # it published on its own schedule. Naming it separately keeps that
        # from reading as a defect.
        "numbering": (
            "same" if generation.canon_version == version else "shifted"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--row",
        action="append",
        dest="rows",
        required=True,
        metavar="WORKFLOW:VERSION:DIGEST",
        help="one stored row, repeatable",
    )
    args = parser.parse_args(argv)

    findings = []
    for raw in args.rows:
        try:
            workflow_id, version, digest = raw.split(":", 2)
            findings.append(_classify(workflow_id, int(version), digest))
        except ValueError:
            print(f"unparseable --row {raw!r}", file=sys.stderr)
            return 2

    print(json.dumps({"rows": findings}, indent=1))
    unrecognized = [f for f in findings if f["verdict"] != "recognized"]
    return 1 if unrecognized else 0


if __name__ == "__main__":
    raise SystemExit(main())
