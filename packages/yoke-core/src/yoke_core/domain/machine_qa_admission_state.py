"""Real-state proof for the Machine QA admission fixture.

``start`` saves a baseline of the disposable universe right after it is
born; the post-state assertion compares the universe's actual rows with it,
rather than trusting the journey's success text. It reads only who exists,
which machines are registered to whom, which credentials are active for
which actor and machine, which provider subjects are linked, and which
teammate invites were consumed for which person and machine. It never reads
or prints a credential or invite value.
"""

from __future__ import annotations

from collections import Counter
import json
from typing import Any

from yoke_core.domain.machine_qa_admission_host import (
    OWNER_NAME,
    TEAMMATE_SUBJECT,
    AdmissionFixtureError,
    mode_root,
    universe_dsn,
    write_private,
)

EXPECTATIONS = {
    "local": frozenset({"nothing-admitted"}),
    "self-hosted": frozenset(
        {"nothing-admitted", "owner-admitted", "teammate-admitted"}
    ),
    "self-hosted-company-sign-in": frozenset({"nothing-admitted", "teammate-admitted"}),
}


def snapshot(mode: str) -> dict[str, Any]:
    """Read the admission-relevant rows of the mode's disposable universe."""
    import psycopg

    with psycopg.connect(universe_dsn(mode)) as conn:
        humans = conn.execute(
            "SELECT id, name FROM actors WHERE kind = 'human' ORDER BY id"
        ).fetchall()
        machines = conn.execute(
            "SELECT machine_id, owner_actor_id FROM machines "
            "WHERE retired_at IS NULL ORDER BY machine_id"
        ).fetchall()
        tokens = conn.execute(
            "SELECT actor_id, machine_id FROM api_tokens "
            "WHERE status = 'active' ORDER BY id"
        ).fetchall()
        invites = conn.execute(
            "SELECT actor_id, consumed_machine_id FROM teammate_invite_codes "
            "WHERE consumed_at IS NOT NULL ORDER BY id"
        ).fetchall()
        identities = conn.execute(
            "SELECT subject, actor_id FROM actor_external_identities ORDER BY id"
        ).fetchall()
    owners = [actor_id for actor_id, name in humans if name == OWNER_NAME]
    return {
        "humans": [actor_id for actor_id, _name in humans],
        "owner_actor_id": owners[0] if len(owners) == 1 else None,
        "machines": {machine_id: owner for machine_id, owner in machines},
        "tokens": [[actor_id, machine_id] for actor_id, machine_id in tokens],
        "identities": {subject: actor_id for subject, actor_id in identities},
        "consumed_invites": [list(row) for row in invites],
    }


def save_baseline(mode: str) -> dict[str, Any]:
    baseline = snapshot(mode)
    write_private(
        mode_root(mode) / "baseline.json", json.dumps(baseline, sort_keys=True) + "\n"
    )
    return {
        "humans": len(baseline["humans"]),
        "machines": len(baseline["machines"]),
        "active_tokens": len(baseline["tokens"]),
    }


def admission_changes(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Name every human, machine and credential added since the baseline."""
    machines = {
        machine_id: owner
        for machine_id, owner in current["machines"].items()
        if baseline["machines"].get(machine_id) != owner
    }
    tokens = Counter(map(tuple, current["tokens"])) - Counter(
        map(tuple, baseline["tokens"])
    )
    return {
        "new_humans": sorted(set(current["humans"]) - set(baseline["humans"])),
        "new_machines": machines,
        "new_tokens": sorted([list(row) for row in tokens.elements()]),
    }


def expectation_failures(
    mode: str,
    expect: str,
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Return why the universe does not show exactly the expected admission."""
    changes = admission_changes(baseline, current)
    humans, machines, tokens = (
        changes["new_humans"],
        changes["new_machines"],
        changes["new_tokens"],
    )
    if expect == "nothing-admitted":
        return [f"{name} changed: {value}" for name, value in changes.items() if value]
    failures = []
    if len(machines) != 1:
        return [f"expected exactly one newly admitted machine, found {machines}"]
    ((machine_id, owner),) = machines.items()
    if expect == "owner-admitted":
        if owner != baseline["owner_actor_id"]:
            failures.append(f"machine {machine_id} belongs to {owner}, not the owner")
        if humans:
            failures.append(f"owner approval created people {humans}")
    else:
        if humans != [owner]:
            failures.append(
                f"machine {machine_id} belongs to {owner}; new people are {humans}"
            )
        if owner == baseline["owner_actor_id"]:
            failures.append("the teammate's machine belongs to the owner")
        if (
            mode == "self-hosted-company-sign-in"
            and current["identities"].get(TEAMMATE_SUBJECT) != owner
        ):
            failures.append("the company identity is not linked to the teammate")
        if mode == "self-hosted" and current["consumed_invites"] != [
            [owner, machine_id]
        ]:
            failures.append(
                f"expected one invite for {owner} consumed by {machine_id}, "
                f"found {current['consumed_invites']}"
            )
    if tokens != [[owner, machine_id]]:
        failures.append(
            f"expected one active credential for {owner} on {machine_id}, "
            f"found {tokens}"
        )
    return failures


def assert_state(mode: str, expect: str) -> dict[str, Any]:
    """Compare the universe with its baseline; refuse by name on mismatch."""
    if expect not in EXPECTATIONS.get(mode, ()):
        raise AdmissionFixtureError(
            f"machine_admission_expectation_unknown: {expect!r} for {mode!r}; "
            f"use one of {sorted(EXPECTATIONS.get(mode, ()))}"
        )
    path = mode_root(mode) / "baseline.json"
    if not path.is_file():
        raise AdmissionFixtureError(
            "machine_admission_baseline_missing: the fixture did not record "
            "its starting state; run fixture.machine-admission-prepare first."
        )
    baseline = json.loads(path.read_text(encoding="utf-8"))
    current = snapshot(mode)
    failures = expectation_failures(mode, expect, baseline, current)
    report = {"mode": mode, "expect": expect, **admission_changes(baseline, current)}
    if failures:
        raise AdmissionFixtureError(
            "machine_admission_state_mismatch: "
            + "; ".join(failures)
            + f". Evidence: {json.dumps(report, sort_keys=True)}. Read the "
            "journey transcript for the step that admitted the wrong subject, "
            "then rerun the case."
        )
    return report


__all__ = [
    "EXPECTATIONS",
    "admission_changes",
    "assert_state",
    "expectation_failures",
    "save_baseline",
    "snapshot",
]
