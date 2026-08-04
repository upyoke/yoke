"""Classify every stored built-in workflow row against the code's canon.

Two very different things look identical to boot convergence today: a universe
that legitimately published a generation on its own schedule, and a universe
whose row was corrupted or hand-edited. Both simply "differ from the
code-owned definition". Deciding whether customization is a real, present
concern -- or whether all divergence so far is release skew -- needs that
distinction drawn explicitly.

For each stored row this reports one of:

* ``canon@N``    -- byte-identical to the canonical definition at its own
                    version number. Nothing to see.
* ``skew@M``     -- byte-identical to a canonical definition at a *different*
                    number. The universe published the same content on its own
                    schedule; only the numbering diverged.
* ``unmatched``  -- matches no canonical definition the code can produce.
                    Either a local customization or a generation the code can
                    no longer reproduce, which is itself the reconstruction bug.

    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.check_builtin_workflow_customization
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_codec import definition_digest


def _canon_digests() -> dict[str, dict[str, int]]:
    """Map workflow id -> {digest: canonical version} across all code fixtures."""
    out: dict[str, dict[str, int]] = {}
    for fixture in [*builtin_workflow_version_history(), *builtin_workflow_definitions()]:
        workflow_id = str(fixture["workflow"]["id"])
        version = int(fixture["canon_version"])
        digest = definition_digest(fixture["definition"])
        out.setdefault(workflow_id, {})[digest] = version
    return out


def _stored_rows(env: str) -> list[tuple[str, int, str]]:
    proc = subprocess.run(
        [
            "yoke", "db", "read",
            "SELECT workflow_id, version, definition_digest FROM workflow_versions "
            "WHERE workflow_id IN ('issue','epic','blitz','dash') "
            "ORDER BY workflow_id, version",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "YOKE_ENV": env},
    )
    if proc.returncode != 0:
        raise SystemExit(f"read failed for {env}: {proc.stderr[:400]}")
    return [(str(r[0]), int(r[1]), str(r[2])) for r in json.loads(proc.stdout)["rows"]]


def _report(env: str, canon: dict[str, dict[str, int]]) -> dict[str, int]:
    tally = {"canon": 0, "skew": 0, "unmatched": 0}
    print(f"=== {env} ===")
    for workflow_id, version, digest in _stored_rows(env):
        known = canon.get(workflow_id, {})
        matched = known.get(digest)
        if matched == version:
            verdict, tally_key = f"canon@{version}", "canon"
        elif matched is not None:
            verdict, tally_key = f"skew@{matched}", "skew"
        else:
            verdict, tally_key = "unmatched", "unmatched"
        tally[tally_key] += 1
        flag = "  " if tally_key == "canon" else "->"
        print(f" {flag} {workflow_id}@{version:<2} {digest[:16]}  {verdict}")
    print(f"    {tally['canon']} canon, {tally['skew']} skew, {tally['unmatched']} unmatched")
    return tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-builtin-workflow-customization")
    parser.add_argument("--env", action="append", dest="envs")
    args = parser.parse_args(argv)
    envs = args.envs or [os.environ.get("YOKE_ENV", "prod-db-admin")]

    canon = _canon_digests()
    print(f"code canon: {sum(len(v) for v in canon.values())} distinct definitions\n")
    for env in envs:
        _report(env, canon)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
