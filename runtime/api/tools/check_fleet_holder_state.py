"""Read-only production proof of shared holder classification on served facts."""

from __future__ import annotations

import json
import subprocess

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, session_rows
from yoke_core.domain.session_state import session_needs_idle_alarm


def main() -> None:
    result = {"rows": []}
    for liveness in ("active", "waiting"):
        command = [
            "yoke",
            "sessions",
            "list",
            "--project",
            "yoke",
            "--full",
            "--liveness",
            liveness,
            "--limit",
            "100",
            "--json",
        ]
        response = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if response.returncode:
            raise SystemExit(
                "fleet_roster_read_failed: inspect yoke sessions list --liveness "
                + liveness
                + " --limit 100 --full --json"
            )
        payload = json.loads(response.stdout)
        if not payload.get("success"):
            raise SystemExit(
                "fleet_roster_read_failed: inspect the sessions.list refusal"
            )
        result["rows"].extend(payload["result"]["rows"])
    roster = session_rows(result)
    holders = [
        row for row in roster.values() if row.lifecycle == "live" and row.claimed_items
    ]
    if not holders or any(not row.session_state for row in holders):
        raise SystemExit(
            "shared_holder_state_unavailable: release the shared state build and retry"
        )
    expected = {
        row.session_id
        for row in holders
        if session_needs_idle_alarm(row.session_state)
        and not any(
            ref in row.landing_waits or ref in row.dependency_waits
            for ref in row.claimed_items
        )
    }
    snapshot = FleetSnapshot(
        taken_at=utc_now(),
        self_session_id="proof",
        sessions=roster,
        landing_waits=frozenset(ref for row in holders for ref in row.landing_waits),
    )
    lines = idle_holder_alarms(snapshot, DeltaState())
    actual = {
        row.session_id
        for row in holders
        if any(f"session={row.session_id} " in line for line in lines)
    }
    if actual != expected:
        raise SystemExit(
            "fleet_holder_classification_mismatch: inspect served session_state and idle-holder lines"
        )
    awaiting = sum(row.session_state["intent"]["state"] != "none" for row in holders)
    print(
        f"PASS: {len(holders)} served holders in active/waiting samples, {awaiting} declared waits, {len(actual)} idle alarms; no parked holder alarm"
    )


if __name__ == "__main__":
    main()
