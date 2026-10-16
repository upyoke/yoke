# ruff: noqa: F811

"""Claimed-lane source execution covers migration-local imports."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.migration_apply_test_helpers import (
    _seed_apply_item,
    apply_env,  # noqa: F401 - fixture registration
)
from runtime.api.test_backlog import tmp_db  # noqa: F401 - fixture dependency
from yoke_core.tools import _source_pythonpath, source_dev_run


def test_source_runner_rehearses_migration_with_lane_only_import(
    apply_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = Path(apply_env["worktree"])
    (worktree / "packages/yoke-core/src/yoke_core").mkdir(
        parents=True,
        exist_ok=True,
    )
    (worktree / "lane_only_migration_support.py").write_text(
        "TABLE_NAME = 'lane_import_widgets'\n",
        encoding="utf-8",
    )
    (apply_env["modules_dir"] / "lane_import_migration.py").write_text(
        "from lane_only_migration_support import TABLE_NAME\n\n"
        "def apply(conn):\n"
        "    conn.execute(f'CREATE TABLE {TABLE_NAME} (id INTEGER PRIMARY KEY)')\n",
        encoding="utf-8",
    )
    item_id = 5040
    _seed_apply_item(
        apply_env["control_db"],
        item_id=item_id,
        modules=["lane_import_migration"],
    )
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda *_args: (worktree, None, None),
    )
    monkeypatch.setattr(
        _source_pythonpath,
        "import_origins",
        lambda _root, env, python: ({"runtime": str(worktree / "runtime")}, None),
    )

    probe = (
        "from pathlib import Path; "
        "from yoke_core.domain.migration_apply import format_rehearse, rehearse; "
        f"result = rehearse({item_id}, session_id='test-session', "
        f"control_db_path={apply_env['control_db']!r}, "
        f"worktree_path=Path({str(worktree)!r})); "
        "print(format_rehearse(result)); "
        "raise SystemExit(0 if result.all_succeeded else 1)"
    )

    assert source_dev_run.run(["python3", "-c", probe]) == 0


def test_selected_worker_reaches_public_rehearsal_runner(apply_env, monkeypatch):
    from runtime.api.fixtures.backlog import insert_item_worktree
    from runtime.api.fixtures.session_holdings import insert_item_claim
    from runtime.api.test_backlog import _conn
    from yoke_cli.commands.migration_rehearse import migration_rehearse
    from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
    from yoke_core.domain import migration_apply
    from yoke_core.domain.migration_apply_resolve import default_worktree_path

    worker = Path(apply_env["worktree"])
    integration = worker.parent / "integration"
    integration.mkdir()
    item_id = 5041
    public_ref = f"YOK-{item_id}"
    _seed_apply_item(apply_env["control_db"], item_id=item_id)
    with _conn(apply_env["control_db"]) as conn:
        insert_item_worktree(
            conn,
            item_id=item_id,
            branch="integration",
            path=str(integration),
            lane_role="integration",
        )
        insert_item_worktree(
            conn,
            item_id=item_id,
            branch="schema-worker",
            path=str(worker),
            lane_role="worker",
        )
        insert_item_claim(conn, "test-session", item_id)
        assert default_worktree_path(conn, item_id) == integration
    assert not (integration / "sample_migration.py").exists()

    def selected_root(selected):
        assert selected == worker
        return worker, None, None

    monkeypatch.setattr(source_dev_run, "_claimed_root", selected_root)
    monkeypatch.setattr(
        _source_pythonpath, "import_origins", lambda *_a, **_kw: ({}, None)
    )
    monkeypatch.setattr(
        migration_apply, "resolve_ambient_session_id", lambda: "test-session"
    )

    # Only the process boundary is in-process; the public adapter, authority
    # validation, target isolation, runner and durable receipt are real.
    def child(command, *, cwd, env, check):
        assert command[-3:] == ["migration", "rehearse", public_ref]
        assert cwd == env[SOURCE_DEV_RUN_ROOT_ENV] == str(worker)
        with monkeypatch.context() as child_context:
            child_context.setenv(SOURCE_DEV_RUN_ROOT_ENV, env[SOURCE_DEV_RUN_ROOT_ENV])
            child_context.chdir(cwd)
            return SimpleNamespace(returncode=migration_rehearse([public_ref]))

    monkeypatch.setattr(source_dev_run.subprocess, "run", child)
    assert (
        source_dev_run.run(["yoke", "migration", "rehearse", public_ref], lane=worker)
        == 0
    )
    with _conn(apply_env["control_db"]) as conn:
        receipt = conn.execute(
            "SELECT state, test_copy_path FROM migration_audit "
            "WHERE migration_name = %s",
            ("sample_migration",),
        ).fetchone()
        assert receipt[0] == "rehearsed"
        assert receipt[1].startswith("postgres-validation:")


@pytest.fixture(autouse=True)
def isolated_environment_probe(monkeypatch):
    import sys
    from yoke_core.domain.source_python_environment import SourcePythonEnvironment

    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(sys.executable, dict(env), {}),
    )
