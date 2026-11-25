"""A fake SYSTEM runner for native Windows controls in unit tests."""

from __future__ import annotations

from yoke_contracts.machine_fixture_verify import MachineFixtureFailed
from yoke_harness.native_windows.machine_fixtures import UNDO_ORDER


def passing_undo_records():
    return [
        {"fixture": name, "operation": "undo", "ok": True, "state": {}}
        for name in UNDO_ORDER
    ]


class FakeSystemRunner:
    """Records each SYSTEM script; fails the undo when told to."""

    test_user = "yokeqa"

    def __init__(self, *, fail_undo=False, calls=None):
        self.system_scripts = []
        self.fail_undo = fail_undo
        self.calls = calls if calls is not None else []
        self.facts_refreshed = 0

    def run_system_script(self, script, *, timeout):
        self.calls.append("undo_fixtures")
        self.system_scripts.append(script)
        if self.fail_undo:
            records = passing_undo_records()
            records[1] = {"fixture": "applocker", "operation": "undo", "ok": False, "error": "applocker_not_undone"}
            raise MachineFixtureFailed(
                records=records, detail="SYSTEM script failed", recovery_hint="inspect"
            )
        return passing_undo_records()

    def refresh_host_facts(self):
        self.facts_refreshed += 1

    def project_public_key(self):
        return "ssh-ed25519 AAAAtest"
