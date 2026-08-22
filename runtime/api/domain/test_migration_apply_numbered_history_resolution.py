"""Governed runner resolution for permanent numbered migration history."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.migration_apply_runners import (
    RUNNER_KIND_GOVERNED_MODULE,
    dispatch_handle,
)


def test_profile_slug_resolves_numbered_history_entry(tmp_path: Path) -> None:
    modules = tmp_path / "migrations"
    modules.mkdir()
    entry = modules / "0015_session_surface.py"
    entry.write_text("def apply(conn):\n    pass\n", encoding="utf-8")
    model = {
        "authoritative_db": {
            "kind": "sqlite_file",
            "location": {"path": "authority.db"},
        },
        "validation_surface": {"kind": "worktree_local_sqlite"},
        "runner": {
            "kind": RUNNER_KIND_GOVERNED_MODULE,
            "config": {
                "modules_dir": "migrations",
                "connection_env_var": "APP_DB_PATH",
            },
        },
    }

    handle = dispatch_handle(
        model=model,
        repo_path=tmp_path,
        identifier="session_surface",
    )

    assert handle.identifier == "session_surface"
    assert handle.source_path == entry
