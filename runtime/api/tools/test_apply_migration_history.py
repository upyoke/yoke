"""The operator trigger supplies the same version guard as boot converge."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.tools import apply_migration_history as tool


class _Connection:
    def close(self) -> None:
        pass

    def commit(self) -> None:
        pass


def test_pending_apply_supplies_the_running_artifact_version(monkeypatch) -> None:
    entry = SimpleNamespace(name="0001_pending")
    seen = {}
    guard_repairs = []
    monkeypatch.setattr(tool, "ordered_entries", lambda _directory: (entry,))
    monkeypatch.setattr(tool, "history_dir", lambda _package: object())
    monkeypatch.setattr(tool.db_helpers, "connect", lambda: _Connection())
    monkeypatch.setattr(
        tool,
        "ensure_yoke_migration_ledger",
        lambda _conn, *, repair_existing_guards: guard_repairs.append(
            repair_existing_guards
        ),
    )
    monkeypatch.setattr(tool, "_hand_created_tables_to_the_serving_role", lambda _conn: None)
    monkeypatch.setattr(
        tool.migration_boot_apply,
        "pending_entries",
        lambda _conn, _history, _ledger: (entry,),
    )
    monkeypatch.setattr(
        tool.migration_boot_apply,
        "applied_names",
        lambda _conn, _ledger: set(),
    )
    monkeypatch.setattr(tool, "universe_is_born_on", lambda _conn: True)
    monkeypatch.setattr(
        tool, "configured_restore_point", lambda: (None, "snapshot:test")
    )
    monkeypatch.setattr(tool, "installed_engine_version", lambda: "4.2.0")

    def apply_pending(_conn, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(restore_point="snapshot:test", applied=(entry.name,))

    monkeypatch.setattr(tool.migration_boot_apply, "apply_pending", apply_pending)
    monkeypatch.setattr(
        tool.migration_fleet_ownership,
        "inspect",
        lambda _conn: SimpleNamespace(
            drifted=(), expected_owner="tenant", summary="uniform",
        ),
    )

    assert tool.main([]) == 0
    assert seen["running_version"] == "4.2.0"
    assert guard_repairs == [True]


def test_apply_hands_back_tables_that_drifted_during_apply(monkeypatch) -> None:
    entry = SimpleNamespace(name="0010_rebuild")
    reports = [
        SimpleNamespace(drifted=(), expected_owner="tenant", summary="before"),
        SimpleNamespace(
            drifted=(("environments", "yoke_admin"), ("sites", "yoke_admin")),
            expected_owner="tenant",
            summary="2 drifted",
        ),
        SimpleNamespace(drifted=(), expected_owner="tenant", summary="uniform"),
    ]
    realigned: list[list[str]] = []
    monkeypatch.setattr(tool, "ordered_entries", lambda _directory: (entry,))
    monkeypatch.setattr(tool, "history_dir", lambda _package: object())
    monkeypatch.setattr(tool.db_helpers, "connect", lambda: _Connection())
    monkeypatch.setattr(
        tool, "ensure_yoke_migration_ledger",
        lambda _conn, *, repair_existing_guards: None,
    )
    monkeypatch.setattr(tool, "_hand_created_tables_to_the_serving_role", lambda _conn: None)
    monkeypatch.setattr(
        tool.migration_boot_apply, "pending_entries",
        lambda _conn, _history, _ledger: (entry,),
    )
    monkeypatch.setattr(
        tool.migration_boot_apply, "applied_names",
        lambda _conn, _ledger: set(),
    )
    monkeypatch.setattr(tool, "universe_is_born_on", lambda _conn: True)
    monkeypatch.setattr(tool, "configured_restore_point", lambda: (None, "snapshot:test"))
    monkeypatch.setattr(tool, "installed_engine_version", lambda: "4.2.0")
    monkeypatch.setattr(
        tool.migration_boot_apply, "apply_pending",
        lambda _conn, **kwargs: SimpleNamespace(
            restore_point="snapshot:test", applied=(entry.name,),
        ),
    )
    monkeypatch.setattr(tool.migration_fleet_ownership, "inspect", lambda _conn: reports.pop(0))
    monkeypatch.setattr(
        tool.migration_fleet_ownership,
        "realign",
        lambda _conn, *, tables, owner: realigned.append(list(tables)) or list(tables),
    )

    assert tool.main([]) == 0
    assert realigned == [["environments", "sites"]]
