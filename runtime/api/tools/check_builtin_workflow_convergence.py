"""Report whether a boot converge would accept this database's built-ins.

``converge_builtin_workflows`` runs early in every boot, ahead of the migration
history, and it is fail-hard: a published built-in whose stored definition no
longer matches the code-owned one aborts startup with
``published built-in <id>@<n> differs from the code-owned definition``. That is
a fleet-wide crash-loop, and it has happened.

So the question "would rolling this wheel take the fleet down?" is worth being
able to answer *before* rolling it. This asks it read-only: it replicates the
same three-way comparison the converge performs, per published version, and
writes nothing.

    ok       stored digest and JSON already match the code-owned definition
    rewrite  differs byte-wise but the comparable forms agree, so the converge
             would rewrite the row to canonical and continue
    ABORT    comparable forms genuinely differ -- this is the crash

Exit status is 1 if any version would ABORT, so it can gate a release.

    YOKE_ENV=<env> python3 -m runtime.api.tools.check_builtin_workflow_convergence
"""

from __future__ import annotations

import sys

from yoke_core.domain import db_helpers
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
    builtin_workflow_version_history,
)
from yoke_core.domain.builtin_workflow_version_compat import _comparable_form
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    canonical_definition_json,
    decode_definition,
    definition_digest,
)
from yoke_core.domain.workflow_registry_rows import version_row


def _classify(existing, definition) -> str:
    """The converge's own decision, without performing it."""
    if str(existing["definition_digest"]) == definition_digest(
        definition
    ) and str(existing["definition_json"]) == canonical_definition_json(definition):
        return "ok"
    try:
        stored = decode_definition(existing["definition_json"])
    except WorkflowRegistryError:
        return "ABORT"
    if canonical_definition_json(_comparable_form(stored)) == canonical_definition_json(
        _comparable_form(definition)
    ):
        return "rewrite"
    return "ABORT"


def main(argv: list[str] | None = None) -> int:
    conn = db_helpers.connect()
    counts = {"ok": 0, "rewrite": 0, "ABORT": 0, "absent": 0}
    aborts: list[str] = []
    try:
        candidates = [
            (str(f["workflow"]["id"]), int(f["version"]), f["definition"])
            for f in builtin_workflow_version_history()
        ]
        for wf in builtin_workflow_definitions():
            candidates.append(
                (str(wf["workflow"]["id"]), int(wf["version"]), wf["definition"])
            )

        seen = set()
        for workflow_id, version, definition in candidates:
            if (workflow_id, version) in seen:
                continue
            seen.add((workflow_id, version))
            existing = version_row(conn, workflow_id, version)
            if existing is None:
                counts["absent"] += 1
                print(f"  absent  {workflow_id}@{version} (converge would insert)")
                continue
            verdict = _classify(existing, definition)
            counts[verdict] += 1
            if verdict == "ABORT":
                aborts.append(f"{workflow_id}@{version}")
                print(f"  ABORT   {workflow_id}@{version}")
            elif verdict == "rewrite":
                print(f"  rewrite {workflow_id}@{version}")
    finally:
        conn.close()

    print(
        f"\n{counts['ok']} ok, {counts['rewrite']} rewrite, "
        f"{counts['absent']} absent, {counts['ABORT']} ABORT"
    )
    if aborts:
        print(f"\nA boot converge would ABORT on: {', '.join(aborts)}")
        print("Rolling a new wheel against this database would crash-loop it.")
        return 1
    print("\nA boot converge would accept this database's built-ins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
