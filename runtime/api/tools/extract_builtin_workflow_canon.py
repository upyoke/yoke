"""Extract the published built-in workflow canon from the live universes.

The canon is the set of definitions Yoke has actually published. It cannot be
derived from the current definition -- that derivation is the defect this
replaces -- so it is sourced from the universes that hold the published rows,
deduplicated by digest, and ordered by publish time.

Neither universe is a superset of the other: stage carries generations prod
never received, and prod carries at least one stage never did. The canon is
therefore the union, which is why this reads every environment given rather
than trusting a single authority.

Writes one JSON file per generation under the canon directory. Run once to
found the canon; afterwards the canon is append-only and lives in the repo.

    python3 -m runtime.api.tools.extract_builtin_workflow_canon \
        --env prod-db-admin --env stage-db-admin
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CANON_DIR = Path("packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon")
WORKFLOW_IDS = ("issue", "epic", "blitz", "dash", "task")


def _rows(env: str) -> list[tuple[str, int, str, str, str]]:
    ids = ",".join(f"'{w}'" for w in WORKFLOW_IDS)
    proc = subprocess.run(
        [
            "yoke", "db", "read",
            "SELECT workflow_id, version, definition_digest, published_at, "
            f"definition_json FROM workflow_versions WHERE workflow_id IN ({ids}) "
            "ORDER BY workflow_id, version",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "YOKE_ENV": env},
    )
    if proc.returncode != 0:
        raise SystemExit(f"read failed for {env}: {proc.stderr[:400]}")
    return [
        (str(r[0]), int(r[1]), str(r[2]), str(r[3]), str(r[4]))
        for r in json.loads(proc.stdout)["rows"]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extract-builtin-workflow-canon")
    parser.add_argument("--env", action="append", dest="envs", required=True)
    parser.add_argument("--canon-dir", type=Path, default=CANON_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # digest -> (workflow_id, earliest published_at, definition_json, seen_in)
    seen: dict[str, dict] = {}
    for env in args.envs:
        for workflow_id, version, digest, published_at, definition_json in _rows(env):
            entry = seen.get(digest)
            if entry is None:
                seen[digest] = {
                    "workflow_id": workflow_id,
                    "published_at": published_at,
                    "definition_json": definition_json,
                    "seen_in": {f"{env}@{version}"},
                }
            else:
                entry["seen_in"].add(f"{env}@{version}")
                entry["published_at"] = min(entry["published_at"], published_at)

    args.canon_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for workflow_id in WORKFLOW_IDS:
        entries = sorted(
            (d for d in seen.values() if d["workflow_id"] == workflow_id),
            key=lambda d: d["published_at"],
        )
        for index, entry in enumerate(entries, start=1):
            path = args.canon_dir / f"{workflow_id}.{index:02d}.json"
            payload = {
                "workflow_id": workflow_id,
                "canon_version": index,
                "published_at": entry["published_at"],
                "observed_as": sorted(entry["seen_in"]),
                "definition": json.loads(entry["definition_json"]),
            }
            body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            print(f"{'would write' if args.dry_run else 'wrote'} {path.name}  "
                  f"published={entry['published_at']}  seen={sorted(entry['seen_in'])}")
            if not args.dry_run:
                path.write_text(body, encoding="utf-8")
            written += 1
    print(f"\n{written} canon generations across {len(WORKFLOW_IDS)} workflows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
