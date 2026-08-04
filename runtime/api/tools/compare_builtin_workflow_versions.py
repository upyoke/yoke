"""Structurally diff two stored built-in workflow definitions.

Digests answer "are these the same?" and nothing else. When two universes
disagree about what a version number means, the useful question is *what
actually differs* -- which stages, which policies, which bindings -- because
that is what decides whether a divergence is cosmetic or a real publish.

Reads the connected environment's ``workflow_versions`` rows. Compares within
one database (two version numbers) or, with ``--other-env``, the same version
across two environments.

    python3 -m runtime.api.tools.compare_builtin_workflow_versions issue 3 4
    YOKE_ENV=stage-db-admin python3 -m runtime.api.tools.compare_builtin_workflow_versions issue 3 --other-env prod-db-admin
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


def _load(env: str, workflow_id: str, version: int) -> dict[str, Any] | None:
    """Read one stored definition through the sanctioned read path."""
    proc = subprocess.run(
        [
            "yoke", "db", "read",
            "SELECT definition_json FROM workflow_versions "
            f"WHERE workflow_id='{workflow_id}' AND version={version}",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "YOKE_ENV": env},
    )
    if proc.returncode != 0:
        raise SystemExit(f"read failed for {env} {workflow_id}@{version}: {proc.stderr[:400]}")
    rows = json.loads(proc.stdout)["rows"]
    if not rows:
        return None
    raw = rows[0][0]
    return json.loads(raw) if isinstance(raw, str) else raw


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten to leaf paths so a diff names the field, not the subtree."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            out.update(_flatten(sub, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            # Stages and bindings are identified by id where they have one, so
            # a reordering does not read as a rewrite of every element.
            label = sub.get("id") if isinstance(sub, dict) and sub.get("id") else index
            out.update(_flatten(sub, f"{prefix}[{label}]"))
    else:
        out[prefix] = value
    return out


def _diff(left: dict[str, Any], right: dict[str, Any], left_label: str, right_label: str) -> int:
    lf, rf = _flatten(left), _flatten(right)
    only_left = sorted(set(lf) - set(rf))
    only_right = sorted(set(rf) - set(lf))
    changed = sorted(k for k in set(lf) & set(rf) if lf[k] != rf[k])

    if not (only_left or only_right or changed):
        print(f"IDENTICAL: {left_label} == {right_label}")
        return 0

    print(f"{left_label}  vs  {right_label}")
    for key in only_left:
        print(f"  only in {left_label}: {key} = {lf[key]!r}")
    for key in only_right:
        print(f"  only in {right_label}: {key} = {rf[key]!r}")
    for key in changed:
        print(f"  changed: {key}: {lf[key]!r} -> {rf[key]!r}")
    print(f"  ({len(only_left)} removed, {len(only_right)} added, {len(changed)} changed)")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare-builtin-workflow-versions")
    parser.add_argument("workflow_id")
    parser.add_argument("version", type=int)
    parser.add_argument("other_version", type=int, nargs="?")
    parser.add_argument("--env", default=os.environ.get("YOKE_ENV", "prod-db-admin"))
    parser.add_argument("--other-env", help="Compare the same version across two environments.")
    args = parser.parse_args(argv)

    left = _load(args.env, args.workflow_id, args.version)
    if left is None:
        raise SystemExit(f"{args.env} has no {args.workflow_id}@{args.version}")
    left_label = f"{args.env} {args.workflow_id}@{args.version}"

    if args.other_env:
        right_version = args.other_version or args.version
        right = _load(args.other_env, args.workflow_id, right_version)
        right_label = f"{args.other_env} {args.workflow_id}@{right_version}"
    else:
        if args.other_version is None:
            raise SystemExit("give a second version or --other-env")
        right = _load(args.env, args.workflow_id, args.other_version)
        right_label = f"{args.env} {args.workflow_id}@{args.other_version}"
    if right is None:
        raise SystemExit(f"no such version: {right_label}")

    return _diff(left, right, left_label, right_label)


if __name__ == "__main__":
    sys.exit(main())
