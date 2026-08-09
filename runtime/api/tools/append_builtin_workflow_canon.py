"""Append the current built-in definitions to the published canon.

Changing a current definition means declaring a new published generation, and
the canon is where that declaration lives. Nothing derives history from the
current definition -- that derivation caused two fleet outages and is what the
literal canon replaced -- but the newest generation IS the current definition,
so appending it is the one direction that stays honest.

    python3 -m runtime.api.tools.append_builtin_workflow_canon \
        --target-root . --published-at 2026-08-09T00:00:00Z

Idempotent: a workflow whose current definition the canon already recognizes
has nothing to append and is reported as such. Only ever writes a new file --
an existing generation is never rewritten, because a stored digest that moves
is indistinguishable from corruption to every universe holding it.

Appending deliberately moves the canon pins in
``runtime/api/domain/test_builtin_workflow_canon.py``; the failure message
names the new values. Fleet effect: the next boot of every universe appends the
new definition at its own next version, and one still following the canon on an
unmodified definition moves onto it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

CANON_SUBPATH = Path(
    "packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon"
)


def _appendable(canon_dir: Path) -> list[dict]:
    """One record per workflow whose current definition is not yet canon."""
    from yoke_core.domain.builtin_workflow_canon import (
        canon_generations,
        recognize,
    )
    from yoke_core.domain.builtin_workflow_definitions import (
        builtin_workflow_definitions,
    )
    from yoke_core.domain.workflow_definition_codec import definition_digest

    pending = []
    for fixture in builtin_workflow_definitions():
        workflow_id = str(fixture["workflow"]["id"])
        definition = fixture["definition"]
        digest = definition_digest(definition)
        known = recognize(workflow_id, digest)
        generations = canon_generations(workflow_id)
        newest = generations[-1].canon_version if generations else 0
        pending.append({
            "workflow_id": workflow_id,
            "definition": definition,
            "digest": digest,
            "canon_version": newest + 1,
            "recognized_as": None if known is None else known.canon_version,
            "path": canon_dir / f"{workflow_id}.{newest + 1:02d}.json",
        })
    return pending


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="append-builtin-workflow-canon")
    parser.add_argument(
        "--target-root",
        required=True,
        help="Checkout whose canon directory receives the new generations.",
    )
    parser.add_argument(
        "--published-at",
        required=True,
        help="Timestamp recorded on each appended generation (ISO-8601 UTC).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    import json

    from yoke_core.domain.workspace_authority import (
        assert_target_under_session_work_authority,
    )

    target_root = Path(args.target_root).resolve()
    canon_dir = target_root / CANON_SUBPATH
    if not canon_dir.is_dir():
        print(f"no canon directory at {canon_dir}", file=sys.stderr)
        return 2
    if not args.dry_run:
        assert_target_under_session_work_authority(canon_dir)

    written = 0
    for record in _appendable(canon_dir):
        workflow_id = record["workflow_id"]
        if record["recognized_as"] is not None:
            print(
                f"{workflow_id}: already canon generation "
                f"{record['recognized_as']}; nothing to append"
            )
            continue
        path = record["path"]
        if path.exists():
            # The next number is taken, which means the canon on disk and the
            # generations loaded from it disagree. Overwriting would rewrite a
            # published digest, so stop instead.
            print(f"{path.name} already exists; refusing to rewrite", file=sys.stderr)
            return 1
        payload = {
            "canon_version": record["canon_version"],
            "definition": record["definition"],
            "observed_as": [],
            "published_at": args.published_at,
            "workflow_id": workflow_id,
        }
        action = "would append" if args.dry_run else "appending"
        print(
            f"{workflow_id}: {action} generation {record['canon_version']} "
            f"({record['digest'][:12]}) -> {path.name}"
        )
        if not args.dry_run:
            # Byte-identical formatting to what founded the canon, so an
            # appended generation is indistinguishable from an extracted one.
            path.write_text(
                json.dumps(
                    payload, indent=2, sort_keys=True, ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
        written += 1
    if written and not args.dry_run:
        print(
            f"appended {written} generation(s); update the canon pins in "
            "runtime/api/domain/test_builtin_workflow_canon.py"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
