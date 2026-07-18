"""CLI tests for explicit source-dev/admin path-snapshot prewarm."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_cli import main as yoke_operations_cli


def test_registry_and_inventory_track_dev_prewarm() -> None:
    # `yoke dev path-snapshot-prewarm` is a source-dev/admin client-local
    # helper with no dispatcher function id: it routes via the tool-shaped
    # table and is tracked as PERMANENT (tool-shaped), not WRAPPED, so
    # HC-fallback-registry-coherence does not expect a registered handler.
    from yoke_cli import operation_inventory as inv
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "path-snapshot-prewarm") not in SUBCOMMAND_REGISTRY
    assert ("dev", "path-snapshot-prewarm") in TOOL_SHAPED_SUBCOMMANDS
    entry = inv.lookup("yoke dev path-snapshot-prewarm")
    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED


def test_dev_prewarm_calls_snapshot_builders(monkeypatch, capsys) -> None:
    from yoke_cli.commands.adapters import dev as mod

    calls: list[tuple[str, str]] = []

    class Conn:
        closed = False

        def close(self) -> None:
            self.closed = True

    conn = Conn()

    def fake_import_module(name: str):
        if name == "yoke_core.domain.db_helpers":
            return SimpleNamespace(connect=lambda: conn)
        if name == "yoke_core.domain.path_snapshots":
            def build_head_snapshot(got_conn, project_id: str) -> int:
                assert got_conn is conn
                calls.append(("head", project_id))
                return 101
            return SimpleNamespace(build_head_snapshot=build_head_snapshot)
        if name == "yoke_core.domain.path_snapshots_integration_warm":
            def ensure_integration_target_snapshot(got_conn, project_id: str) -> int:
                assert got_conn is conn
                calls.append(("integration", project_id))
                return 202
            return SimpleNamespace(
                ensure_integration_target_snapshot=(
                    ensure_integration_target_snapshot
                )
            )
        raise AssertionError(name)

    monkeypatch.setattr(mod.importlib, "import_module", fake_import_module)
    rc = yoke_operations_cli.main([
        "dev", "path-snapshot-prewarm", "externalwebapp", "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "operation": "dev.path_snapshot_prewarm",
        "project_id": "externalwebapp",
        "head_snapshot_id": 101,
        "integration_snapshot_id": 202,
    }
    assert calls == [("head", "externalwebapp"), ("integration", "externalwebapp")]
    assert conn.closed is True


def test_dev_prewarm_uses_project_env_default(monkeypatch, capsys) -> None:
    from yoke_cli.commands.adapters import dev as mod

    monkeypatch.setenv(mod.PROJECT_ID_ENV, "yoke")
    monkeypatch.setattr(
        mod,
        "_run_path_snapshot_prewarm",
        lambda project_id: (11, None),
    )

    rc = yoke_operations_cli.main(["dev", "path-snapshot-prewarm", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_id"] == "yoke"
    assert payload["head_snapshot_id"] == 11
    assert payload["integration_snapshot_id"] is None


def test_dev_prewarm_reports_source_dev_failure(monkeypatch, capsys) -> None:
    from yoke_cli.commands.adapters import dev as mod

    def fail(_project_id: str):
        raise RuntimeError("no local DB")

    monkeypatch.setattr(mod, "_run_path_snapshot_prewarm", fail)

    rc = yoke_operations_cli.main(["dev", "path-snapshot-prewarm", "externalwebapp"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "source-dev/admin path-snapshot prewarm failed" in err
    assert "no local DB" in err
