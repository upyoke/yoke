"""The operator trigger supplies the same version guard as boot converge."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.tools import apply_migration_history as tool


class _Connection:
    def close(self) -> None:
        pass


def test_pending_apply_supplies_the_running_artifact_version(monkeypatch) -> None:
    entry = SimpleNamespace(name="0001_pending")
    seen = {}
    monkeypatch.setattr(tool, "ordered_entries", lambda _directory: (entry,))
    monkeypatch.setattr(tool, "history_dir", lambda _package: object())
    monkeypatch.setattr(tool.db_helpers, "connect", lambda: _Connection())
    monkeypatch.setattr(tool, "ensure_applied_migrations_table", lambda _conn: None)
    monkeypatch.setattr(tool, "_hand_created_tables_to_the_serving_role", lambda _conn: None)
    monkeypatch.setattr(
        tool.migration_boot_apply, "pending_entries", lambda _conn, _history: (entry,)
    )
    monkeypatch.setattr(tool.migration_boot_apply, "applied_names", lambda _conn: set())
    monkeypatch.setattr(tool, "universe_is_born_on", lambda _conn: True)
    monkeypatch.setattr(
        tool, "configured_restore_point", lambda: (None, "snapshot:test")
    )
    monkeypatch.setattr(tool, "installed_engine_version", lambda: "4.2.0")

    def apply_pending(_conn, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(restore_point="snapshot:test", applied=(entry.name,))

    monkeypatch.setattr(tool.migration_boot_apply, "apply_pending", apply_pending)

    assert tool.main([]) == 0
    assert seen["running_version"] == "4.2.0"
